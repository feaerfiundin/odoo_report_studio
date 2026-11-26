# -*- coding: utf-8 -*-
import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestRsReport(TransactionCase):

    def setUp(self):
        super().setUp()
        self.model = self.env["ir.model"]._get("sale.order")
        self.report = self.env["rs.report"].create({
            "name": "Test report",
            "model_id": self.model.id,
        })

    def test_initial_version_and_action(self):
        self.assertEqual(self.report.version_count, 1)
        self.assertTrue(self.report.action_id)
        self.assertEqual(
            self.report.action_id.report_name,
            self.report.current_version_id.view_id.key,
        )

    def test_new_version_and_restore(self):
        definition = {"type": "page", "children": [{"type": "text", "content": "Ciao"}]}
        v2 = self.report._create_version(json.dumps(definition), comment="prova")
        self.assertEqual(self.report.current_version_id, v2)
        self.assertEqual(self.report.action_id.report_name, v2.view_id.key)
        v1 = self.report.version_ids.filtered(lambda v: v.version_no == 1)
        v3 = self.report.action_restore_version(v1)
        self.assertEqual(v3.version_no, 3)
        self.assertEqual(self.report.current_version_id, v3)

    def test_version_is_immutable(self):
        with self.assertRaises(UserError):
            self.report.version_ids[0].write({"comment": "modifica"})

    def test_invalid_field_is_rejected(self):
        bad = {"type": "page", "children": [{"type": "field", "path": "campo_inesistente"}]}
        with self.assertRaises(UserError):
            self.report._create_version(json.dumps(bad))

    def test_table_source_must_be_x2many(self):
        bad = {"type": "page", "children": [{
            "type": "table",
            "source": "partner_id",
            "columns": [{"path": "name"}],
        }]}
        with self.assertRaises(UserError):
            self.report._create_version(json.dumps(bad))

    def test_preview_rejects_invalid_definition_before_rendering(self):
        bad = {"type": "page", "children": [{"type": "field", "path": "campo_inesistente"}]}
        with self.assertRaises(UserError):
            self.report._render_preview_pdf(json.dumps(bad), res_id=1)

    def test_copy_version_creates_report_without_history(self):
        definition = {"type": "page", "children": [{"type": "text", "content": "Copia"}]}
        self.report._create_version(json.dumps(definition), comment="v2")
        source_version = self.report.current_version_id
        copy = self.report.action_copy_version_to_new_report(source_version, name="Nuovo")
        self.assertEqual(copy.name, "Nuovo")
        self.assertEqual(copy.version_count, 1)
        self.assertEqual(copy.current_version_id.version_no, 1)
        self.assertEqual(copy.current_version_id.definition, source_version.definition)
        self.assertEqual(self.report.version_count, 2)

    def test_archive_removes_print_binding(self):
        self.assertTrue(self.report.action_id.binding_model_id)
        self.report.active = False
        self.assertFalse(self.report.action_id.binding_model_id)
        self.report.active = True
        self.assertEqual(self.report.action_id.binding_model_id, self.report.model_id)

    def test_saved_layouts_list_shows_archived(self):
        action = self.env.ref("report_studio.action_rs_report_list")
        self.assertEqual(self.env.ref("report_studio.menu_report_studio_root").action, action)
        context = safe_eval(action.context)
        self.assertIs(context.get("active_test"), False)
        self.report.active = False
        Report = self.env["rs.report"].with_context(context)
        self.assertIn(self.report, Report.search([]))
        self.assertIn(self.report, Report.search([("active", "=", False)]))
        # Elenco e ricerca si caricano; Attivo segue Ultima modifica.
        views = Report.get_views([(action.view_id.id, "list"), (action.search_view_id.id, "search")])
        arch = views["views"]["list"]["arch"]
        self.assertIn('js_class="rs_report_list"', arch)
        self.assertLess(arch.index('name="write_date"'), arch.index('name="active"'))

    def test_render_canvas_marks_blocks_with_real_data(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "field", "path": "name"},
            {"type": "field", "path": ""},
            {"type": "if", "path": "amount_total", "op": "<", "value": 0,
             "children": [{"type": "text", "content": "Nascosto"}]},
        ]})
        views_before = self.env["ir.ui.view"].sudo().search_count([])
        html = self.report.render_canvas(definition, order.id)
        self.assertIn('data-rs-path="0"', html)
        self.assertIn(order.name, html)
        self.assertIn("o_rs_cv_invalid", html)          # campo vuoto: segnaposto
        self.assertIn("Condizione falsa", html)          # if sempre selezionabile
        self.assertNotIn("Nascosto", html)
        # vista e azione temporanee eliminate
        self.assertEqual(self.env["ir.ui.view"].sudo().search_count([]), views_before)
        with self.assertRaises(UserError):
            self.report.render_canvas(definition, 0)

    def test_fonts_label_and_widths_in_pdf_template(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "text", "content": "Titolo", "font": {"size": 18, "bold": True}},
            {"type": "field", "path": "name", "label": "Ordine n.", "label_font": {"italic": True}},
            {"type": "table", "source": "order_line", "head_font": {"underline": True},
             "columns": [{"path": "name", "label": "Descrizione", "width": 75, "locked": True},
                         {"path": "product_uom_qty", "label": "Qtà", "width": 25}]},
        ]})
        version = self.report._create_version(definition)
        self.assertIn("font-size: 18pt; font-weight: bold", version.arch)
        self.assertIn("width: 75%", version.arch)
        html = self.report.render_canvas(definition, order.id)
        self.assertIn("Ordine n.", html)
        self.assertIn(order.name, html)

    def test_layout_blocks_save_and_canvas(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "section", "margins": {"left": 10}, "children": [
                {"type": "columns", "divider": True, "children": [
                    {"type": "column", "margins": {"right": 2}, "children": [{"type": "field", "path": "name"}]},
                    {"type": "column", "children": []},
                ]},
            ]},
            {"type": "separator", "style": "dotted", "thickness": 2},
            {"type": "spacer", "height": 20},
            {"type": "page_break"},
        ]})
        version = self.report._create_version(definition)
        self.assertIn("border-left: 1px solid #333", version.arch)
        self.assertIn("page-break-after: always", version.arch)
        html = self.report.render_canvas(definition, order.id)
        self.assertIn('data-rs-path="0.0.1" data-rs-type="column"', html)
        self.assertIn("Colonna vuota", html)
        self.assertIn("Interruzione di pagina", html)
        self.assertIn(order.name, html)

    def test_text_alignment_child_wins(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "section", "align": "right", "children": [
                {"type": "text", "content": "Centrato", "align": "center"},
                {"type": "field", "path": "name"},
            ]},
            {"type": "table", "source": "order_line", "align": "center",
             "columns": [{"path": "name", "label": "Descrizione", "align": "left"}]},
        ]})
        version = self.report._create_version(definition)
        self.assertIn('<div class="page" style="text-align: left">', version.arch)
        self.assertIn('<div style="text-align: right">', version.arch)
        self.assertIn('<p style="text-align: center">Centrato</p>', version.arch)
        self.assertIn('<th style="text-align: left">Descrizione</th>', version.arch)
        self.assertIn("Centrato", self.report.render_canvas(definition, order.id))

    def _sale_order(self):
        partner = self.env["res.partner"].create({"name": "Cliente anteprima"})
        return self.env["sale.order"].create({"partner_id": partner.id})

    def test_preview_renders_definition(self):
        order = self._sale_order()
        definition = {"children": [{"type": "text", "content": "Testo anteprima"},
                                   {"type": "field", "path": "name"}]}
        # In modalità test Odoo restituisce l'HTML del report invece del PDF.
        html = self.report._render_preview_pdf(json.dumps(definition), order.id)
        self.assertIn(b"Testo anteprima", html)
        self.assertIn(order.name.encode(), html)

    def test_preview_respects_record_access(self):
        """L'anteprima non deve leggere i dati in sudo."""
        order = self._sale_order()
        viewer = new_test_user(
            self.env, login="rs_viewer_no_sales",
            groups="base.group_user,report_studio.group_rs_viewer",
        )
        definition = {"children": [{"type": "field", "path": "name"}]}
        with self.assertRaises(AccessError):
            self.report.with_user(viewer)._render_preview_pdf(json.dumps(definition), order.id)

    def test_model_name_is_stored(self):
        self.assertEqual(self.report.model_name, "sale.order")

    def test_rename_updates_print_action(self):
        self.report.name = "Nuovo nome"
        self.assertEqual(self.report.action_id.name, "Nuovo nome")

    def test_unlink_removes_views_and_action(self):
        self.report._create_version(json.dumps({"children": []}))
        views = self.report.version_ids.view_id
        action = self.report.action_id
        self.assertEqual(len(views), 2)
        self.report.unlink()
        self.assertFalse(views.exists())
        self.assertFalse(action.exists())

    def test_version_of_other_report_is_rejected(self):
        other = self.env["rs.report"].create({"name": "Altro", "model_id": self.model.id})
        with self.assertRaises(UserError):
            self.report.restore_version_by_id(other.current_version_id.id)
        with self.assertRaises(UserError):
            self.report.copy_version_by_id(other.current_version_id.id)
        with self.assertRaises(UserError):
            self.report.restore_version_by_id(999999999)

    def test_create_from_studio_report(self):
        definition = {"layout": "basic", "children": [{"type": "text", "content": "Origine"}]}
        self.report._create_version(json.dumps(definition))
        new_id = self.env["rs.report"].create_from_source("Copia", "report:%s" % self.report.id)
        copy = self.env["rs.report"].browse(new_id)
        self.assertEqual(copy.model_name, "sale.order")
        self.assertEqual(copy.report_mode, "blocks")
        self.assertEqual(json.loads(copy.current_version_id.definition), definition)

    def test_create_from_odoo_document(self):
        action = self.env.ref("sale.action_report_saleorder")
        new_id = self.env["rs.report"].create_from_source("Ordine", "action:%s" % action.id)
        copy = self.env["rs.report"].browse(new_id)
        self.assertEqual(copy.report_mode, "qweb")
        self.assertEqual(copy.model_name, "sale.order")
        self.assertIn(copy.action_id.report_name, copy.current_version_id.arch)

    def test_create_from_invalid_source(self):
        for key in ("", "report:abc", "altro:1", "report:999999999"):
            with self.assertRaises(UserError):
                self.env["rs.report"].create_from_source("X", key)

    def test_layout_is_kept_in_compiled_template(self):
        version = self.report._create_version(json.dumps({"layout": "basic", "children": []}))
        self.assertIn("web.basic_layout", version.arch)
