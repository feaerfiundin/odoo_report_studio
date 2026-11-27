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
    {"type": "separator", "style": "solid" | "dashed" | "dotted", "thickness": 1}
    {"type": "spacer", "height": 10}
    {"type": "page_break"}
    {"type": "columns", "divider": true, "margins": <margini>,
     "children": [{"type": "column", "margins": <margini>, "children": [...]}, ...]}

Sezione e Tabella accettano anche ``"margins": <margini>``. Margini (mm, tutti facoltativi)::

    {"top": 0, "right": 2, "bottom": 0, "left": 2}

Allineamento del testo (facoltativo, ``"align"``): ``left``, ``center``,
``right``, ``justify``. Vale per Testo, Sezione, Colonne, singola Colonna,
Tabella e singola colonna di tabella (intestazione e righe). Il documento è
allineato a sinistra; un blocco senza allineamento eredita quello del
contenitore e il più interno vince (ereditarietà di ``text-align`` in CSS).

Il blocco Colonne ha da 2 a 4 colonne, tutte di tipo ``column``; una colonna
può stare solo dentro un blocco Colonne. Nel PDF le colonne sono una tabella
senza bordi: il motore PDF di Odoo (wkhtmltopdf) non gestisce bene flexbox.

Lingue. I testi dei blocchi Testo, le etichette dei Campi e le intestazioni
delle colonne di tabella si possono tradurre::

    {"type": "text", "content": "Hello", "translations": {"it_IT": "Ciao"}}
    {"type": "field", "label": "Order", "label_translations": {"it_IT": "Ordine"}}
    colonna: {"label": "Qty", "label_translations": {"it_IT": "Qtà"}}

Il testo base (``content`` / ``label``) è nella lingua principale
(``"base_lang"`` della definizione, solo informativo) e vale per ogni lingua
senza traduzione. In stampa si sceglie il testo con la variabile QWeb
``rs_lang``: la lingua di stampa (``lang`` di Odoo, cioè quella di chi stampa).
Con ``"print_lang": {"enabled": true, "field": "partner_id"}`` la lingua è
quella del contatto indicato (``o.partner_id.lang``): la pagina diventa un
secondo template ``<chiave>_document`` chiamato con ``t-lang``, così anche i
campi di Odoo (nomi prodotto, selezioni, date) escono in quella lingua, come
nei documenti nativi. ``compile_templates`` restituisce tutti i template.

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
MARGIN_SIDES = ("top", "right", "bottom", "left")
MAX_MARGIN = 100           # mm
SPACER_RANGE = (1, 200)    # mm
SEPARATOR_STYLES = ("solid", "dashed", "dotted")
SEPARATOR_THICKNESS = (1, 5)  # px
COLUMNS_RANGE = (2, 4)
ALIGNS = ("left", "center", "right", "justify")
LANG_RE = re.compile(r"^[a-z]{2,3}(_[A-Za-z0-9]{2,8})?(@[a-z]+)?$")
MAX_TEXT = 10000
MAX_LANGS = 50
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


def _number(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise CompileError("%s non valido: %r (da %g a %g)" % (what, value, low, high))
    return value


def _align_css(align):
    """text-align da un allineamento validato ("" se assente: eredita)."""
    if align in (None, ""):
        return ""
    if align not in ALIGNS:
        raise CompileError("Allineamento non ammesso: %r" % (align,))
    return "text-align: %s" % align


def _margins_css(margins):
    """padding dai margini in mm ("" se assenti o tutti a zero)."""
    if margins is None:
        return ""
    if not isinstance(margins, dict) or set(margins) - set(MARGIN_SIDES):
        raise CompileError("Margini non validi: %r" % (margins,))
    values = [
        _number(margins.get(side) or 0, 0, MAX_MARGIN, "Margine (%s, mm)" % side)
        for side in MARGIN_SIDES
    ]
    if not any(values):
        return ""
    return "padding: %s" % " ".join("%gmm" % v for v in values)


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


def _translations(value, limit, what):
    """Traduzioni validate {codice lingua: testo}, senza quelle vuote."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_LANGS:
        raise CompileError("Traduzioni non valide (%s)" % what)
    result = {}
    for code, text in value.items():
        if not isinstance(code, str) or not LANG_RE.match(code):
            raise CompileError("Codice lingua non valido: %r" % (code,))
        if not isinstance(text, str) or len(text) > limit:
            raise CompileError("Traduzione non valida (%s, %s)" % (what, code))
        if text.strip():
            result[code] = text
    return result


def _by_lang(base, translations, render):
    """QWeb che sceglie il testo nella lingua di stampa (rs_lang); base se manca."""
    if not translations:
        return render(base)
    parts = []
    for index, code in enumerate(sorted(translations)):
        parts.append('<t t-%s="rs_lang == \'%s\'">%s</t>'
                     % ("if" if index == 0 else "elif", code, render(translations[code])))
    parts.append('<t t-else="">%s</t>' % render(base))
    return "".join(parts)


def _text_html(text):
    """Testo statico: escape e a capo come <br/>."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "<br/>".join(escape(line) for line in lines)


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


def _empty_placeholder(children, ctx, text):
    """Nell'editor un contenitore vuoto mostra un invito ad aggiungere blocchi."""
    if ctx.annotate and not children:
        return ['<div class="o_rs_cv_empty">%s</div>' % escape(text)]
    return []


def _render_annotated(block, model, var, depth, ctx, tree_path):
    """Blocco per la vista visuale: avvolto e marcato, errori come segnaposto."""
    btype = block.get("type") if isinstance(block, dict) else None
    # Un campo è in linea, salvo quando ha un allineamento proprio (diventa un blocco).
    tag = "span" if btype == "field" and not block.get("align") else "div"
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
        children = children or _empty_placeholder(children, ctx, "Sezione vuota: selezionala e aggiungi blocchi")
        return (
            ["<div%s%s>" % (
                _css_attr(block.get("class")),
                _style_attr(_margins_css(block.get("margins")), _align_css(block.get("align"))),
            )]
            + children
            + ["</div>"]
        )

    if btype == "separator":
        style = block.get("style", "solid")
        if style not in SEPARATOR_STYLES:
            raise CompileError("Stile del separatore non ammesso: %r" % (style,))
        thickness = _number(block.get("thickness", 1), *SEPARATOR_THICKNESS, what="Spessore del separatore (px)")
        return ['<div style="border-top: %gpx %s #333; margin: 2mm 0; height: 0"></div>' % (thickness, style)]

    if btype == "spacer":
        height = _number(block.get("height", 10), *SPACER_RANGE, what="Altezza dello spaziatore (mm)")
        return ['<div style="height: %gmm"></div>' % height]

    if btype == "page_break":
        lines = ['<div style="page-break-after: always; break-after: page"></div>']
        if ctx.annotate:
            lines.insert(0, '<div class="o_rs_cv_page_break">Interruzione di pagina</div>')
        return lines

    if btype == "columns":
        return _render_columns(block, model, var, depth, ctx, tree_path)

    if btype == "column":
        raise CompileError("Una colonna può stare solo dentro un blocco Colonne")

    if btype == "text":
        content = block.get("content", "")
        if not isinstance(content, str) or len(content) > MAX_TEXT:
            raise CompileError("'content' deve essere una stringa")
        translations = _translations(block.get("translations"), MAX_TEXT, "testo")
        # Ogni a capo del testo diventa un <br/> nel documento.
        return ["<p%s%s>%s</p>" % (
            _css_attr(block.get("class")),
            _style_attr(_align_css(block.get("align")), _font_css(block.get("font"))),
            _by_lang(content, translations, _text_html),
        )]

    if btype == "field":
        path = block.get("path")
        _check_path(path, model, ctx)
        value = '<span t-field="%s.%s"%s/>' % (var, path, _style_attr(_font_css(block.get("font"))))
        label = block.get("label") or ""
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            raise CompileError("Etichetta del campo non valida")
        if label.strip():
            # Etichetta + spazio indivisibile + valore, sulla stessa riga.
            value = '<span><span class="o_rs_label"%s>%s</span>&#160;%s</span>' % (
                _style_attr(_font_css(block.get("label_font"))),
                _by_lang(label, _translations(block.get("label_translations"), MAX_LABEL, "etichetta"), escape),
                value,
            )
        # text-align non vale su un elemento in linea: con un allineamento
        # proprio il campo va su una riga a sé, allineata.
        align = _align_css(block.get("align"))
        if align:
            value = '<div style="%s">%s</div>' % (align, value)
        return [value]

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
            # Le celle ricevono l'allineamento esplicito (colonna, altrimenti tabella):
            # il CSS dei report Odoo imposta quello delle intestazioni, che quindi
            # non lo erediterebbero dalla tabella.
            align = _align_css(column.get("align") or block.get("align"))
            heads.append("<th%s>%s</th>" % (_style_attr(width, align, head_css), _by_lang(
                str(label), _translations(column.get("label_translations"), MAX_LABEL, "intestazione"), escape)))
            cells.append('<td%s><span t-field="%s.%s"/></td>' % (_style_attr(align, body_css), line, cpath))
        # Con larghezze impostate la tabella le rispetta (layout fisso).
        table_style = _style_attr(
            "table-layout: fixed; width: 100%" if any(widths) else "",
            _align_css(block.get("align")),
        )
        table = [
            '<table class="table table-sm"%s>' % table_style,
            "<thead><tr>%s</tr></thead>" % "".join(heads),
            "<tbody>",
            '<t t-foreach="%s.%s" t-as="%s">' % (var, source, line),
            "<tr>%s</tr>" % "".join(cells),
            "</t>",
            "</tbody>",
            "</table>",
        ]
        # Margini: la tabella sta in un contenitore con padding.
        padding = _margins_css(block.get("margins"))
        if padding:
            table = ['<div style="%s">' % padding] + table + ["</div>"]
        return table

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


def _render_columns(block, model, var, depth, ctx, tree_path):
    """Blocco Colonne: tabella senza bordi a larghezze uguali, riga verticale facoltativa."""
    columns = block.get("children")
    low, high = COLUMNS_RANGE
    if not isinstance(columns, list) or not low <= len(columns) <= high:
        raise CompileError("Il blocco Colonne deve avere da %d a %d colonne" % (low, high))
    divider = block.get("divider", False)
    if not isinstance(divider, bool):
        raise CompileError("'divider' deve essere vero o falso")
    width = 100.0 / len(columns)
    cells = []
    for index, column in enumerate(columns):
        if not isinstance(column, dict) or column.get("type") != "column":
            raise CompileError("Il blocco Colonne può contenere solo colonne")
        column_path = "%s.%d" % (tree_path, index) if tree_path else str(index)
        css = ["width: %.4g%%" % width, "vertical-align: top", _margins_css(column.get("margins")),
               _align_css(column.get("align"))]
        if divider and index:
            css.append("border-left: 1px solid #333")
        marks = ""
        if ctx.annotate:
            # La colonna è selezionabile nell'editor (contenitore dei blocchi).
            marks = ' class="o_rs_cv_block o_rs_cv_column" data-rs-path="%s" data-rs-type="column"' % column_path
        children = _render_children(
            column.get("children", []), model, var, depth + 2, ctx, column_path
        )
        children = children or _empty_placeholder(children, ctx, "Colonna vuota")
        cells.extend(["<td%s%s>" % (marks, _style_attr(*css))] + children + ["</td>"])
    return (
        ["<div%s>" % _style_attr(_margins_css(block.get("margins")), _align_css(block.get("align"))),
         '<table style="width: 100%; table-layout: fixed; border-collapse: collapse"><tr>']
        + cells
        + ["</tr></table>", "</div>"]
    )


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


def _print_lang(definition, model, ctx):
    """Campo contatto da cui leggere la lingua di stampa, oppure None."""
    options = definition.get("print_lang")
    if options is None:
        return None
    if not isinstance(options, dict) or not isinstance(options.get("enabled", False), bool):
        raise CompileError("Opzione 'stampa nella lingua del cliente' non valida")
    if not options.get("enabled"):
        return None
    path = options.get("field") or "partner_id"
    ftype, comodel = _check_path(path, model, ctx)
    if ftype is not None and (ftype != "many2one" or comodel != "res.partner"):
        raise CompileError("Il campo %r non è un contatto (many2one a res.partner)" % path)
    return path


def _parse(definition, report_key):
    if not isinstance(report_key, str) or not REPORT_KEY_RE.match(report_key):
        raise CompileError("Chiave del report non valida: %r" % (report_key,))
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except ValueError as exc:
            raise CompileError("JSON non valido: %s" % exc)
    if not isinstance(definition, dict):
        raise CompileError("La definizione deve essere un oggetto JSON")
    base_lang = definition.get("base_lang")
    if base_lang is not None and not (isinstance(base_lang, str) and LANG_RE.match(base_lang)):
        raise CompileError("Lingua principale non valida: %r" % (base_lang,))
    return definition


def compile_templates(definition, model, report_key, resolver=None, annotate=False):
    """Compila una definizione nei template QWeb del report.

    :param definition: dict oppure stringa JSON con la definizione.
    :param model: nome tecnico del modello Odoo (es. ``sale.order``).
    :param report_key: chiave del template principale (``t-name``),
        es. ``report_studio.rs_report_1_v1``; è quella dell'azione di stampa.
    :param resolver: callable ``(model, path) -> (tipo, comodel) | None``.
    :param annotate: marca i blocchi per la vista visuale dell'editor (mai nei
        PDF salvati). La vista visuale usa sempre un solo template: la lingua
        è quella del contesto (la lingua che si sta modificando).
    :returns: lista di ``(chiave, xml)``; il primo è il template principale,
        il secondo (solo con la stampa nella lingua del cliente) la pagina.
    """
    definition = _parse(definition, report_key)
    if definition.get("mode") == "qweb":
        return [(report_key, _compile_qweb(definition, report_key))]

    layout = definition.get("layout", "external")
    if layout not in LAYOUTS:
        raise CompileError("Layout non ammesso: %r" % (layout,))

    ctx = _Context(resolver, annotate=annotate)
    lang_field = _print_lang(definition, model, ctx)
    body = _render_children(definition.get("children", []), model, "o", 0, ctx)
    page = [
        '<t t-call="%s">' % LAYOUTS[layout],
        # Allineamento di base del documento: a sinistra.
        '<div class="page" style="text-align: left">',
    ] + body + ["</div>", "</t>"]

    if lang_field is None or annotate:
        lines = [
            '<t t-name="%s">' % report_key,
            '<t t-call="web.html_container">',
            '<t t-foreach="docs" t-as="o">',
            # Lingua dei testi tradotti: quella di stampa.
            '<t t-set="rs_lang" t-value="lang"/>',
        ] + page + ["</t>", "</t>", "</t>"]
        return [(report_key, "\n".join(lines))]

    # Lingua del cliente: la pagina è un template a parte, chiamato con t-lang
    # (il contenuto di una t-call verrebbe reso nella lingua del chiamante).
    document_key = "%s_document" % report_key
    main = "\n".join([
        '<t t-name="%s">' % report_key,
        '<t t-call="web.html_container">',
        '<t t-foreach="docs" t-as="o">',
        '<t t-set="rs_lang" t-value="o.%s.lang or lang"/>' % lang_field,
        '<t t-call="%s" t-lang="rs_lang"/>' % document_key,
        "</t>", "</t>", "</t>",
    ])
    document = "\n".join(['<t t-name="%s">' % document_key] + page + ["</t>"])
    return [(report_key, main), (document_key, document)]


def compile_definition(definition, model, report_key, resolver=None, annotate=False):
    """Template principale (vedi ``compile_templates``); tutti i template uniti.

    Con la stampa nella lingua del cliente i template sono due: qui sono
    restituiti uno dopo l'altro (per i test e per la consultazione), mentre
    Odoo ne riceve uno per vista da ``compile_templates``.
    """
    return "\n".join(arch for _key, arch in compile_templates(
        definition, model, report_key, resolver=resolver, annotate=annotate))
