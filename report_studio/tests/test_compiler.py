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


def etree_ok(arch):
    """Il template annotato è XML ben formato."""
    import xml.dom.minidom
    xml.dom.minidom.parseString(arch)

if __name__ == "__main__":
    unittest.main()
