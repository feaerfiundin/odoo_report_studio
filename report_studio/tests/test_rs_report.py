# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import json

from odoo.exceptions import AccessError, UserError, ValidationError
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
        v2 = self.report._create_version(json.dumps(definition), comment="test")
        self.assertEqual(self.report.current_version_id, v2)
        self.assertEqual(self.report.action_id.report_name, v2.view_id.key)
        v1 = self.report.version_ids.filtered(lambda v: v.version_no == 1)
        v3 = self.report.action_restore_version(v1)
        self.assertEqual(v3.version_no, 3)
        self.assertEqual(self.report.current_version_id, v3)

    def test_version_is_immutable(self):
        with self.assertRaises(UserError):
            self.report.version_ids[0].write({"comment": "change"})

    def test_invalid_field_is_rejected(self):
        bad = {"type": "page", "children": [{"type": "field", "path": "missing_field"}]}
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
        bad = {"type": "page", "children": [{"type": "field", "path": "missing_field"}]}
        with self.assertRaises(UserError):
            self.report._render_preview_pdf(json.dumps(bad), res_id=1)

    def test_copy_version_creates_report_without_history(self):
        definition = {"type": "page", "children": [{"type": "text", "content": "Copy"}]}
        self.report._create_version(json.dumps(definition), comment="v2")
        source_version = self.report.current_version_id
        copy = self.report.action_copy_version_to_new_report(source_version, name="New")
        self.assertEqual(copy.name, "New")
        self.assertEqual(copy.version_count, 1)
        self.assertEqual(copy.current_version_id.version_no, 1)
        self.assertEqual(copy.current_version_id.definition, source_version.definition)
        self.assertEqual(self.report.version_count, 2)

    def test_archive_removes_print_binding(self):
        self.report.action_add_print_menu()
        self.assertTrue(self.report.action_id.binding_model_id)
        self.report.active = False
        self.assertFalse(self.report.action_id.binding_model_id)
        self.report.active = True
        self.assertEqual(self.report.action_id.binding_model_id, self.report.model_id)

    def test_print_menu_only_with_button(self):
        """A new report is not in the Print menu until it is added."""
        action = self.report.action_id
        self.assertFalse(self.report.in_print_menu)
        self.assertFalse(action.binding_model_id)
        self.report.action_add_print_menu()
        self.assertEqual(action.binding_model_id, self.model)
        self.assertEqual(action.binding_type, "report")
        # a new version does not change the choice
        self.report._create_version(json.dumps({"children": []}))
        self.assertEqual(action.binding_model_id, self.model)
        self.report.action_remove_print_menu()
        self.assertFalse(action.binding_model_id)
        self.report.active = False
        with self.assertRaises(UserError):
            self.report.action_add_print_menu()

    def test_print_settings_copied_to_action(self):
        paper = self.env["report.paperformat"].search([], limit=1)
        self.report.write({
            "print_name": "Print order",
            "paperformat_id": paper.id,
            "print_report_name": "'Order - %s' % object.name",
            "attachment": "(object.name + '.pdf')",
            "attachment_use": True,
        })
        action = self.report.action_id
        self.assertEqual(action.name, "Print order")
        self.assertEqual(action.paperformat_id, paper)
        self.assertEqual(action.print_report_name, "'Order - %s' % object.name")
        self.assertEqual(action.attachment, "(object.name + '.pdf')")
        self.assertTrue(action.attachment_use)
        # empty menu name: back to the report name
        self.report.print_name = False
        self.assertEqual(action.name, "Test report")
        with self.assertRaises(ValidationError):
            self.report.print_report_name = "'Order' %"

    def test_print_page_roles(self):
        editor = new_test_user(self.env, login="rs_print_editor",
                               groups="base.group_user,report_studio.group_rs_editor")
        viewer = new_test_user(self.env, login="rs_print_viewer",
                               groups="base.group_user,report_studio.group_rs_viewer")
        paper = self.env["report.paperformat"].search([], limit=1)
        as_editor = self.report.with_user(editor)
        as_editor.action_add_print_menu()
        as_editor.write({"paperformat_id": paper.id, "print_name": "From editor"})
        self.assertEqual(self.report.action_id.binding_model_id, self.model)
        self.assertEqual(self.report.action_id.name, "From editor")
        with self.assertRaises(AccessError):
            self.report.with_user(viewer).action_remove_print_menu()
        self.assertTrue(self.report.with_user(viewer).in_print_menu)  # reading allowed
        # page and menu
        action = self.env.ref("report_studio.action_rs_report_print")
        menu = self.env.ref("report_studio.menu_report_studio_print")
        self.assertEqual(menu.action, action)
        self.assertEqual(menu.parent_id, self.env.ref("report_studio.menu_report_studio_root"))
        form = self.env["rs.report"].with_user(editor).get_views(
            [(self.env.ref("report_studio.rs_report_print_view_form").id, "form")])["views"]["form"]["arch"]
        self.assertIn("action_add_print_menu", form)
        form_viewer = self.env["rs.report"].with_user(viewer).get_views(
            [(self.env.ref("report_studio.rs_report_print_view_form").id, "form")])["views"]["form"]["arch"]
        self.assertNotIn("action_add_print_menu", form_viewer)

    def test_saved_layouts_list_shows_archived(self):
        action = self.env.ref("report_studio.action_rs_report_list")
        self.assertEqual(self.env.ref("report_studio.menu_report_studio_root").action, action)
        self.assertEqual(self.env.ref("report_studio.menu_report_studio_layouts").action, action)
        context = safe_eval(action.context)
        self.assertIs(context.get("active_test"), False)
        # By default the search starts with the Active filter, which can be removed.
        self.assertEqual(context.get("search_default_filter_active"), 1)
        self.report.active = False
        Report = self.env["rs.report"].with_context(context)
        self.assertIn(self.report, Report.search([]))
        self.assertIn(self.report, Report.search([("active", "=", False)]))
        # List and search load; Active follows Last Modified.
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
             "children": [{"type": "text", "content": "Hidden"}]},
        ]})
        views_before = self.env["ir.ui.view"].sudo().search_count([])
        html = self.report.render_canvas(definition, order.id)
        self.assertIn('data-rs-path="0"', html)
        self.assertIn(order.name, html)
        self.assertIn("o_rs_cv_invalid", html)          # empty field: placeholder
        self.assertIn("Condition false", html)  # "if" always selectable
        self.assertNotIn("Hidden", html)
        # temporary view and action deleted
        self.assertEqual(self.env["ir.ui.view"].sudo().search_count([]), views_before)
        with self.assertRaises(UserError):
            self.report.render_canvas(definition, 0)

    def test_fonts_label_and_widths_in_pdf_template(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "text", "content": "Title", "font": {"size": 18, "bold": True}},
            {"type": "field", "path": "name", "label": "Order no.", "label_font": {"italic": True}},
            {"type": "table", "source": "order_line", "head_font": {"underline": True},
             "margins": {"left": 4},
             "columns": [{"path": "name", "label": "Description", "width": 75, "locked": True},
                         {"path": "product_uom_qty", "label": "Qty", "width": 25}]},
        ]})
        version = self.report._create_version(definition)
        self.assertIn("font-size: 18pt; font-weight: bold", version.arch)
        self.assertIn("width: 75%", version.arch)
        self.assertIn('<div style="padding: 0mm 0mm 0mm 4mm">', version.arch)
        html = self.report.render_canvas(definition, order.id)
        self.assertIn("Order no.", html)
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
        self.assertIn("Empty column", html)
        self.assertIn("Page break", html)
        self.assertIn(order.name, html)

    def test_text_alignment_child_wins(self):
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "section", "align": "right", "children": [
                {"type": "text", "content": "Centered\nSecond line", "align": "center"},
                {"type": "field", "path": "name"},
                {"type": "field", "path": "name", "label": "N.", "align": "center"},
            ]},
            {"type": "table", "source": "order_line", "align": "center",
             "columns": [{"path": "name", "label": "Description", "align": "left"}]},
        ]})
        version = self.report._create_version(definition)
        self.assertIn('<div class="page" style="text-align: left">', version.arch)
        self.assertIn('<div style="text-align: right">', version.arch)
        self.assertIn('<p style="text-align: center">Centered<br/>Second line</p>', version.arch)
        self.assertIn('<th style="text-align: left">Description</th>', version.arch)
        self.assertIn('<div style="text-align: center"><span><span class="o_rs_label">N.</span>', version.arch)
        self.assertIn("Centered", self.report.render_canvas(definition, order.id))

    def test_print_in_customer_language(self):
        self.env["res.lang"]._activate_lang("it_IT")
        order = self._sale_order()
        order.partner_id.lang = "it_IT"
        children = [{"type": "text", "content": "Hello", "translations": {"it_IT": "Ciao"}},
                    {"type": "field", "path": "name", "label": "Order", "label_translations": {"it_IT": "Order"}}]
        on = {"print_lang": {"enabled": True, "field": "partner_id"}, "children": children}
        html = self.report.with_context(lang="en_US")._render_preview_pdf(json.dumps(on), order.id)
        self.assertIn(b"Ciao", html)
        self.assertIn(b"Order", html)
        self.assertNotIn(b"Hello", html)
        # without the option: language of the user printing
        off = {"children": children}
        html = self.report.with_context(lang="en_US")._render_preview_pdf(json.dumps(off), order.id)
        self.assertIn(b"Hello", html)
        self.assertNotIn(b"Ciao", html)
        # customer without language: language of the user printing
        order.partner_id.lang = False
        html = self.report.with_context(lang="en_US")._render_preview_pdf(json.dumps(on), order.id)
        self.assertIn(b"Hello", html)
        # saved version: two views, the real print uses the translated page
        order.partner_id.lang = "it_IT"
        version = self.report._create_version(json.dumps(on))
        self.assertTrue(version.document_view_id)
        self.assertEqual(version.document_view_id.key, version.view_id.key + "_document")
        html, _fmt = self.env["ir.actions.report"].with_context(lang="en_US")._render_qweb_html(
            self.report.action_id.report_name, [order.id])
        self.assertIn(b"Ciao", html)
        views = version.view_id | version.document_view_id
        self.report.unlink()
        self.assertFalse(views.exists())

    def test_canvas_in_editing_language(self):
        self.env["res.lang"]._activate_lang("it_IT")
        order = self._sale_order()
        definition = json.dumps({"children": [
            {"type": "text", "content": "Hello", "translations": {"it_IT": "Ciao"}}]})
        self.assertIn("Ciao", self.report.render_canvas(definition, order.id, lang="it_IT"))
        self.assertIn("Hello", self.report.with_context(lang="en_US").render_canvas(definition, order.id))
        # inactive language: ignored
        self.assertIn("Hello", self.report.with_context(lang="en_US").render_canvas(definition, order.id, lang="xx_XX"))
        langs = self.report.get_languages()
        self.assertIn("it_IT", [lang["code"] for lang in langs["langs"]])
        self.assertIn(langs["main"], [lang["code"] for lang in langs["langs"]])

    def test_print_lang_field_validated(self):
        bad = {"print_lang": {"enabled": True, "field": "name"}, "children": []}
        with self.assertRaises(UserError):
            self.report._create_version(json.dumps(bad))

    def test_messages_translated_in_user_language(self):
        """Compiler errors and editor placeholders follow the user language."""
        self.env["res.lang"]._activate_lang("it_IT")
        bad = json.dumps({"children": [{"type": "field", "path": "missing_field"}]})
        with self.assertRaises(UserError) as error:
            self.report.with_context(lang="en_US")._create_version(bad)
        self.assertIn("Invalid report definition", str(error.exception))
        self.assertIn("does not exist on model", str(error.exception))
        with self.assertRaises(UserError) as error:
            self.report.with_context(lang="it_IT")._create_version(bad)
        self.assertIn("Definizione del report non valida", str(error.exception))
        self.assertIn("non esiste sul modello", str(error.exception))
        order = self._sale_order()
        definition = json.dumps({"children": [{"type": "page_break"}]})
        html = self.report.with_context(lang="it_IT").render_canvas(definition, order.id)
        self.assertIn("Interruzione di pagina", html)
        html = self.report.with_context(lang="en_US").render_canvas(definition, order.id)
        self.assertIn("Page break", html)
        # Editing the Italian texts with an English interface: placeholders in English.
        html = self.report.with_context(lang="en_US").render_canvas(definition, order.id, lang="it_IT")
        self.assertIn("Page break", html)
        self.assertNotIn("Interruzione di pagina", html)

    def test_section_label_borders_and_classes(self):
        self.env["res.lang"]._activate_lang("it_IT")
        order = self._sale_order()
        definition = json.dumps({"children": [{
            "type": "section",
            "class": "small o_rs_keep_together",
            "title": {"text": "Customer", "translations": {"it_IT": "Cliente"},
                      "background": "#e9ecef"},
            "border": {"sides": ["top", "bottom"], "style": "double", "width": 3},
            "children": [{"type": "field", "path": "name"}],
        }]})
        version = self.report._create_version(definition)
        self.assertIn('class="small o_rs_keep_together"', version.arch)
        self.assertIn("border-top: 3px double #333333", version.arch)
        self.assertIn('class="o_rs_section_title"', version.arch)
        html = self.report.render_canvas(definition, order.id, lang="it_IT")
        self.assertIn("Cliente", html)
        self.assertIn(order.name, html)
        # the report assets define the "do not split" class
        bundle = self.env["ir.qweb"]._get_asset_bundle("web.report_assets_common")
        self.assertIn("/report_studio/static/src/scss/report.scss",
                      [f["url"] for f in bundle.files])

    def _sale_order(self):
        partner = self.env["res.partner"].create({"name": "Preview customer"})
        return self.env["sale.order"].create({"partner_id": partner.id})

    def test_preview_renders_definition(self):
        order = self._sale_order()
        definition = {"children": [{"type": "text", "content": "Preview text"},
                                   {"type": "field", "path": "name"}]}
        # In test mode Odoo returns the report HTML instead of the PDF.
        html = self.report._render_preview_pdf(json.dumps(definition), order.id)
        self.assertIn(b"Preview text", html)
        self.assertIn(order.name.encode(), html)

    def test_preview_respects_record_access(self):
        """The preview must not read the data in sudo."""
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
        self.report.name = "New name"
        self.assertEqual(self.report.action_id.name, "New name")

    def test_unlink_removes_views_and_action(self):
        self.report._create_version(json.dumps({"children": []}))
        views = self.report.version_ids.view_id
        action = self.report.action_id
        self.assertEqual(len(views), 2)
        self.report.unlink()
        self.assertFalse(views.exists())
        self.assertFalse(action.exists())

    def test_version_of_other_report_is_rejected(self):
        other = self.env["rs.report"].create({"name": "Other", "model_id": self.model.id})
        with self.assertRaises(UserError):
            self.report.restore_version_by_id(other.current_version_id.id)
        with self.assertRaises(UserError):
            self.report.copy_version_by_id(other.current_version_id.id)
        with self.assertRaises(UserError):
            self.report.restore_version_by_id(999999999)

    def test_create_from_studio_report(self):
        definition = {"layout": "basic", "children": [{"type": "text", "content": "Source"}]}
        self.report._create_version(json.dumps(definition))
        new_id = self.env["rs.report"].create_from_source("Copy", "report:%s" % self.report.id)
        copy = self.env["rs.report"].browse(new_id)
        self.assertEqual(copy.model_name, "sale.order")
        self.assertEqual(copy.report_mode, "blocks")
        self.assertEqual(json.loads(copy.current_version_id.definition), definition)

    def test_create_from_odoo_document(self):
        action = self.env.ref("sale.action_report_saleorder")
        new_id = self.env["rs.report"].create_from_source("Order", "action:%s" % action.id)
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
