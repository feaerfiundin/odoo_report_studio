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
    {"type": "text", "content": "testo statico", "class": "..."}
    {"type": "field", "path": "partner_id.name"}
    {"type": "table", "source": "order_line",
     "columns": [{"path": "name", "label": "Descrizione"}]}
    {"type": "if", "path": "amount_total", "op": ">", "value": 0,
     "children": [...]}

Non vengono mai accettate espressioni Python libere: i confronti passano
solo da percorsi di campo validati e da letterali scalari.
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
TABLE_TYPES = ("one2many", "many2many")


class CompileError(ValueError):
    """La definizione del report non è valida."""


class _Context:
    def __init__(self, resolver):
        self.resolver = resolver
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


def _render_children(children, model, var, depth, ctx):
    if not isinstance(children, list):
        raise CompileError("'children' deve essere una lista")
    if len(children) > MAX_CHILDREN:
        raise CompileError("Troppi blocchi nello stesso livello")
    lines = []
    for child in children:
        lines.extend(_render_block(child, model, var, depth, ctx))
    return lines


def _render_block(block, model, var, depth, ctx):
    if depth > MAX_DEPTH:
        raise CompileError("Profondità massima dei blocchi superata")
    if not isinstance(block, dict):
        raise CompileError("Ogni blocco deve essere un oggetto")
    btype = block.get("type")

    if btype == "section":
        children = _render_children(
            block.get("children", []), model, var, depth + 1, ctx
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
        return ["<p%s>%s</p>" % (_css_attr(block.get("class")), escape(content))]

    if btype == "field":
        path = block.get("path")
        _check_path(path, model, ctx)
        return ['<span t-field="%s.%s"/>' % (var, path)]

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
        heads, cells = [], []
        for column in columns:
            if not isinstance(column, dict):
                raise CompileError("Ogni colonna deve essere un oggetto")
            cpath = column.get("path")
            _check_path(cpath, comodel, ctx)
            label = column.get("label", cpath)
            heads.append("<th>%s</th>" % escape(str(label)))
            cells.append('<td><span t-field="%s.%s"/></td>' % (line, cpath))
        return [
            '<table class="table table-sm">',
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
            block.get("children", []), model, var, depth + 1, ctx
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


def compile_definition(definition, model, report_key, resolver=None):
    """Compila una definizione in un template QWeb completo.

    :param definition: dict oppure stringa JSON con la definizione.
    :param model: nome tecnico del modello Odoo (es. ``sale.order``).
    :param report_key: chiave del template (``t-name``), es. ``report_studio.rs_report_1_v1``.
    :param resolver: callable ``(model, path) -> (tipo, comodel) | None``.
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

    ctx = _Context(resolver)
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
