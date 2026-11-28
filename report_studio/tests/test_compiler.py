# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests of the pure compiler, runnable without Odoo:

    python3 report_studio/tests/test_compiler.py
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "rs_compiler", os.path.join(_HERE, "..", "lib", "compiler.py")
)
compiler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(compiler)

FIELDS = {
    "sale.order": {
        "name": ("char", None),
        "amount_total": ("monetary", None),
        "partner_id": ("many2one", "res.partner"),
        "order_line": ("one2many", "sale.order.line"),
    },
    "sale.order.line": {
        "name": ("text", None),
        "product_uom_qty": ("float", None),
    },
    "res.partner": {"name": ("char", None)},
}


def resolver(model, path):
    current = model
    ftype = comodel = None
    parts = path.split(".")
    for index, part in enumerate(parts):
        field = FIELDS.get(current, {}).get(part)
        if field is None:
            return None
        ftype, comodel = field
        if index < len(parts) - 1:
            if comodel is None:
                return None
            current = comodel
    return ftype, comodel


KEY = "report_studio.test_v1"


def compile_(children, layout=None):
    definition = {"children": children}
    if layout:
        definition["layout"] = layout
    return compiler.compile_definition(
        definition, "sale.order", "report_studio.test_v1", resolver=resolver
    )


class TestCompiler(unittest.TestCase):
    def test_template_wrapper(self):
        xml = compile_([])
        self.assertIn('t-name="report_studio.test_v1"', xml)
        self.assertIn('t-call="web.html_container"', xml)
        self.assertIn('t-foreach="docs" t-as="o"', xml)
        self.assertIn("web.external_layout", xml)  # default layout: the Odoo one

    def test_external_layout(self):
        self.assertIn("web.external_layout", compile_([], layout="external"))

    def test_text_is_escaped(self):
        xml = compile_([{"type": "text", "content": "<b>A & B</b>"}])
        self.assertIn("&lt;b&gt;A &amp; B&lt;/b&gt;", xml)
        self.assertNotIn("<b>A", xml)

    def test_field_uses_t_field(self):
        xml = compile_([{"type": "field", "path": "partner_id.name"}])
        self.assertIn('<span t-field="o.partner_id.name"/>', xml)

    def test_table_loops_over_x2many(self):
        xml = compile_([{
            "type": "table",
            "source": "order_line",
            "columns": [{"path": "name", "label": "Description"},
                        {"path": "product_uom_qty", "label": "Qty"}],
        }])
        self.assertIn('t-foreach="o.order_line"', xml)
        self.assertIn('t-field="line_1.name"', xml)
        self.assertIn("<th>Description</th>", xml)

    def test_if_block_with_literal(self):
        xml = compile_([{
            "type": "if", "path": "amount_total", "op": ">", "value": 0,
            "children": [{"type": "text", "content": "Positive total"}],
        }])
        self.assertIn('t-if="o.amount_total &gt; 0"', xml)

    def test_if_string_literal_is_repr_quoted(self):
        xml = compile_([{
            "type": "if", "path": "name", "op": "==", "value": "x'y",
            "children": [],
        }])
        self.assertIn("t-if=", xml)

    def test_empty_css_class_means_no_class(self):
        for empty in ("", "   "):
            xml = compile_([
                {"type": "text", "content": "x", "class": empty},
                {"type": "section", "class": empty, "children": []},
            ])
            self.assertIn("<p>x</p>", xml)
            self.assertNotIn('class=""', xml)

    def test_invalid_css_class_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "text", "content": "x", "class": '" onload="alert(1)'}])

    def test_invalid_path_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "__import__"}])
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "name; os.system"}])

    def test_unknown_field_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "missing_field"}])

    def test_table_on_many2one_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "table", "source": "partner_id",
                       "columns": [{"path": "name"}]}])

    def test_bad_operator_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "if", "path": "amount_total", "op": "and",
                       "value": 1, "children": []}])

    def test_unsupported_value_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "if", "path": "amount_total", "op": "==",
                       "value": {"x": 1}, "children": []}])

    def test_unknown_block_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "script"}])

    def test_bad_layout_and_key_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compile_([], layout="magic")
        with self.assertRaises(compiler.CompileError):
            compiler.compile_definition({"children": []}, "sale.order", "Bad Key!")

    def test_json_string_input(self):
        xml = compiler.compile_definition(
            '{"children": [{"type": "text", "content": "ok"}]}',
            "sale.order", "report_studio.test_v2",
        )
        self.assertIn("<p>ok</p>", xml)

    def test_depth_limit(self):
        block = {"type": "text", "content": "x"}
        for _ in range(12):
            block = {"type": "section", "children": [block]}
        with self.assertRaises(compiler.CompileError):
            compile_([block])

    def test_qweb_mode_rekeys_template(self):
        arch = '<t t-name="sale.report_saleorder"><t t-call="web.html_container"/></t>'
        xml = compiler.compile_definition(
            {"mode": "qweb", "arch": arch}, "sale.order", "report_studio.test_q1",
        )
        self.assertIn('t-name="report_studio.test_q1"', xml)
        self.assertNotIn("sale.report_saleorder", xml)

    def test_qweb_mode_wraps_fragment(self):
        xml = compiler.compile_definition(
            {"mode": "qweb", "arch": "<div>x</div>"}, "sale.order", "report_studio.test_q2",
        )
        self.assertIn('<t t-name="report_studio.test_q2"><div>x</div></t>', xml)

    def test_qweb_empty_rejected(self):
        with self.assertRaises(compiler.CompileError):
            compiler.compile_definition({"mode": "qweb", "arch": " "}, "sale.order", "report_studio.test_q3")


    # ----- visual view of the editor (annotate=True) -----

    def _annotated(self, children):
        return compiler.compile_definition(
            {"children": children}, "sale.order", KEY, resolver=resolver, annotate=True
        )

    def test_annotate_marks_blocks_with_tree_path(self):
        arch = self._annotated([
            {"type": "text", "content": "Hello"},
            {"type": "section", "children": [{"type": "field", "path": "name"}]},
        ])
        self.assertIn('data-rs-path="0" data-rs-type="text"', arch)
        self.assertIn('data-rs-path="1" data-rs-type="section"', arch)
        self.assertIn('<span class="o_rs_cv_block o_rs_cv_field" data-rs-path="1.0"', arch)
        etree_ok(arch)

    def test_annotate_invalid_block_is_placeholder(self):
        arch = self._annotated([
            {"type": "field", "path": ""},
            {"type": "field", "path": "field_<missing>"},
            {"type": "text", "content": "ok"},
        ])
        self.assertIn('o_rs_cv_invalid', arch)
        self.assertNotIn("<missing>", arch)  # escaped message
        self.assertIn('data-rs-path="2" data-rs-type="text"', arch)
        etree_ok(arch)

    def test_annotate_condition_always_visible(self):
        arch = self._annotated([{"type": "if", "path": "amount_total", "op": ">", "value": 0,
                                 "children": [{"type": "text", "content": "x"}]}])
        self.assertIn('data-rs-path="0.0"', arch)
        self.assertIn('t-else=""', arch)
        self.assertIn("If amount_total &gt; 0", arch)
        etree_ok(arch)

    def test_saved_templates_are_not_annotated(self):
        arch = compiler.compile_definition(
            {"children": [{"type": "text", "content": "Hello"}]}, "sale.order", KEY, resolver=resolver
        )
        self.assertNotIn("data-rs-path", arch)
        with self.assertRaises(compiler.CompileError):
            compiler.compile_definition(
                {"children": [{"type": "field", "path": ""}]}, "sale.order", KEY, resolver=resolver
            )


    # ----- font, field label, column widths -----

    def test_text_font(self):
        xml = compile_([{"type": "text", "content": "Hello",
                         "font": {"size": 14, "bold": True, "italic": True, "underline": True}}])
        self.assertIn('<p style="font-size: 14pt; font-weight: bold; font-style: italic; '
                      'text-decoration: underline">Hello</p>', xml)

    def test_empty_font_adds_no_style(self):
        xml = compile_([{"type": "text", "content": "Hello", "font": {"size": None, "bold": False}}])
        self.assertIn("<p>Hello</p>", xml)

    def test_invalid_font_rejected(self):
        for font in ({"size": 200}, {"size": "12"}, {"bold": "yes"}, {"color": "red"}, "bold"):
            with self.assertRaises(compiler.CompileError, msg=font):
                compile_([{"type": "text", "content": "x", "font": font}])

    def test_field_label_and_fonts(self):
        xml = compile_([{"type": "field", "path": "name", "label": "Delivery <no>:",
                         "label_font": {"bold": True}, "font": {"size": 10}}])
        self.assertIn('<span class="o_rs_label" style="font-weight: bold">Delivery &lt;no&gt;:</span>&#160;'
                      '<span t-field="o.name" style="font-size: 10pt"/>', xml)

    def test_field_without_label_unchanged(self):
        xml = compile_([{"type": "field", "path": "name", "label": "  "}])
        self.assertIn('<span t-field="o.name"/>', xml)
        self.assertNotIn("o_rs_label", xml)

    def test_table_fonts_and_widths(self):
        xml = compile_([{
            "type": "table", "source": "order_line",
            "head_font": {"bold": True}, "body_font": {"size": 9},
            "columns": [{"path": "name", "label": "Description", "width": 70, "locked": True},
                        {"path": "product_uom_qty", "label": "Qty", "width": 30}],
        }])
        self.assertIn('<table class="table table-sm" style="table-layout: fixed; width: 100%">', xml)
        self.assertIn('<th style="width: 70%; font-weight: bold">Description</th>', xml)
        self.assertIn('<td style="font-size: 9pt"><span t-field="line_1.product_uom_qty"/></td>', xml)

    def test_table_without_widths_unchanged(self):
        xml = compile_([{"type": "table", "source": "order_line",
                         "columns": [{"path": "name", "label": "Description"}]}])
        self.assertIn('<table class="table table-sm">', xml)
        self.assertIn("<th>Description</th>", xml)

    def test_invalid_width_rejected(self):
        for width in (0, 120, "50", True):
            with self.assertRaises(compiler.CompileError, msg=width):
                compile_([{"type": "table", "source": "order_line",
                           "columns": [{"path": "name", "width": width}]}])


    # ----- separator, spacer, page break, columns, margins -----

    def _cols(self, n, **extra):
        return dict({"type": "columns", "children": [
            {"type": "column", "children": [{"type": "text", "content": "C%d" % i}]} for i in range(n)
        ]}, **extra)

    def test_separator_spacer_page_break(self):
        xml = compile_([
            {"type": "separator", "style": "dashed", "thickness": 2},
            {"type": "spacer", "height": 15},
            {"type": "page_break"},
        ])
        self.assertIn("border-top: 2px dashed #333", xml)
        self.assertIn('<div style="height: 15mm"></div>', xml)
        self.assertIn("page-break-after: always", xml)
        self.assertNotIn("Page break", xml)  # label only in the editor

    def test_separator_and_spacer_validation(self):
        for block in ({"type": "separator", "style": "double"}, {"type": "separator", "thickness": 9},
                      {"type": "spacer", "height": 0}, {"type": "spacer", "height": "10"}):
            with self.assertRaises(compiler.CompileError, msg=block):
                compile_([block])

    def test_columns_table_with_divider_and_margins(self):
        block = self._cols(3, divider=True, margins={"top": 5})
        block["children"][1]["margins"] = {"left": 3, "right": 3}
        xml = compile_([block])
        self.assertIn('<div style="padding: 5mm 0mm 0mm 0mm">', xml)
        self.assertEqual(xml.count("<td "), 3)
        self.assertIn("width: 33.33%; vertical-align: top; padding: 0mm 3mm 0mm 3mm; border-left: 1px solid #333", xml)
        self.assertNotIn("width: 33.33%; vertical-align: top; border-left", xml.split("<td")[1])  # first column without line
        self.assertIn("C2", xml)

    def test_columns_count_and_content_validated(self):
        for block in (self._cols(1), self._cols(5), self._cols(2, divider="yes"),
                      {"type": "columns", "children": [{"type": "text", "content": "x"}] * 2},
                      {"type": "column", "children": []}):
            with self.assertRaises(compiler.CompileError, msg=block):
                compile_([block])

    def test_section_margins(self):
        xml = compile_([{"type": "section", "margins": {"left": 10, "top": 0}, "children": []}])
        self.assertIn('<div style="padding: 0mm 0mm 0mm 10mm">', xml)
        self.assertIn("<div>", compile_([{"type": "section", "margins": {"left": 0}, "children": []}]))
        for margins in ({"left": -1}, {"left": 500}, {"middle": 1}, "5"):
            with self.assertRaises(compiler.CompileError, msg=margins):
                compile_([{"type": "section", "margins": margins, "children": []}])

    def test_annotate_columns_are_selectable(self):
        arch = self._annotated([{"type": "section", "children": [self._cols(2)]}])
        self.assertIn('data-rs-path="0.0" data-rs-type="columns"', arch)
        self.assertIn('class="o_rs_cv_block o_rs_cv_column" data-rs-path="0.0.1" data-rs-type="column"', arch)
        self.assertIn('data-rs-path="0.0.1.0" data-rs-type="text"', arch)
        etree_ok(arch)

    def test_annotate_page_break_label(self):
        arch = self._annotated([{"type": "page_break"}])
        self.assertIn("Page break", arch)


    # ----- text alignment -----

    def test_document_is_left_aligned(self):
        self.assertIn('<div class="page" style="text-align: left">', compile_([]))

    def test_align_on_text_section_columns(self):
        cols = self._cols(2, align="right")
        cols["children"][0]["align"] = "justify"
        xml = compile_([{"type": "section", "align": "left", "children": [
            {"type": "text", "content": "Title", "align": "center", "font": {"bold": True}},
            {"type": "text", "content": "Normal"},
            cols,
        ]}])
        self.assertIn('<div style="text-align: left">', xml)
        self.assertIn('<p style="text-align: center; font-weight: bold">Title</p>', xml)
        self.assertIn("<p>Normal</p>", xml)  # inherited from the section
        self.assertIn('<div style="text-align: right">', xml)
        self.assertIn("vertical-align: top; text-align: justify", xml)

    def test_table_and_column_align(self):
        xml = compile_([{"type": "table", "source": "order_line", "align": "center", "columns": [
            {"path": "name", "label": "Description", "align": "left"},
            {"path": "product_uom_qty", "label": "Qty"},
        ]}])
        self.assertIn('<table class="table table-sm" style="text-align: center">', xml)
        self.assertIn('<th style="text-align: left">Description</th>', xml)
        self.assertIn('<td style="text-align: left"><span t-field="line_1.name"/></td>', xml)
        self.assertIn('<th style="text-align: center">Qty</th>', xml)  # as the table

    def test_text_line_breaks(self):
        xml = compile_([{"type": "text", "content": "Line 1\nLine <2>\r\nLine 3"}])
        self.assertIn("<p>Line 1<br/>Line &lt;2&gt;<br/>Line 3</p>", xml)
        self.assertIn("<p>One line</p>", compile_([{"type": "text", "content": "One line"}]))

    def test_table_margins(self):
        table = {"type": "table", "source": "order_line", "columns": [{"path": "name"}]}
        self.assertNotIn("padding", compile_([dict(table, margins={"top": 0})]))
        xml = compile_([dict(table, margins={"top": 2, "left": 5})])
        self.assertIn('<div style="padding: 2mm 0mm 0mm 5mm">\n<table class="table table-sm">', xml)
        with self.assertRaises(compiler.CompileError):
            compile_([dict(table, margins={"top": 500})])

    # ----- section label and borders -----

    def test_section_without_label_and_borders_unchanged(self):
        xml = compile_([{"type": "section", "margins": {"left": 10}, "title": {"text": " "},
                         "border": {"sides": []}, "children": []}])
        self.assertIn('<div style="padding: 0mm 0mm 0mm 10mm">\n</div>', xml)

    def test_section_label_bar(self):
        xml = compile_([{"type": "section", "margins": {"left": 5}, "align": "right", "children": [
            {"type": "text", "content": "x"}],
            "title": {"text": "Customer", "translations": {"it_IT": "Cliente"},
                      "background": "#E9ECEF", "color": "#000000",
                      "font": {"bold": True}, "align": "center"}}])
        self.assertIn('<div style="text-align: right">\n<div class="o_rs_section_title" '
                      'style="background-color: #E9ECEF; color: #000000; padding: 1mm 2mm; '
                      'text-align: center; font-weight: bold">'
                      "<t t-if=\"rs_lang == 'it_IT'\">Cliente</t><t t-else=\"\">Customer</t></div>\n"
                      '<div style="padding: 0mm 0mm 0mm 5mm">\n<p>x</p>\n</div>\n</div>', xml)

    def test_section_borders(self):
        xml = compile_([{"type": "section", "children": [],
                         "border": {"sides": ["top", "bottom"], "style": "double", "width": 3}}])
        self.assertIn('<div style="border-top: 3px double #333333; border-bottom: 3px double #333333">', xml)
        xml = compile_([{"type": "section", "children": [],
                         "border": {"sides": ["left", "top", "right", "bottom"], "color": "#ff0000"}}])
        self.assertIn("border-top: 1px solid #ff0000; border-right: 1px solid #ff0000; "
                      "border-bottom: 1px solid #ff0000; border-left: 1px solid #ff0000", xml)

    def test_section_label_and_borders_validated(self):
        for extra in ({"title": {"text": "x", "background": "red"}},
                      {"title": {"text": "x", "color": "#12345"}},
                      {"title": "x"},
                      {"border": {"sides": ["middle"]}},
                      {"border": {"sides": ["top"], "style": "groove"}},
                      {"border": {"sides": ["top"], "width": 9}},
                      {"border": {"sides": ["top"], "color": "#zzzzzz"}}):
            with self.assertRaises(compiler.CompileError, msg=extra):
                compile_([dict({"type": "section", "children": []}, **extra)])

    def test_section_label_selectable_in_editor(self):
        arch = self._annotated([{"type": "section", "children": [],
                                 "title": {"text": "Customer"}, "border": {"sides": ["top"]}}])
        self.assertIn('data-rs-path="0" data-rs-type="section"', arch)
        self.assertIn('<div class="o_rs_section_title" style="padding: 1mm 2mm">Customer</div>', arch)
        etree_ok(arch)

    # ----- section: source, size, position in the page -----

    def test_section_source_and_use_document(self):
        xml = compile_([{"type": "section", "source": "partner_id", "children": [
            {"type": "field", "path": "name"},
            {"type": "field", "path": "amount_total", "use_document": True}]}])
        self.assertIn('<t t-set="section_1" t-value="o.partner_id"/>', xml)
        self.assertIn('<span t-field="section_1.name"/>', xml)
        self.assertIn('<span t-field="o.amount_total"/>', xml)
        # the fields inside are checked on the source model
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "section", "source": "partner_id",
                       "children": [{"type": "field", "path": "amount_total"}]}])
        for source in ("order_line", "name", "missing"):
            with self.assertRaises(compiler.CompileError, msg=source):
                compile_([{"type": "section", "source": source, "children": []}])
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "name", "use_document": "yes"}])

    def test_section_width_and_position(self):
        xml = compile_([{"type": "section", "width": {"mode": "percent", "value": 50},
                         "halign": "right", "children": []}])
        self.assertIn('<div style="width: 50%; box-sizing: border-box; margin-left: auto">', xml)
        xml = compile_([{"type": "section", "width": {"mode": "mm", "value": 80},
                         "halign": "center", "children": []}])
        self.assertIn("width: 80mm; box-sizing: border-box; margin-left: auto; margin-right: auto", xml)
        self.assertNotIn("width:", compile_([{"type": "section", "width": {"mode": "full"}, "children": []}]))
        for width in ({"mode": "percent", "value": 150}, {"mode": "cm", "value": 3}, {"mode": "mm"}):
            with self.assertRaises(compiler.CompileError, msg=width):
                compile_([{"type": "section", "width": width, "children": []}])

    def test_section_height_and_vertical_alignment(self):
        xml = compile_([{"type": "section", "height": 40, "valign": "middle", "margins": {"left": 2},
                         "title": {"text": "Shipping"}, "children": [{"type": "text", "content": "x"}]}])
        self.assertIn('<div style="display: table; width: 100%; height: 40mm; border-collapse: collapse">', xml)
        self.assertIn('<div style="display: table-cell; vertical-align: middle; padding: 0mm 0mm 0mm 2mm">', xml)
        self.assertIn('<div class="o_rs_section_title"', xml)
        etree_ok(xml)

    def test_section_repeated_on_every_page(self):
        xml = compile_([{"type": "section", "position": "footer", "height": 30, "class": "small",
                         "children": [{"type": "field", "path": "name"}]}])
        self.assertIn('class="small o_rs_page_footer"', xml)
        self.assertIn('data-rs-height="30"', xml)
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "section", "position": "header", "children": []}])  # no height
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "section", "position": "aside", "height": 10, "children": []}])
        arch = self._annotated([{"type": "section", "position": "header", "height": 25, "children": []}])
        self.assertIn('<div class="o_rs_cv_repeat">Repeated at the top of every page (25 mm)</div>', arch)

    # ----- table style -----

    def _table(self, **extra):
        return dict({"type": "table", "source": "order_line", "columns": [
            {"path": "name", "label": "Description"},
            {"path": "product_uom_qty", "label": "Qty"}]}, **extra)

    def test_table_header_and_rows_style(self):
        xml = compile_([self._table(style={
            "head": {"background": "#000080", "color": "#ffffff", "height": 8},
            "rows": {"background": "#ffffff", "height": 6, "valign": "middle"}})])
        self.assertIn('<th style="background-color: #000080; color: #ffffff; height: 8mm">Description</th>', xml)
        self.assertIn('<td style="height: 6mm; vertical-align: middle; background-color: #ffffff">'
                      '<span t-field="line_1.name"/></td>', xml)

    def test_table_alternate_rows_and_column_wins(self):
        table = self._table(style={"rows": {"alt_background": "#eeeeee"}})
        table["columns"][1]["background"] = "#ffff00"
        xml = compile_([table])
        # alternate rows: dynamic style on the first column
        self.assertIn('<td t-attf-style="background-color: {{ \'#eeeeee\' if line_1_index % 2 '
                      'else \'transparent\' }}"><span t-field="line_1.name"/></td>', xml)
        # the column background wins
        self.assertIn('<td style="background-color: #ffff00"><span t-field="line_1.product_uom_qty"/></td>', xml)
        etree_ok(xml)

    def test_table_border_presets(self):
        line = "1px solid #333333"
        cases = {
            "all": ('<th style="border: %s">' % line, '<td style="border: %s">' % line),
            "horizontal": ('<th style="border: 0; border-top: %s; border-bottom: %s">' % (line, line), None),
            "vertical": ('<th style="border: 0; border-left: %s; border-right: %s">' % (line, line), None),
            "header": ('<th style="border: 0; border-bottom: %s">' % line, '<td style="border: 0">'),
            "none": ('<th style="border: 0">', '<td style="border: 0">'),
        }
        for preset, (head, cell) in cases.items():
            xml = compile_([self._table(style={"borders": {"preset": preset}})])
            self.assertIn(head, xml, preset)
            if cell:
                self.assertIn(cell, xml, preset)
            self.assertIn("border-collapse: collapse", xml)
        xml = compile_([self._table(style={"borders": {"preset": "outer", "style": "double",
                                                       "width": 3, "color": "#ff0000"}})])
        self.assertIn('<table class="table table-sm" style="border-collapse: collapse; '
                      'border: 3px double #ff0000">', xml)

    def test_table_column_borders(self):
        table = self._table(style={"borders": {"width": 2}})
        table["columns"][0]["border_right"] = True
        xml = compile_([table])
        self.assertIn('<th style="border-right: 2px solid #333333">Description</th>', xml)
        self.assertIn('<td style="border-right: 2px solid #333333">', xml)
        self.assertIn('style="border-collapse: collapse"', xml)

    def test_table_style_validated(self):
        for style in ({"head": {"background": "blue"}}, {"rows": {"valign": "baseline"}},
                      {"rows": {"height": 500}}, {"head": {"height": -1}}, {"borders": {"preset": "diagonal"}},
                      {"borders": {"style": "groove"}}, {"other": 1}, "x"):
            with self.assertRaises(compiler.CompileError, msg=style):
                compile_([self._table(style=style)])
        table = self._table()
        table["columns"][0]["border_left"] = "yes"
        with self.assertRaises(compiler.CompileError):
            compile_([table])

    # ----- languages -----

    def test_translations_choose_text_by_lang(self):
        xml = compile_([
            {"type": "text", "content": "Hello\nWorld", "translations": {"it_IT": "Ciao\nMondo", "fr_FR": ""}},
            {"type": "field", "path": "name", "label": "Order", "label_translations": {"it_IT": "Ordine"}},
            {"type": "table", "source": "order_line", "columns": [
                {"path": "name", "label": "Qty", "label_translations": {"de_DE": "Menge", "it_IT": "Qty"}}]},
        ])
        self.assertIn('<t t-set="rs_lang" t-value="lang"/>', xml)
        self.assertIn("<p><t t-if=\"rs_lang == 'it_IT'\">Ciao<br/>Mondo</t>"
                      "<t t-else=\"\">Hello<br/>World</t></p>", xml)
        self.assertNotIn("fr_FR", xml)  # empty translation: base text
        self.assertIn("<t t-if=\"rs_lang == 'it_IT'\">Ordine</t><t t-else=\"\">Order</t>", xml)
        self.assertIn("<t t-if=\"rs_lang == 'de_DE'\">Menge</t><t t-elif=\"rs_lang == 'it_IT'\">Qty</t>"
                      "<t t-else=\"\">Qty</t>", xml)

    def test_translations_validated(self):
        for block in ({"type": "text", "content": "x", "translations": {"it' or 1": "y"}},
                      {"type": "text", "content": "x", "translations": {"it_IT": 3}},
                      {"type": "text", "content": "x", "translations": ["it_IT"]},
                      {"type": "field", "path": "name", "label": "x", "label_translations": {"it_IT": "y" * 500}}):
            with self.assertRaises(compiler.CompileError, msg=block):
                compile_([block])
        with self.assertRaises(compiler.CompileError):
            compiler.compile_definition({"base_lang": "x'y", "children": []}, "sale.order", KEY, resolver=resolver)

    def test_print_lang_uses_document_template(self):
        definition = {"print_lang": {"enabled": True, "field": "partner_id"},
                      "children": [{"type": "field", "path": "name"}]}
        templates = compiler.compile_templates(definition, "sale.order", KEY, resolver=resolver)
        self.assertEqual([k for k, _a in templates], [KEY, KEY + "_document"])
        main, document = templates[0][1], templates[1][1]
        self.assertIn('<t t-set="rs_lang" t-value="o.partner_id.lang or lang"/>', main)
        self.assertIn('<t t-call="%s_document" t-lang="rs_lang"/>' % KEY, main)
        self.assertIn('<t t-name="%s_document">' % KEY, document)
        self.assertIn('<span t-field="o.name"/>', document)
        self.assertNotIn("t-field", main)
        # disabled, or editor view: a single template
        off = dict(definition, print_lang={"enabled": False})
        self.assertEqual(len(compiler.compile_templates(off, "sale.order", KEY, resolver=resolver)), 1)
        self.assertEqual(len(compiler.compile_templates(definition, "sale.order", KEY,
                                                        resolver=resolver, annotate=True)), 1)

    def test_print_lang_field_must_be_partner(self):
        for field in ("name", "order_line", "missing", "partner_id.name"):
            with self.assertRaises(compiler.CompileError, msg=field):
                compiler.compile_templates({"print_lang": {"enabled": True, "field": field}, "children": []},
                                           "sale.order", KEY, resolver=resolver)

    def test_field_align(self):
        # Without alignment the field stays inline, as before.
        self.assertIn('<span t-field="o.name"/>', compile_([{"type": "field", "path": "name"}]))
        xml = compile_([
            {"type": "field", "path": "name", "align": "right"},
            {"type": "field", "path": "name", "label": "Order no.", "align": "center"},
        ])
        self.assertIn('<div style="text-align: right"><span t-field="o.name"/></div>', xml)
        self.assertIn('<div style="text-align: center"><span><span class="o_rs_label">Order no.</span>', xml)
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "name", "align": "middle"}])
        canvas = self._annotated([{"type": "field", "path": "name", "align": "right"},
                               {"type": "field", "path": "name"}])
        self.assertIn('<div class="o_rs_cv_block o_rs_cv_field" data-rs-path="0"', canvas)
        self.assertIn('<span class="o_rs_cv_block o_rs_cv_field" data-rs-path="1"', canvas)

    # ----- translation of messages -----

    def test_messages_are_marked_and_translatable(self):
        italian = {
            "Invalid field path: %r": "Percorso di campo non valido: %r",
            "Empty column": "Colonna vuota",
            "%(what)s is not valid: %(value)r (%(low)g to %(high)g)":
                "%(what)s non valido: %(value)r (da %(low)g a %(high)g)",
            "Spacer height (mm)": "Altezza dello spaziatore (mm)",
        }
        gettext = lambda text: italian.get(text, text)  # noqa: E731
        with self.assertRaises(compiler.CompileError) as error:
            compile_([{"type": "field", "path": "a b"}])
        self.assertEqual(str(error.exception), "Invalid field path: 'a b'")
        self.assertEqual(error.exception.translate(gettext), "Percorso di campo non valido: 'a b'")
        with self.assertRaises(compiler.CompileError) as error:
            compile_([{"type": "spacer", "height": 0}])
        self.assertEqual(error.exception.translate(gettext),
                         "Altezza dello spaziatore (mm) non valido: 0 (da 1 a 200)")
        arch = compiler.compile_definition(
            {"children": [self._cols(2)]}, "sale.order", KEY, resolver=resolver, annotate=True,
            gettext=gettext)
        self.assertNotIn("Colonna vuota", arch)  # columns are not empty
        arch = compiler.compile_definition(
            {"children": [{"type": "columns", "children": [{"type": "column", "children": []}] * 2}]},
            "sale.order", KEY, resolver=resolver, annotate=True, gettext=gettext)
        self.assertIn("Colonna vuota", arch)

    def test_invalid_align_rejected(self):
        for block in ({"type": "text", "content": "x", "align": "middle"},
                      {"type": "section", "align": 1, "children": []},
                      {"type": "table", "source": "order_line",
                       "columns": [{"path": "name", "align": "top"}]}):
            with self.assertRaises(compiler.CompileError, msg=block):
                compile_([block])


def etree_ok(arch):
    """The annotated template is well formed XML."""
    import xml.dom.minidom
    xml.dom.minidom.parseString(arch)


if __name__ == "__main__":
    unittest.main()
