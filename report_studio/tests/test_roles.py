# -*- coding: utf-8 -*-
"""Uso di Report Studio da utenti NON amministratori.

I test girano di norma come superutente e non vedono i problemi di permessi:
qui ogni operazione passa da with_user() con i ruoli reali.
"""
import json
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

SALES = "sales_team.group_sale_salesman"


@tagged("post_install", "-at_install")
class TestRoles(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = new_test_user(
            cls.env, login="rs_viewer", groups="base.group_user,%s,report_studio.group_rs_viewer" % SALES
        )
        cls.editor = new_test_user(
            cls.env, login="rs_editor", groups="base.group_user,%s,report_studio.group_rs_editor" % SALES
        )
        cls.manager = new_test_user(
            cls.env, login="rs_manager", groups="base.group_user,%s,report_studio.group_rs_manager" % SALES
        )
        partner = cls.env["res.partner"].create({"name": "Cliente ruoli"})
        # Venditore "solo i propri documenti": l'ordine deve essere dell'editor.
        cls.order = cls.env["sale.order"].create({"partner_id": partner.id, "user_id": cls.editor.id})

    def _rs(self, user):
        return self.env["rs.report"].with_user(user)

    def test_editor_full_workflow(self):
        Report = self._rs(self.editor)
        models = {m["model"] for m in Report.get_model_options()}
        self.assertIn("sale.order", models)
        self.assertNotIn("ir.model", models)  # non leggibile dall'editor
        fields = {f["name"]: f for f in Report.get_model_fields("sale.order")}
        self.assertEqual(fields["order_line"]["relation"], "sale.order.line")

        report = Report.browse(Report.create_new_report("Report editor", "sale.order"))
        self.assertEqual(report.model_name, "sale.order")
        rows = Report.search_read([("id", "=", report.id)], ["name", "model_name", "report_mode"])
        self.assertEqual(rows[0]["model_name"], "sale.order")

        definition = json.dumps({"children": [
            {"type": "text", "content": "Ciao"},
            {"type": "field", "path": "partner_id.name"},
            {"type": "table", "source": "order_line", "columns": [{"path": "name", "label": ""}]},
        ]})
        report.action_save_version(definition, comment="editor")
        self.assertEqual(report.version_count, 2)
        html = report._render_preview_pdf(definition, self.order.id)
        self.assertIn(b"Ciao", html)
        report.restore_version_by_id(report.version_ids.filtered(lambda v: v.version_no == 1).id)
        self.assertEqual(report.version_count, 3)
        copy_id = report.copy_version_by_id(report.current_version_id.id, "Copia editor")
        self.assertEqual(Report.browse(copy_id).version_count, 1)

    def test_preview_is_not_rendered_as_superuser(self):
        report = self._rs(self.editor).browse(
            self._rs(self.editor).create_new_report("Anteprima", "sale.order")
        )
        IrActionsReport = type(self.env["ir.actions.report"])
        original = IrActionsReport._render_qweb_pdf
        seen = []

        def spy(records, *args, **kwargs):
            seen.append((records.env.su, records.env.uid))
            return original(records, *args, **kwargs)

        with patch.object(IrActionsReport, "_render_qweb_pdf", spy):
            report._render_preview_pdf(json.dumps({"children": []}), self.order.id)
        self.assertEqual(seen, [(False, self.editor.id)])

    def test_editor_cannot_read_unreadable_model(self):
        with self.assertRaises(AccessError):
            self._rs(self.editor).get_model_fields("ir.model")
        with self.assertRaises(AccessError):
            self._rs(self.editor).create_new_report("No", "ir.model")

    def test_viewer_is_read_only(self):
        report = self.env["rs.report"].create({
            "name": "Solo lettura", "model_id": self.env["ir.model"]._get("sale.order").id,
        })
        as_viewer = report.with_user(self.viewer)
        self.assertEqual(as_viewer.model_name, "sale.order")
        with self.assertRaises(AccessError):
            self._rs(self.viewer).create_new_report("No", "sale.order")
        with self.assertRaises(AccessError):
            as_viewer.action_save_version(json.dumps({"children": []}))

    def test_qweb_only_for_managers(self):
        action = self.env.ref("sale.action_report_saleorder")
        editor_catalog = self._rs(self.editor).get_source_catalog()
        self.assertFalse([i for i in editor_catalog if i["key"].startswith("action:")])
        with self.assertRaises(UserError):
            self._rs(self.editor).create_from_source("No", "action:%s" % action.id)

        manager_catalog = self._rs(self.manager).get_source_catalog()
        self.assertIn("action:%s" % action.id, [i["key"] for i in manager_catalog])
        report_id = self._rs(self.manager).create_from_source("Ordine", "action:%s" % action.id)
        self.assertEqual(self._rs(self.manager).browse(report_id).report_mode, "qweb")

    def test_role_field(self):
        user = new_test_user(self.env, login="rs_role", groups="base.group_user")
        self.assertEqual(user.report_studio_role, "none")
        user.report_studio_role = "editor"
        self.assertTrue(user.has_group("report_studio.group_rs_editor"))
        self.assertTrue(user.has_group("report_studio.group_rs_viewer"))
        self.assertFalse(user.has_group("report_studio.group_rs_manager"))
        self.assertEqual(user.report_studio_role, "editor")
        user.report_studio_role = "none"
        self.assertFalse(user.has_group("report_studio.group_rs_user"))

    def test_only_managers_change_roles(self):
        user = new_test_user(self.env, login="rs_target", groups="base.group_user")
        # "Diritti di accesso" senza ruolo Report Studio: non può assegnare ruoli RS.
        access_admin = new_test_user(
            self.env, login="rs_access_admin", groups="base.group_user,base.group_erp_manager"
        )
        with self.assertRaises(AccessError):
            user.with_user(access_admin).report_studio_role = "editor"
        self.assertEqual(user.report_studio_role, "none")
        # Con anche il ruolo Amministratore Report Studio invece può.
        rs_admin = new_test_user(
            self.env, login="rs_access_admin_rs",
            groups="base.group_user,base.group_erp_manager,report_studio.group_rs_manager",
        )
        user.with_user(rs_admin).report_studio_role = "viewer"
        user.invalidate_recordset()
        self.assertEqual(user.report_studio_role, "viewer")
        self.assertFalse(user.has_group("report_studio.group_rs_editor"))
