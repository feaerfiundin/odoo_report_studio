# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models

EMPTY_DEFINITION = json.dumps({"type": "page", "children": []})


class RsReport(models.Model):
    """Report disegnato con Report Studio.

    Il record contiene l'identità del report e il puntatore alla versione
    attiva. Il contenuto vive nelle versioni (rs.report.version).
    """

    _name = "rs.report"
    _description = "Report Studio - Report"
    _order = "name"

    name = fields.Char(required=True, translate=False)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model",
        string="Modello Odoo",
        required=True,
        ondelete="cascade",
        help="Modello su cui il report viene eseguito (es. sale.order).",
    )
    version_ids = fields.One2many(
        "rs.report.version", "report_id", string="Versioni"
    )
    current_version_id = fields.Many2one(
        "rs.report.version",
        string="Versione attiva",
        copy=False,
    )
    version_count = fields.Integer(
        compute="_compute_version_count", string="N. versioni"
    )

    @api.depends("version_ids")
    def _compute_version_count(self):
        for report in self:
            report.version_count = len(report.version_ids)

    def _create_version(self, definition, comment=False):
        """Crea una nuova versione immutabile e la rende attiva."""
        self.ensure_one()
        next_no = (max(self.version_ids.mapped("version_no"), default=0)) + 1
        version = self.env["rs.report.version"].with_context(
            rs_internal_write=True
        ).create({
            "report_id": self.id,
            "version_no": next_no,
            "definition": definition or EMPTY_DEFINITION,
            "comment": comment,
        })
        self.with_context(rs_internal_write=True).current_version_id = version
        return version

    def action_restore_version(self, version):
        """Ripristina una versione creando una nuova versione copiata da essa."""
        self.ensure_one()
        if version.report_id != self:
            raise ValueError("La versione non appartiene a questo report.")
        return self._create_version(
            version.definition,
            comment="Ripristino dalla versione %s" % version.version_no,
        )
