# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Compiler: JSON report definition -> QWeb templates.

Pure module, with no Odoo dependency. Field checks are delegated to a
``resolver(model_name, path)`` given by the caller, which returns
``(field_type, comodel_name)`` or ``None`` when the path is not valid.

Definition schema::

    {
      "layout": "basic" | "external",
      "children": [ <block>, ... ]
    }

Blocks::

    {"type": "section", "class": "...", "children": [...]}
    {"type": "text", "content": "static text", "class": "...", "font": <font>}
    {"type": "field", "path": "partner_id.name",
     "label": "Delivery no.:", "label_font": <font>, "font": <font>}
    {"type": "table", "source": "order_line",
     "head_font": <font>, "body_font": <font>,
     "columns": [{"path": "name", "label": "Description", "width": 50, "locked": false}]}
    {"type": "if", "path": "amount_total", "op": ">", "value": 0,
     "children": [...]}
    {"type": "separator", "style": "solid" | "dashed" | "dotted", "thickness": 1}
    {"type": "spacer", "height": 10}
    {"type": "page_break"}
    {"type": "columns", "divider": true, "margins": <margins>,
     "children": [{"type": "column", "margins": <margins>, "children": [...]}, ...]}

Font (every key optional; missing or empty = the layout's)::

    {"size": 12, "bold": true, "italic": false, "underline": false}

``size`` is in points (6-72); the ``width`` of table columns is a
percentage (0-100].

A Section can also have a label bar on top and borders::

    "title": {"text": "Customer", "translations": {...}, "background": "#e9ecef",
              "color": "#000000", "font": <font>, "align": "left"}
    "border": {"sides": ["top", "right", "bottom", "left"],
               "style": "solid" | "double" | "dashed" | "dotted",
               "width": 1, "color": "#333333"}

A Table can have a style (all keys optional) and per column background and
side borders::

    "style": {"head": {"background": "#..", "color": "#..", "height": 8},
              "rows": {"background": "#..", "alt_background": "#..",
                       "height": 6, "valign": "top" | "middle" | "bottom"},
              "borders": {"preset": "all" | "none" | "outer" | "horizontal"
                                    | "vertical" | "header",
                          "style": "solid", "width": 1, "color": "#333333"}}
    column: {"background": "#..", "border_left": true, "border_right": false}

The column background wins over the row backgrounds; the column borders use
the line of the table borders.

Section and Table also accept ``"margins": <margins>``. Margins (mm, all
optional)::

    {"top": 0, "right": 2, "bottom": 0, "left": 2}

Text alignment (optional, ``"align"``): ``left``, ``center``, ``right``,
``justify``. It applies to Text, Field, Section, Columns, single Column, Table
and single table column (header and rows). The document is left aligned; a
block without alignment inherits the one of its container and the innermost
wins (``text-align`` inheritance in CSS).

The Columns block has 2 to 4 columns, all of type ``column``; a column can
only live inside a Columns block. In the PDF the columns are a borderless
table: the Odoo PDF engine (wkhtmltopdf) does not handle flexbox well.

Languages. Text block contents, Field labels and table column headers can be
translated::

    {"type": "text", "content": "Hello", "translations": {"it_IT": "Ciao"}}
    {"type": "field", "label": "Order", "label_translations": {"it_IT": "Ordine"}}
    column: {"label": "Qty", "label_translations": {"it_IT": "Qtà"}}

The base text (``content`` / ``label``) is in the main language (the
definition's ``"base_lang"``, informative only) and is used for every
language without a translation. When printing, the text is chosen with the
QWeb variable ``rs_lang``: the print language (Odoo's ``lang``, i.e. the one
of the user printing). With ``"print_lang": {"enabled": true, "field":
"partner_id"}`` the language is the one of the given contact
(``o.partner_id.lang``): the page becomes a second template ``<key>_document``
called with ``t-lang``, so Odoo fields (product names, selections, dates) are
printed in that language too, as in the native documents.
``compile_templates`` returns all the templates.

Free Python expressions are never accepted: comparisons only use validated
field paths and scalar literals.

With ``annotate=True`` (visual view of the editor) every block is wrapped in
an element with ``data-rs-path`` (position in the tree, e.g. ``0.2.1``) and
``data-rs-type``; an invalid block becomes a placeholder with the error
message instead of stopping the compilation, and a conditional block stays
always visible (its content only when the condition is true).

Translations. Messages and placeholders are in English and marked with
``_()`` so that Odoo extracts them into the module's translation files. The
compiler never translates by itself: the caller passes a ``gettext`` function
(used for the editor placeholders) and translates errors with
``CompileError.translate(gettext)``.
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
FONT_FLAGS = (
    ("bold", "font-weight: bold"),
    ("italic", "font-style: italic"),
    ("underline", "text-decoration: underline"),
)
MAX_LABEL = 200
MARGIN_SIDES = ("top", "right", "bottom", "left")
MAX_MARGIN = 100  # mm
SPACER_RANGE = (1, 200)  # mm
SEPARATOR_STYLES = ("solid", "dashed", "dotted")
SEPARATOR_THICKNESS = (1, 5)  # px
COLUMNS_RANGE = (2, 4)
ALIGNS = ("left", "center", "right", "justify")
LANG_RE = re.compile(r"^[a-z]{2,3}(_[A-Za-z0-9]{2,8})?(@[a-z]+)?$")
MAX_TEXT = 10000
MAX_LANGS = 50
TABLE_TYPES = ("one2many", "many2many")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
BORDER_STYLES = ("solid", "double", "dashed", "dotted")
BORDER_WIDTH = (1, 6)  # px
BORDER_PRESETS = ("all", "none", "outer", "horizontal", "vertical", "header")
VALIGNS = ("top", "middle", "bottom")
ROW_HEIGHT = (1, 100)  # mm


class _Term(str):
    """A message marked for translation (see ``_``)."""


def _(message):
    """Mark a message for translation; it is translated by the caller."""
    return _Term(message)


MARGIN_LABELS = {
    "top": _("Top margin (mm)"),
    "right": _("Right margin (mm)"),
    "bottom": _("Bottom margin (mm)"),
    "left": _("Left margin (mm)"),
}


def _identity(text):
    return text


class CompileError(ValueError):
    """The report definition is not valid.

    ``message`` is an English template marked with ``_()``; ``args`` are its
    values. ``str()`` gives the English text, ``translate()`` the translated one.
    """

    def __init__(self, message, *args):
        super().__init__(message, *args)
        self.message = message
        self.args_values = args

    def translate(self, gettext=_identity):
        def value(arg):
            return gettext(arg) if isinstance(arg, _Term) else arg

        text = gettext(self.message)
        args = self.args_values
        if not args:
            return text
        if len(args) == 1 and isinstance(args[0], dict) and "%(" in self.message:
            return text % {key: value(val) for key, val in args[0].items()}
        return text % tuple(value(arg) for arg in args)

    def __str__(self):
        return self.translate()


class _Context:
    def __init__(self, resolver, annotate=False, gettext=None):
        self.resolver = resolver
        self.annotate = annotate
        self.gettext = gettext or _identity
        self._counter = 0

    def new_var(self):
        self._counter += 1
        return "line_%d" % self._counter


def _attr(value):
    return escape(value, {'"': "&quot;"})


def _css_attr(css_class):
    # No class: None or an empty/blank string (the editor default).
    if css_class is None or (isinstance(css_class, str) and not css_class.strip()):
        return ""
    if not isinstance(css_class, str) or not CSS_CLASS_RE.match(css_class):
        raise CompileError(_("Invalid CSS class: %r"), css_class)
    return ' class="%s"' % css_class


def _font_css(font):
    """CSS declarations from a validated font object ("" when none)."""
    if font is None:
        return ""
    if not isinstance(font, dict):
        raise CompileError(_("The font must be an object"))
    unknown = set(font) - {"size", "bold", "italic", "underline"}
    if unknown:
        raise CompileError(
            _("Font properties not allowed: %s"), ", ".join(sorted(unknown))
        )
    rules = []
    size = font.get("size")
    if size is not None:
        low, high = FONT_SIZE_RANGE
        if (
            isinstance(size, bool)
            or not isinstance(size, int | float)
            or not low <= size <= high
        ):
            raise CompileError(
                _("Invalid font size: %(size)r (%(low)d to %(high)d pt)"),
                {"size": size, "low": low, "high": high},
            )
        rules.append("font-size: %gpt" % size)
    for key, css in FONT_FLAGS:
        value = font.get(key, False)
        if not isinstance(value, bool):
            raise CompileError(
                _("Invalid value for %(key)s: %(value)r"), {"key": key, "value": value}
            )
        if value:
            rules.append(css)
    return "; ".join(rules)


def _style_attr(*declarations):
    css = "; ".join(d for d in declarations if d)
    return ' style="%s"' % _attr(css) if css else ""


def _number(value, low, high, what):
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not low <= value <= high
    ):
        raise CompileError(
            _("%(what)s is not valid: %(value)r (%(low)g to %(high)g)"),
            {"what": what, "value": value, "low": low, "high": high},
        )
    return value


def _align_css(align):
    """text-align from a validated alignment ("" when missing: inherited)."""
    if align in (None, ""):
        return ""
    if align not in ALIGNS:
        raise CompileError(_("Alignment not allowed: %r"), align)
    return "text-align: %s" % align


def _margins_css(margins):
    """Padding from the margins in mm ("" when missing or all zero)."""
    if margins is None:
        return ""
    if not isinstance(margins, dict) or set(margins) - set(MARGIN_SIDES):
        raise CompileError(_("Invalid margins: %r"), margins)
    values = [
        _number(margins.get(side) or 0, 0, MAX_MARGIN, MARGIN_LABELS[side])
        for side in MARGIN_SIDES
    ]
    if not any(values):
        return ""
    return "padding: %s" % " ".join("%gmm" % v for v in values)


def _column_width(column):
    width = column.get("width")
    if width is None:
        return ""
    if (
        isinstance(width, bool)
        or not isinstance(width, int | float)
        or not 0 < width <= 100
    ):
        raise CompileError(_("Invalid column width: %r (in %%, 0 to 100)"), width)
    if not isinstance(column.get("locked", False), bool):
        raise CompileError(_("The column 'locked' value must be true or false"))
    return "width: %g%%" % width


def _check_path(path, model, ctx):
    """Validate a field path and return (type, comodel)."""
    if not isinstance(path, str) or not FIELD_PATH_RE.match(path):
        raise CompileError(_("Invalid field path: %r"), path)
    if ctx.resolver is None or model is None:
        return None, None
    result = ctx.resolver(model, path)
    if result is None:
        raise CompileError(
            _("Field %(path)r does not exist on model %(model)s"),
            {"path": path, "model": model},
        )
    return result


def _translations(value, limit, what):
    """Validated translations {language code: text}, without the empty ones."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_LANGS:
        raise CompileError(_("Invalid translations (%s)"), what)
    result = {}
    for code, text in value.items():
        if not isinstance(code, str) or not LANG_RE.match(code):
            raise CompileError(_("Invalid language code: %r"), code)
        if not isinstance(text, str) or len(text) > limit:
            raise CompileError(
                _("Invalid translation (%(what)s, %(code)s)"),
                {"what": what, "code": code},
            )
        if text.strip():
            result[code] = text
    return result


def _by_lang(base, translations, render):
    """QWeb choosing the text in the print language (rs_lang); base when missing."""
    if not translations:
        return render(base)
    parts = []
    for index, code in enumerate(sorted(translations)):
        parts.append(
            "<t t-%s=\"rs_lang == '%s'\">%s</t>"
            % ("if" if index == 0 else "elif", code, render(translations[code]))
        )
    parts.append('<t t-else="">%s</t>' % render(base))
    return "".join(parts)


def _text_html(text):
    """Static text: escaped, line breaks as <br/>."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "<br/>".join(escape(line) for line in lines)


def _literal(value):
    if value is None or isinstance(value, bool | int | float | str):
        return repr(value)
    raise CompileError(_("Comparison value not allowed: %r"), value)


def _render_children(children, model, var, depth, ctx, tree_path=""):
    if not isinstance(children, list):
        raise CompileError(_("'children' must be a list"))
    if len(children) > MAX_CHILDREN:
        raise CompileError(_("Too many blocks on the same level"))
    lines = []
    for index, child in enumerate(children):
        child_path = "%s.%d" % (tree_path, index) if tree_path else str(index)
        if ctx.annotate:
            lines.extend(_render_annotated(child, model, var, depth, ctx, child_path))
        else:
            lines.extend(_render_block(child, model, var, depth, ctx, child_path))
    return lines


def _empty_placeholder(children, ctx, text):
    """In the editor an empty container invites to add blocks."""
    if ctx.annotate and not children:
        return ['<div class="o_rs_cv_empty">%s</div>' % escape(ctx.gettext(text))]
    return []


def _render_annotated(block, model, var, depth, ctx, tree_path):
    """Block for the visual view: wrapped and marked, errors as placeholders."""
    btype = block.get("type") if isinstance(block, dict) else None
    # A field is inline, unless it has its own alignment (then it is a block).
    tag = "span" if btype == "field" and not block.get("align") else "div"
    btype_attr = _attr(btype) if isinstance(btype, str) else "unknown"
    try:
        inner = _render_block(block, model, var, depth, ctx, tree_path)
        css = "o_rs_cv_block"
    except CompileError as exc:
        inner = [
            '<span class="o_rs_cv_error">%s</span>' % escape(exc.translate(ctx.gettext))
        ]
        css = "o_rs_cv_block o_rs_cv_invalid"
    return (
        [
            '<%s class="%s o_rs_cv_%s" data-rs-path="%s" data-rs-type="%s">'
            % (tag, css, btype_attr, tree_path, btype_attr)
        ]
        + inner
        + ["</%s>" % tag]
    )


def _render_block(block, model, var, depth, ctx, tree_path=""):
    if depth > MAX_DEPTH:
        raise CompileError(_("Maximum block depth exceeded"))
    if not isinstance(block, dict):
        raise CompileError(_("Every block must be an object"))
    btype = block.get("type")

    if btype == "section":
        return _render_section(block, model, var, depth, ctx, tree_path)

    if btype == "separator":
        style = block.get("style", "solid")
        if style not in SEPARATOR_STYLES:
            raise CompileError(_("Separator style not allowed: %r"), style)
        thickness = _number(
            block.get("thickness", 1),
            *SEPARATOR_THICKNESS,
            what=_("Separator thickness (px)"),
        )
        return [
            '<div style="border-top: %gpx %s #333; margin: 2mm 0; height: 0"></div>'
            % (thickness, style)
        ]

    if btype == "spacer":
        height = _number(
            block.get("height", 10), *SPACER_RANGE, what=_("Spacer height (mm)")
        )
        return ['<div style="height: %gmm"></div>' % height]

    if btype == "page_break":
        lines = ['<div style="page-break-after: always; break-after: page"></div>']
        if ctx.annotate:
            lines.insert(
                0,
                '<div class="o_rs_cv_page_break">%s</div>'
                % escape(ctx.gettext(_("Page break"))),
            )
        return lines

    if btype == "columns":
        return _render_columns(block, model, var, depth, ctx, tree_path)

    if btype == "column":
        raise CompileError(_("A column can only be inside a Columns block"))

    if btype == "text":
        content = block.get("content", "")
        if not isinstance(content, str) or len(content) > MAX_TEXT:
            raise CompileError(_("'content' must be a string"))
        translations = _translations(block.get("translations"), MAX_TEXT, _("text"))
        # Every line break of the text becomes a <br/> in the document.
        return [
            "<p%s%s>%s</p>"
            % (
                _css_attr(block.get("class")),
                _style_attr(
                    _align_css(block.get("align")), _font_css(block.get("font"))
                ),
                _by_lang(content, translations, _text_html),
            )
        ]

    if btype == "field":
        path = block.get("path")
        _check_path(path, model, ctx)
        value = '<span t-field="%s.%s"%s/>' % (
            var,
            path,
            _style_attr(_font_css(block.get("font"))),
        )
        label = block.get("label") or ""
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            raise CompileError(_("Invalid field label"))
        if label.strip():
            # Label + non-breaking space + value, on the same line.
            translations = _translations(
                block.get("label_translations"), MAX_LABEL, _("label")
            )
            value = '<span><span class="o_rs_label"%s>%s</span>&#160;%s</span>' % (
                _style_attr(_font_css(block.get("label_font"))),
                _by_lang(label, translations, escape),
                value,
            )
        # text-align does not apply to an inline element: with its own
        # alignment the field goes on a line of its own, aligned.
        align = _align_css(block.get("align"))
        if align:
            value = '<div style="%s">%s</div>' % (align, value)
        return [value]

    if btype == "table":
        return _render_table(block, model, var, ctx)

    if btype == "if":
        path = block.get("path")
        op = block.get("op")
        value = block.get("value")
        _check_path(path, model, ctx)
        if op not in OPERATORS:
            raise CompileError(_("Operator not allowed: %r"), op)
        expression = "%s.%s %s %s" % (var, path, op, _literal(value))
        children = _render_children(
            block.get("children", []), model, var, depth + 1, ctx, tree_path
        )
        if ctx.annotate:
            # In the editor the block stays selectable when the condition is false.
            label = ctx.gettext(_("If %(path)s %(op)s %(value)s")) % {
                "path": path,
                "op": op,
                "value": _literal(value),
            }
            hidden = ctx.gettext(_("Condition false for this record: content hidden"))
            return (
                ['<div class="o_rs_cv_if_label">%s</div>' % escape(label)]
                + ['<t t-if="%s">' % _attr(expression)]
                + children
                + [
                    "</t>",
                    '<t t-else=""><div class="o_rs_cv_if_false">%s</div></t>'
                    % escape(hidden),
                ]
            )
        return ['<t t-if="%s">' % _attr(expression)] + children + ["</t>"]

    raise CompileError(_("Unknown block type: %r"), btype)


def _color(value, what):
    """Validated #RRGGBB color, or "" when missing."""
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not COLOR_RE.match(value):
        raise CompileError(
            _("Invalid color for %(what)s: %(value)r"), {"what": what, "value": value}
        )
    return value


def _border_css(border):
    """CSS of the section borders: chosen sides, one style, width and color."""
    if border is None:
        return []
    if not isinstance(border, dict):
        raise CompileError(_("The border must be an object"))
    sides = border.get("sides") or []
    if not isinstance(sides, list) or set(sides) - set(MARGIN_SIDES):
        raise CompileError(_("Invalid border sides: %r"), sides)
    if not sides:
        return []
    style = border.get("style", "solid")
    if style not in BORDER_STYLES:
        raise CompileError(_("Border style not allowed: %r"), style)
    width = _number(border.get("width", 1), *BORDER_WIDTH, what=_("Border width (px)"))
    color = _color(border.get("color"), _("border")) or "#333333"
    return [
        "border-%s: %gpx %s %s" % (side, width, style, color)
        for side in MARGIN_SIDES
        if side in sides
    ]


def _section_title(title):
    """Label of the section: a full width bar on top, translatable."""
    if title is None:
        return []
    if not isinstance(title, dict):
        raise CompileError(_("The section label must be an object"))
    text = title.get("text") or ""
    if not isinstance(text, str) or len(text) > MAX_LABEL:
        raise CompileError(_("Invalid section label"))
    if not text.strip():
        return []
    translations = _translations(title.get("translations"), MAX_LABEL, _("label"))
    background = _color(title.get("background"), _("label background"))
    color = _color(title.get("color"), _("label text"))
    style = _style_attr(
        "background-color: %s" % background if background else "",
        "color: %s" % color if color else "",
        "padding: 1mm 2mm",
        _align_css(title.get("align")),
        _font_css(title.get("font")),
    )
    return [
        '<div class="o_rs_section_title"%s>%s</div>'
        % (style, _by_lang(text, translations, _text_html))
    ]


def _render_section(block, model, var, depth, ctx, tree_path):
    """Section: container with optional label bar, borders and margins.

    Without label and borders the output is a single div (as before); with
    them the outer div carries the borders and the label bar spans its full
    width, while the margins become the padding of an inner div.
    """
    children = _render_children(
        block.get("children", []), model, var, depth + 1, ctx, tree_path
    )
    children = children or _empty_placeholder(
        children, ctx, _("Empty section: select it and add blocks")
    )
    title = _section_title(block.get("title"))
    borders = _border_css(block.get("border"))
    margins = _margins_css(block.get("margins"))
    align = _align_css(block.get("align"))
    if not title and not borders:
        return (
            ["<div%s%s>" % (_css_attr(block.get("class")), _style_attr(margins, align))]
            + children
            + ["</div>"]
        )
    return (
        ["<div%s%s>" % (_css_attr(block.get("class")), _style_attr(*borders, align))]
        + title
        + ["<div%s>" % _style_attr(margins)]
        + children
        + ["</div>", "</div>"]
    )


def _check_keys(value, allowed, what):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise CompileError(_("Invalid %(what)s: %(value)r"), {"what": what, "value": value})
    return value


def _table_style(block):
    """Validated table style: header, data rows and borders.

    Returns a dict of ready CSS pieces; everything is optional and a table
    without style compiles as before.
    """
    style = _check_keys(block.get("style"), ("head", "rows", "borders"), _("table style"))
    head = _check_keys(
        style.get("head"), ("background", "color", "height"), _("header style")
    )
    rows = _check_keys(
        style.get("rows"),
        ("background", "alt_background", "height", "valign"),
        _("row style"),
    )
    borders = _check_keys(
        style.get("borders"), ("preset", "style", "width", "color"), _("table borders")
    )
    result = {
        "head_background": _color(head.get("background"), _("header background")),
        "head_color": _color(head.get("color"), _("header text")),
        "head_height": head.get("height")
        and _number(head["height"], *ROW_HEIGHT, what=_("Header height (mm)")),
        "rows_background": _color(rows.get("background"), _("row background")),
        "rows_alt_background": _color(
            rows.get("alt_background"), _("alternate row background")
        ),
        "rows_height": rows.get("height")
        and _number(rows["height"], *ROW_HEIGHT, what=_("Row height (mm)")),
        "valign": rows.get("valign") or "",
        "preset": borders.get("preset") or "",
    }
    if result["valign"] not in ("",) + VALIGNS:
        raise CompileError(_("Vertical alignment not allowed: %r"), result["valign"])
    if result["preset"] not in ("",) + BORDER_PRESETS:
        raise CompileError(_("Border scheme not allowed: %r"), result["preset"])
    line_style = borders.get("style", "solid")
    if line_style not in BORDER_STYLES:
        raise CompileError(_("Border style not allowed: %r"), line_style)
    width = _number(borders.get("width", 1), *BORDER_WIDTH, what=_("Border width (px)"))
    color = _color(borders.get("color"), _("border")) or "#333333"
    result["line"] = "%gpx %s %s" % (width, line_style, color)
    return result


def _cell_borders(style, header):
    """Border CSS of a cell for the chosen scheme ([] = Odoo default)."""
    line = style["line"]
    preset = style["preset"]
    if preset == "all":
        return ["border: %s" % line]
    if preset == "horizontal":
        return ["border: 0", "border-top: %s" % line, "border-bottom: %s" % line]
    if preset == "vertical":
        return ["border: 0", "border-left: %s" % line, "border-right: %s" % line]
    if preset == "header":
        return ["border: 0"] + (["border-bottom: %s" % line] if header else [])
    if preset in ("none", "outer"):
        return ["border: 0"]
    return []


def _column_extra(column, style):
    """Background and side borders of a single column."""
    background = _color(column.get("background"), _("column background"))
    sides = []
    for side in ("left", "right"):
        value = column.get("border_%s" % side, False)
        if not isinstance(value, bool):
            raise CompileError(_("The column border must be true or false"))
        if value:
            sides.append("border-%s: %s" % (side, style["line"]))
    return background, sides


def _render_table(block, model, var, ctx):
    source = block.get("source")
    ftype, comodel = _check_path(source, model, ctx)
    if ftype is not None and ftype not in TABLE_TYPES:
        raise CompileError(
            _("The table source %r must be a one2many or many2many field"), source
        )
    columns = block.get("columns")
    if not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS:
        raise CompileError(_("'columns' must be a non empty list"))
    line = ctx.new_var()
    head_css = _font_css(block.get("head_font"))
    body_css = _font_css(block.get("body_font"))
    style = _table_style(block)
    head_extra = [
        "background-color: %s" % style["head_background"]
        if style["head_background"]
        else "",
        "color: %s" % style["head_color"] if style["head_color"] else "",
        "height: %gmm" % style["head_height"] if style["head_height"] else "",
    ]
    rows_extra = [
        "height: %gmm" % style["rows_height"] if style["rows_height"] else "",
        "vertical-align: %s" % style["valign"] if style["valign"] else "",
    ]
    heads, cells, widths = [], [], []
    for column in columns:
        if not isinstance(column, dict):
            raise CompileError(_("Every column must be an object"))
        cpath = column.get("path")
        _check_path(cpath, comodel, ctx)
        label = column.get("label", cpath)
        width = _column_width(column)
        widths.append(width)
        # Cells get the explicit alignment (column, otherwise table): the CSS
        # of Odoo reports sets the one of the headers, which would not inherit
        # it from the table.
        align = _align_css(column.get("align") or block.get("align"))
        background, side_borders = _column_extra(column, style)
        translations = _translations(
            column.get("label_translations"), MAX_LABEL, _("header")
        )
        heads.append(
            "<th%s>%s</th>"
            % (
                _style_attr(
                    width,
                    align,
                    head_css,
                    *head_extra,
                    *_cell_borders(style, True),
                    *side_borders,
                ),
                _by_lang(str(label), translations, escape),
            )
        )
        cell_css = [
            align,
            body_css,
            *rows_extra,
            *_cell_borders(style, False),
            *side_borders,
        ]
        # Backgrounds: the column wins over the rows (base and alternate).
        if background:
            cell_css.append("background-color: %s" % background)
            style_attr = _style_attr(*cell_css)
        elif style["rows_alt_background"]:
            static = "; ".join(d for d in cell_css if d)
            dynamic = "background-color: {{ '%s' if %s_index %% 2 else '%s' }}" % (
                style["rows_alt_background"],
                line,
                style["rows_background"] or "transparent",
            )
            style_attr = ' t-attf-style="%s"' % _attr(
                "%s; %s" % (static, dynamic) if static else dynamic
            )
        else:
            if style["rows_background"]:
                cell_css.append("background-color: %s" % style["rows_background"])
            style_attr = _style_attr(*cell_css)
        cells.append('<td%s><span t-field="%s.%s"/></td>' % (style_attr, line, cpath))
    # With widths set, the table keeps them (fixed layout).
    bordered = style["preset"] or any(
        c.get("border_left") or c.get("border_right") for c in columns
    )
    table_style = _style_attr(
        "table-layout: fixed; width: 100%" if any(widths) else "",
        _align_css(block.get("align")),
        "border-collapse: collapse" if bordered else "",
        "border: %s" % style["line"] if style["preset"] == "outer" else "",
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
    # Margins: the table is wrapped in a container with padding.
    padding = _margins_css(block.get("margins"))
    if padding:
        table = ['<div style="%s">' % padding] + table + ["</div>"]
    return table


def _render_columns(block, model, var, depth, ctx, tree_path):
    """Columns block: borderless table, equal widths, optional vertical line."""
    columns = block.get("children")
    low, high = COLUMNS_RANGE
    if not isinstance(columns, list) or not low <= len(columns) <= high:
        raise CompileError(
            _("The Columns block must have %(low)d to %(high)d columns"),
            {"low": low, "high": high},
        )
    divider = block.get("divider", False)
    if not isinstance(divider, bool):
        raise CompileError(_("'divider' must be true or false"))
    width = 100.0 / len(columns)
    cells = []
    for index, column in enumerate(columns):
        if not isinstance(column, dict) or column.get("type") != "column":
            raise CompileError(_("The Columns block can only contain columns"))
        column_path = "%s.%d" % (tree_path, index) if tree_path else str(index)
        css = [
            "width: %.4g%%" % width,
            "vertical-align: top",
            _margins_css(column.get("margins")),
            _align_css(column.get("align")),
        ]
        if divider and index:
            css.append("border-left: 1px solid #333")
        marks = ""
        if ctx.annotate:
            # The column is selectable in the editor (container of blocks).
            marks = (
                ' class="o_rs_cv_block o_rs_cv_column" data-rs-path="%s" '
                'data-rs-type="column"' % column_path
            )
        children = _render_children(
            column.get("children", []), model, var, depth + 2, ctx, column_path
        )
        children = children or _empty_placeholder(children, ctx, _("Empty column"))
        cells.extend(
            ["<td%s%s>" % (marks, _style_attr(*css))] + children + ["</td>"]
        )
    return (
        [
            "<div%s>"
            % _style_attr(
                _margins_css(block.get("margins")), _align_css(block.get("align"))
            ),
            '<table style="width: 100%; table-layout: fixed; '
            'border-collapse: collapse"><tr>',
        ]
        + cells
        + ["</tr></table>", "</div>"]
    )


def _compile_qweb(definition, report_key):
    """Free QWeb mode: the template is used as it is, with its name changed.

    The template must already contain its own layout (e.g.
    web.external_layout), like the native documents copied into Report Studio.
    """
    arch = definition.get("arch")
    if not isinstance(arch, str) or not arch.strip():
        raise CompileError(_("The QWeb template is empty"))
    arch, count = re.subn(
        r't-name="[^"]*"', 't-name="%s"' % report_key, arch, count=1
    )
    if count == 0:
        arch = '<t t-name="%s">%s</t>' % (report_key, arch)
    return arch


def _print_lang(definition, model, ctx):
    """Contact field the print language is read from, or None."""
    options = definition.get("print_lang")
    if options is None:
        return None
    if not isinstance(options, dict) or not isinstance(
        options.get("enabled", False), bool
    ):
        raise CompileError(_("Invalid 'print in the customer language' option"))
    if not options.get("enabled"):
        return None
    path = options.get("field") or "partner_id"
    ftype, comodel = _check_path(path, model, ctx)
    if ftype is not None and (ftype != "many2one" or comodel != "res.partner"):
        raise CompileError(
            _("The field %r is not a contact (many2one to res.partner)"), path
        )
    return path


def _parse(definition, report_key):
    if not isinstance(report_key, str) or not REPORT_KEY_RE.match(report_key):
        raise CompileError(_("Invalid report key: %r"), report_key)
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except ValueError as exc:
            raise CompileError(_("Invalid JSON: %s"), str(exc)) from exc
    if not isinstance(definition, dict):
        raise CompileError(_("The definition must be a JSON object"))
    base_lang = definition.get("base_lang")
    if base_lang is not None and not (
        isinstance(base_lang, str) and LANG_RE.match(base_lang)
    ):
        raise CompileError(_("Invalid main language: %r"), base_lang)
    return definition


def compile_templates(
    definition, model, report_key, resolver=None, annotate=False, gettext=None
):
    """Compile a definition into the QWeb templates of the report.

    :param definition: dict or JSON string with the definition.
    :param model: technical name of the Odoo model (e.g. ``sale.order``).
    :param report_key: key of the main template (``t-name``), e.g.
        ``report_studio.rs_report_1_v1``; it is the one of the print action.
    :param resolver: callable ``(model, path) -> (type, comodel) | None``.
    :param annotate: mark the blocks for the visual view of the editor (never
        in saved PDFs). The visual view always uses a single template: the
        language is the one of the context (the language being edited).
    :param gettext: translates the editor placeholders (default: English).
    :returns: list of ``(key, xml)``; the first is the main template, the
        second (only when printing in the customer language) the page.
    """
    definition = _parse(definition, report_key)
    if definition.get("mode") == "qweb":
        return [(report_key, _compile_qweb(definition, report_key))]

    layout = definition.get("layout", "external")
    if layout not in LAYOUTS:
        raise CompileError(_("Layout not allowed: %r"), layout)

    ctx = _Context(resolver, annotate=annotate, gettext=gettext)
    lang_field = _print_lang(definition, model, ctx)
    body = _render_children(definition.get("children", []), model, "o", 0, ctx)
    page = (
        [
            '<t t-call="%s">' % LAYOUTS[layout],
            # Base alignment of the document: left.
            '<div class="page" style="text-align: left">',
        ]
        + body
        + ["</div>", "</t>"]
    )

    if lang_field is None or annotate:
        lines = (
            [
                '<t t-name="%s">' % report_key,
                '<t t-call="web.html_container">',
                '<t t-foreach="docs" t-as="o">',
                # Language of the translated texts: the print language.
                '<t t-set="rs_lang" t-value="lang"/>',
            ]
            + page
            + ["</t>", "</t>", "</t>"]
        )
        return [(report_key, "\n".join(lines))]

    # Customer language: the page is a separate template called with t-lang
    # (the content of a t-call would be rendered in the caller's language).
    document_key = "%s_document" % report_key
    main = "\n".join(
        [
            '<t t-name="%s">' % report_key,
            '<t t-call="web.html_container">',
            '<t t-foreach="docs" t-as="o">',
            '<t t-set="rs_lang" t-value="o.%s.lang or lang"/>' % lang_field,
            '<t t-call="%s" t-lang="rs_lang"/>' % document_key,
            "</t>",
            "</t>",
            "</t>",
        ]
    )
    document = "\n".join(['<t t-name="%s">' % document_key] + page + ["</t>"])
    return [(report_key, main), (document_key, document)]


def compile_definition(
    definition, model, report_key, resolver=None, annotate=False, gettext=None
):
    """All the templates of ``compile_templates`` joined, main one first.

    With printing in the customer language there are two templates: here they
    are returned one after the other (for tests and inspection), while Odoo
    gets one per view from ``compile_templates``.
    """
    return "\n".join(
        arch
        for _key, arch in compile_templates(
            definition,
            model,
            report_key,
            resolver=resolver,
            annotate=annotate,
            gettext=gettext,
        )
    )
