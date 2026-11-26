# -*- coding: utf-8 -*-
"""Compilatore: definizione JSON di un report -> template QWeb.

Modulo puro, senza dipendenze da Odoo. La verifica dei campi è delegata
a un ``resolver(model_name, path)`` passato dal chiamante, che restituisce
``(tipo_campo, modello_relazione)`` oppure ``None`` se il percorso non è
valido.

Schema della definizione::

    {
      "layout": "basic" | "external",
      "children": [ <blocco>, ... ]
    }

Blocchi::

    {"type": "section", "class": "...", "children": [...]}
    {"type": "text", "content": "testo statico", "class": "...", "font": <font>}
    {"type": "field", "path": "partner_id.name",
     "label": "DDT num:", "label_font": <font>, "font": <font>}
    {"type": "table", "source": "order_line",
     "head_font": <font>, "body_font": <font>,
     "columns": [{"path": "name", "label": "Descrizione", "width": 50, "locked": false}]}

Carattere (tutte le chiavi facoltative; assente o vuoto = quello del layout)::

    {"size": 12, "bold": true, "italic": false, "underline": false}

``size`` è in punti (6-72); ``width`` delle colonne è in percentuale (0-100].
    {"type": "if", "path": "amount_total", "op": ">", "value": 0,
     "children": [...]}

Non vengono mai accettate espressioni Python libere: i confronti passano
solo da percorsi di campo validati e da letterali scalari.

Con ``annotate=True`` (vista visuale dell'editor) ogni blocco è avvolto in un
elemento con ``data-rs-path`` (posizione nell'albero, es. ``0.2.1``) e
``data-rs-type``; un blocco non valido diventa un segnaposto con il messaggio
d'errore invece di interrompere la compilazione, e un blocco condizionale resta
sempre visibile (il contenuto solo se la condizione è vera).
"""
import json
import re
from xml.sax.saxutils import escape

MAX_DEPTH = 10
MAX_CHILDREN = 200
MAX_COLUMNS = 30

FIELD_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
REPORT_KEY_RE = re.compile(r"^[a-z0-9_.]+$")
CSS_CLASS_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,100}$")
OPERATORS = ("==", "!=", ">", "<", ">=", "<=")
LAYOUTS = {"basic": "web.basic_layout", "external": "web.external_layout"}
FONT_SIZE_RANGE = (6, 72)
FONT_FLAGS = (("bold", "font-weight: bold"), ("italic", "font-style: italic"),
              ("underline", "text-decoration: underline"))
MAX_LABEL = 200
TABLE_TYPES = ("one2many", "many2many")


class CompileError(ValueError):
    """La definizione del report non è valida."""


class _Context:
    def __init__(self, resolver, annotate=False):
        self.resolver = resolver
        self.annotate = annotate
        self._counter = 0

    def new_var(self):
        self._counter += 1
        return "line_%d" % self._counter


def _attr(value):
    return escape(value, {'"': "&quot;"})


def _css_attr(css_class):
    # Nessuna classe: None oppure stringa vuota/solo spazi (default dell'editor).
    if css_class is None or (isinstance(css_class, str) and not css_class.strip()):
        return ""
    if not isinstance(css_class, str) or not CSS_CLASS_RE.match(css_class):
        raise CompileError("Classe CSS non valida: %r" % (css_class,))
    return ' class="%s"' % css_class


def _font_css(font):
    """Dichiarazioni CSS da un oggetto carattere validato ("" se nessuna)."""
    if font is None:
        return ""
    if not isinstance(font, dict):
        raise CompileError("Il carattere deve essere un oggetto")
    unknown = set(font) - {"size", "bold", "italic", "underline"}
    if unknown:
        raise CompileError("Proprietà del carattere non ammesse: %s" % ", ".join(sorted(unknown)))
    rules = []
    size = font.get("size")
    if size is not None:
        low, high = FONT_SIZE_RANGE
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not low <= size <= high:
            raise CompileError("Dimensione del carattere non valida: %r (da %d a %d pt)" % (size, low, high))
        rules.append("font-size: %gpt" % size)
    for key, css in FONT_FLAGS:
        value = font.get(key, False)
        if not isinstance(value, bool):
            raise CompileError("Valore non valido per %s: %r" % (key, value))
        if value:
            rules.append(css)
    return "; ".join(rules)


def _style_attr(*declarations):
    css = "; ".join(d for d in declarations if d)
    return ' style="%s"' % _attr(css) if css else ""


def _column_width(column):
    width = column.get("width")
    if width is None:
        return ""
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not 0 < width <= 100:
        raise CompileError("Larghezza della colonna non valida: %r (in %%, da 0 a 100)" % (width,))
    if not isinstance(column.get("locked", False), bool):
        raise CompileError("'locked' della colonna deve essere vero o falso")
    return "width: %g%%" % width


def _check_path(path, model, ctx):
    """Valida un percorso di campo e ritorna (tipo, modello_relazione)."""
    if not isinstance(path, str) or not FIELD_PATH_RE.match(path):
        raise CompileError("Percorso di campo non valido: %r" % (path,))
    if ctx.resolver is None or model is None:
        return None, None
    result = ctx.resolver(model, path)
    if result is None:
        raise CompileError("Campo %r non esistente sul modello %s" % (path, model))
    return result


def _literal(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    raise CompileError("Valore di confronto non ammesso: %r" % (value,))


def _render_children(children, model, var, depth, ctx, tree_path=""):
    if not isinstance(children, list):
        raise CompileError("'children' deve essere una lista")
    if len(children) > MAX_CHILDREN:
        raise CompileError("Troppi blocchi nello stesso livello")
    lines = []
    for index, child in enumerate(children):
        child_path = "%s.%d" % (tree_path, index) if tree_path else str(index)
        if ctx.annotate:
            lines.extend(_render_annotated(child, model, var, depth, ctx, child_path))
        else:
            lines.extend(_render_block(child, model, var, depth, ctx, child_path))
    return lines


def _render_annotated(block, model, var, depth, ctx, tree_path):
    """Blocco per la vista visuale: avvolto e marcato, errori come segnaposto."""
    btype = block.get("type") if isinstance(block, dict) else None
    tag = "span" if btype == "field" else "div"
    btype_attr = _attr(btype) if isinstance(btype, str) else "unknown"
    try:
        inner = _render_block(block, model, var, depth, ctx, tree_path)
        css = "o_rs_cv_block"
    except CompileError as exc:
        inner = ['<span class="o_rs_cv_error">%s</span>' % escape(str(exc))]
        css = "o_rs_cv_block o_rs_cv_invalid"
    return (
        ['<%s class="%s o_rs_cv_%s" data-rs-path="%s" data-rs-type="%s">'
         % (tag, css, btype_attr, tree_path, btype_attr)]
        + inner
        + ["</%s>" % tag]
    )


def _render_block(block, model, var, depth, ctx, tree_path=""):
    if depth > MAX_DEPTH:
        raise CompileError("Profondità massima dei blocchi superata")
    if not isinstance(block, dict):
        raise CompileError("Ogni blocco deve essere un oggetto")
    btype = block.get("type")

    if btype == "section":
        children = _render_children(
            block.get("children", []), model, var, depth + 1, ctx, tree_path
        )
        return (
            ["<div%s>" % _css_attr(block.get("class"))]
            + children
            + ["</div>"]
        )

    if btype == "text":
        content = block.get("content", "")
        if not isinstance(content, str):
            raise CompileError("'content' deve essere una stringa")
        return ["<p%s%s>%s</p>" % (
            _css_attr(block.get("class")),
            _style_attr(_font_css(block.get("font"))),
            escape(content),
        )]

    if btype == "field":
        path = block.get("path")
        _check_path(path, model, ctx)
        value = '<span t-field="%s.%s"%s/>' % (var, path, _style_attr(_font_css(block.get("font"))))
        label = block.get("label") or ""
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            raise CompileError("Etichetta del campo non valida")
        if not label.strip():
            return [value]
        # Etichetta + spazio indivisibile + valore, sulla stessa riga.
        return ['<span><span class="o_rs_label"%s>%s</span>&#160;%s</span>' % (
            _style_attr(_font_css(block.get("label_font"))), escape(label), value,
        )]

    if btype == "table":
        source = block.get("source")
        ftype, comodel = _check_path(source, model, ctx)
        if ftype is not None and ftype not in TABLE_TYPES:
            raise CompileError(
                "La sorgente della tabella %r deve essere one2many o many2many"
                % source
            )
        columns = block.get("columns")
        if not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS:
            raise CompileError("'columns' deve essere una lista non vuota")
        line = ctx.new_var()
        head_css = _font_css(block.get("head_font"))
        body_css = _font_css(block.get("body_font"))
        heads, cells, widths = [], [], []
        for column in columns:
            if not isinstance(column, dict):
                raise CompileError("Ogni colonna deve essere un oggetto")
            cpath = column.get("path")
            _check_path(cpath, comodel, ctx)
            label = column.get("label", cpath)
            width = _column_width(column)
            widths.append(width)
            heads.append("<th%s>%s</th>" % (_style_attr(width, head_css), escape(str(label))))
            cells.append('<td%s><span t-field="%s.%s"/></td>' % (_style_attr(body_css), line, cpath))
        # Con larghezze impostate la tabella le rispetta (layout fisso).
        table_style = _style_attr("table-layout: fixed; width: 100%" if any(widths) else "")
        return [
            '<table class="table table-sm"%s>' % table_style,
            "<thead><tr>%s</tr></thead>" % "".join(heads),
            "<tbody>",
            '<t t-foreach="%s.%s" t-as="%s">' % (var, source, line),
            "<tr>%s</tr>" % "".join(cells),
            "</t>",
            "</tbody>",
            "</table>",
        ]

    if btype == "if":
        path = block.get("path")
        op = block.get("op")
        value = block.get("value")
        _check_path(path, model, ctx)
        if op not in OPERATORS:
            raise CompileError("Operatore non ammesso: %r" % (op,))
        expression = "%s.%s %s %s" % (var, path, op, _literal(value))
        children = _render_children(
            block.get("children", []), model, var, depth + 1, ctx, tree_path
        )
        if ctx.annotate:
            # Nell'editor il blocco resta selezionabile anche a condizione falsa.
            return (
                ['<div class="o_rs_cv_if_label">Se %s %s %s</div>'
                 % (escape(str(path)), escape(op), escape(_literal(value)))]
                + ['<t t-if="%s">' % _attr(expression)]
                + children
                + ["</t>",
                   '<t t-else=""><div class="o_rs_cv_if_false">'
                   "Condizione falsa per questo record: contenuto nascosto</div></t>"]
            )
        return (
            ['<t t-if="%s">' % _attr(expression)]
            + children
            + ["</t>"]
        )

    raise CompileError("Tipo di blocco sconosciuto: %r" % (btype,))


def _compile_qweb(definition, report_key):
    """Modalità QWeb libero: il template è usato così com'è, con il nome cambiato.

    Il template deve già contenere il proprio layout (es. web.external_layout),
    come i documenti nativi copiati in Report Studio.
    """
    arch = definition.get("arch")
    if not isinstance(arch, str) or not arch.strip():
        raise CompileError("Il template QWeb è vuoto")
    arch, count = re.subn(r't-name="[^"]*"', 't-name="%s"' % report_key, arch, count=1)
    if count == 0:
        arch = '<t t-name="%s">%s</t>' % (report_key, arch)
    return arch


def compile_definition(definition, model, report_key, resolver=None, annotate=False):
    """Compila una definizione in un template QWeb completo.

    :param definition: dict oppure stringa JSON con la definizione.
    :param model: nome tecnico del modello Odoo (es. ``sale.order``).
    :param report_key: chiave del template (``t-name``), es. ``report_studio.rs_report_1_v1``.
    :param resolver: callable ``(model, path) -> (tipo, comodel) | None``.
    :param annotate: marca i blocchi per la vista visuale dell'editor (mai nei PDF salvati).
    :returns: stringa XML del template.
    """
    if not isinstance(report_key, str) or not REPORT_KEY_RE.match(report_key):
        raise CompileError("Chiave del report non valida: %r" % (report_key,))

    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except ValueError as exc:
            raise CompileError("JSON non valido: %s" % exc)
    if not isinstance(definition, dict):
        raise CompileError("La definizione deve essere un oggetto JSON")

    if definition.get("mode") == "qweb":
        return _compile_qweb(definition, report_key)

    layout = definition.get("layout", "external")
    if layout not in LAYOUTS:
        raise CompileError("Layout non ammesso: %r" % (layout,))

    ctx = _Context(resolver, annotate=annotate)
    body = _render_children(definition.get("children", []), model, "o", 0, ctx)

    lines = [
        '<t t-name="%s">' % report_key,
        '<t t-call="web.html_container">',
        '<t t-foreach="docs" t-as="o">',
        '<t t-call="%s">' % LAYOUTS[layout],
        '<div class="page">',
    ]
    lines.extend(body)
    lines.extend(["</div>", "</t>", "</t>", "</t>", "</t>"])
    return "\n".join(lines)
