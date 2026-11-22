# -*- coding: utf-8 -*-
import json

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


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
