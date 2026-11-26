# -*- coding: utf-8 -*-
"""Test del compilatore puro, eseguibili senza Odoo:

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
        self.assertIn("web.external_layout", xml)  # layout predefinito: quello di Odoo

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
            "columns": [{"path": "name", "label": "Descrizione"},
                        {"path": "product_uom_qty", "label": "Q.tà"}],
        }])
        self.assertIn('t-foreach="o.order_line"', xml)
        self.assertIn('t-field="line_1.name"', xml)
        self.assertIn("<th>Descrizione</th>", xml)

    def test_if_block_with_literal(self):
        xml = compile_([{
            "type": "if", "path": "amount_total", "op": ">", "value": 0,
            "children": [{"type": "text", "content": "Totale positivo"}],
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
            compile_([{"type": "field", "path": "campo_inesistente"}])

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


    # ----- vista visuale dell'editor (annotate=True) -----

    def _annotated(self, children):
        return compiler.compile_definition(
            {"children": children}, "sale.order", KEY, resolver=resolver, annotate=True
        )

    def test_annotate_marks_blocks_with_tree_path(self):
        arch = self._annotated([
            {"type": "text", "content": "Ciao"},
            {"type": "section", "children": [{"type": "field", "path": "name"}]},
        ])
        self.assertIn('data-rs-path="0" data-rs-type="text"', arch)
        self.assertIn('data-rs-path="1" data-rs-type="section"', arch)
        self.assertIn('<span class="o_rs_cv_block o_rs_cv_field" data-rs-path="1.0"', arch)
        etree_ok(arch)

    def test_annotate_invalid_block_is_placeholder(self):
        arch = self._annotated([
            {"type": "field", "path": ""},
            {"type": "field", "path": "campo_<inesistente>"},
            {"type": "text", "content": "ok"},
        ])
        self.assertIn('o_rs_cv_invalid', arch)
        self.assertNotIn("<inesistente>", arch)  # messaggio escapato
        self.assertIn('data-rs-path="2" data-rs-type="text"', arch)
        etree_ok(arch)

    def test_annotate_condition_always_visible(self):
        arch = self._annotated([{"type": "if", "path": "amount_total", "op": ">", "value": 0,
                                 "children": [{"type": "text", "content": "x"}]}])
        self.assertIn('data-rs-path="0.0"', arch)
        self.assertIn('t-else=""', arch)
        self.assertIn("Se amount_total &gt; 0", arch)
        etree_ok(arch)

    def test_saved_templates_are_not_annotated(self):
        arch = compiler.compile_definition(
            {"children": [{"type": "text", "content": "Ciao"}]}, "sale.order", KEY, resolver=resolver
        )
        self.assertNotIn("data-rs-path", arch)
        with self.assertRaises(compiler.CompileError):
            compiler.compile_definition(
                {"children": [{"type": "field", "path": ""}]}, "sale.order", KEY, resolver=resolver
            )


    # ----- carattere, etichetta del campo, larghezza colonne -----

    def test_text_font(self):
        xml = compile_([{"type": "text", "content": "Ciao",
                         "font": {"size": 14, "bold": True, "italic": True, "underline": True}}])
        self.assertIn('<p style="font-size: 14pt; font-weight: bold; font-style: italic; '
                      'text-decoration: underline">Ciao</p>', xml)

    def test_empty_font_adds_no_style(self):
        xml = compile_([{"type": "text", "content": "Ciao", "font": {"size": None, "bold": False}}])
        self.assertIn("<p>Ciao</p>", xml)

    def test_invalid_font_rejected(self):
        for font in ({"size": 200}, {"size": "12"}, {"bold": "si"}, {"color": "red"}, "grassetto"):
            with self.assertRaises(compiler.CompileError, msg=font):
                compile_([{"type": "text", "content": "x", "font": font}])

    def test_field_label_and_fonts(self):
        xml = compile_([{"type": "field", "path": "name", "label": "DDT <num>:",
                         "label_font": {"bold": True}, "font": {"size": 10}}])
        self.assertIn('<span class="o_rs_label" style="font-weight: bold">DDT &lt;num&gt;:</span>&#160;'
                      '<span t-field="o.name" style="font-size: 10pt"/>', xml)

    def test_field_without_label_unchanged(self):
        xml = compile_([{"type": "field", "path": "name", "label": "  "}])
        self.assertIn('<span t-field="o.name"/>', xml)
        self.assertNotIn("o_rs_label", xml)

    def test_table_fonts_and_widths(self):
        xml = compile_([{
            "type": "table", "source": "order_line",
            "head_font": {"bold": True}, "body_font": {"size": 9},
            "columns": [{"path": "name", "label": "Descrizione", "width": 70, "locked": True},
                        {"path": "product_uom_qty", "label": "Qtà", "width": 30}],
        }])
        self.assertIn('<table class="table table-sm" style="table-layout: fixed; width: 100%">', xml)
        self.assertIn('<th style="width: 70%; font-weight: bold">Descrizione</th>', xml)
        self.assertIn('<td style="font-size: 9pt"><span t-field="line_1.product_uom_qty"/></td>', xml)

    def test_table_without_widths_unchanged(self):
        xml = compile_([{"type": "table", "source": "order_line",
                         "columns": [{"path": "name", "label": "Descrizione"}]}])
        self.assertIn('<table class="table table-sm">', xml)
        self.assertIn("<th>Descrizione</th>", xml)

    def test_invalid_width_rejected(self):
        for width in (0, 120, "50", True):
            with self.assertRaises(compiler.CompileError, msg=width):
                compile_([{"type": "table", "source": "order_line",
                           "columns": [{"path": "name", "width": width}]}])


    # ----- separatore, spaziatore, interruzione, colonne, margini -----

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
        self.assertNotIn("Interruzione di pagina", xml)  # etichetta solo nell'editor

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
        self.assertNotIn("width: 33.33%; vertical-align: top; border-left", xml.split("<td")[1])  # prima colonna senza riga
        self.assertIn("C2", xml)

    def test_columns_count_and_content_validated(self):
        for block in (self._cols(1), self._cols(5), self._cols(2, divider="si"),
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
        self.assertIn("Interruzione di pagina", arch)


    # ----- allineamento del testo -----

    def test_document_is_left_aligned(self):
        self.assertIn('<div class="page" style="text-align: left">', compile_([]))

    def test_align_on_text_section_columns(self):
        cols = self._cols(2, align="right")
        cols["children"][0]["align"] = "justify"
        xml = compile_([{"type": "section", "align": "left", "children": [
            {"type": "text", "content": "Titolo", "align": "center", "font": {"bold": True}},
            {"type": "text", "content": "Normale"},
            cols,
        ]}])
        self.assertIn('<div style="text-align: left">', xml)
        self.assertIn('<p style="text-align: center; font-weight: bold">Titolo</p>', xml)
        self.assertIn("<p>Normale</p>", xml)  # eredita dalla sezione
        self.assertIn('<div style="text-align: right">', xml)
        self.assertIn("vertical-align: top; text-align: justify", xml)

    def test_table_and_column_align(self):
        xml = compile_([{"type": "table", "source": "order_line", "align": "center", "columns": [
            {"path": "name", "label": "Descrizione", "align": "left"},
            {"path": "product_uom_qty", "label": "Qtà"},
        ]}])
        self.assertIn('<table class="table table-sm" style="text-align: center">', xml)
        self.assertIn('<th style="text-align: left">Descrizione</th>', xml)
        self.assertIn('<td style="text-align: left"><span t-field="line_1.name"/></td>', xml)
        self.assertIn('<th style="text-align: center">Qtà</th>', xml)  # come la tabella

    def test_text_line_breaks(self):
        xml = compile_([{"type": "text", "content": "Riga 1\nRiga <2>\r\nRiga 3"}])
        self.assertIn("<p>Riga 1<br/>Riga &lt;2&gt;<br/>Riga 3</p>", xml)
        self.assertIn("<p>Una riga</p>", compile_([{"type": "text", "content": "Una riga"}]))

    def test_field_align(self):
        # Senza allineamento il campo resta in linea, come prima.
        self.assertIn('<span t-field="o.name"/>', compile_([{"type": "field", "path": "name"}]))
        xml = compile_([
            {"type": "field", "path": "name", "align": "right"},
            {"type": "field", "path": "name", "label": "Ordine n.", "align": "center"},
        ])
        self.assertIn('<div style="text-align: right"><span t-field="o.name"/></div>', xml)
        self.assertIn('<div style="text-align: center"><span><span class="o_rs_label">Ordine n.</span>', xml)
        with self.assertRaises(compiler.CompileError):
            compile_([{"type": "field", "path": "name", "align": "middle"}])
        canvas = self._annotated([{"type": "field", "path": "name", "align": "right"},
                               {"type": "field", "path": "name"}])
        self.assertIn('<div class="o_rs_cv_block o_rs_cv_field" data-rs-path="0"', canvas)
        self.assertIn('<span class="o_rs_cv_block o_rs_cv_field" data-rs-path="1"', canvas)

    def test_invalid_align_rejected(self):
        for block in ({"type": "text", "content": "x", "align": "middle"},
                      {"type": "section", "align": 1, "children": []},
                      {"type": "table", "source": "order_line",
                       "columns": [{"path": "name", "align": "top"}]}):
            with self.assertRaises(compiler.CompileError, msg=block):
                compile_([block])


def etree_ok(arch):
    """Il template annotato è XML ben formato."""
    import xml.dom.minidom
    xml.dom.minidom.parseString(arch)

if __name__ == "__main__":
    unittest.main()
