# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

IMMUTABLE_FIELDS = {"report_id", "version_no", "definition", "comment", "arch", "view_id"}


class RsReportVersion(models.Model):
    """Snapshot immutabile di un report: definizione JSON, template QWeb e vista.

    Una volta creata, la versione non può essere modificata: le modifiche
    producono una nuova versione tramite rs.report._create_version().
    """

    _name = "rs.report.version"
    _description = "Report Studio - Versione"
    _order = "version_no desc"

    report_id = fields.Many2one(
        "rs.report", required=True, ondelete="cascade", index=True
    )
    version_no = fields.Integer(required=True, readonly=True)
    definition = fields.Text(
        required=True,
        help="Definizione JSON dei blocchi del report.",
    )
    arch = fields.Text(
        readonly=True,
        help="Template QWeb generato dalla definizione.",
    )
    view_id = fields.Many2one(
        "ir.ui.view",
        string="Vista QWeb",
        readonly=True,
        ondelete="restrict",
    )
    comment = fields.Char(string="Commento")
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        string="Autore",
    )
    is_active = fields.Boolean(
        compute="_compute_is_active", string="Attiva"
    )

    _sql_constraints = [
        (
            "report_version_unique",
            "unique(report_id, version_no)",
            "Il numero di versione deve essere unico per report.",
        ),
    ]

    @api.depends("report_id.current_version_id")
    def _compute_is_active(self):
        for version in self:
            version.is_active = version.report_id.current_version_id == version

    @api.constrains("definition")
    def _check_definition_json(self):
        for version in self:
            try:
                json.loads(version.definition)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    _("La definizione del report non è JSON valido: %s") % exc
                )

    def write(self, vals):
        if not self.env.context.get("rs_internal_write") and (
            IMMUTABLE_FIELDS & set(vals)
        ):
            raise UserError(
                _("Le versioni dei report sono immutabili. "
                  "Crea una nuova versione per modificarne il contenuto.")
            )
        return super().write(vals)

    def unlink(self):
        raise UserError(
            _("Le versioni dei report non possono essere eliminate: "
              "lo storico è permanente.")
        )
