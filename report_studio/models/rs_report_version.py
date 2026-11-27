# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import json

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

IMMUTABLE_FIELDS = {
    "report_id",
    "version_no",
    "definition",
    "comment",
    "arch",
    "view_id",
    "document_view_id",
}


class RsReportVersion(models.Model):
    """Immutable snapshot of a report: JSON definition, QWeb template and view.

    Once created, a version cannot be changed: changes produce a new version
    through rs.report._create_version().
    """

    _name = "rs.report.version"
    _description = "Report Studio - Version"
    _order = "version_no desc"

    report_id = fields.Many2one(
        "rs.report", string="Report", required=True, ondelete="cascade", index=True
    )
    version_no = fields.Integer(string="Version", required=True, readonly=True)
    definition = fields.Text(
        required=True,
        help="JSON definition of the report blocks.",
    )
    arch = fields.Text(
        readonly=True,
        help="QWeb template generated from the definition.",
    )
    view_id = fields.Many2one(
        "ir.ui.view",
        string="QWeb View",
        readonly=True,
        ondelete="restrict",
    )
    document_view_id = fields.Many2one(
        "ir.ui.view",
        string="Page QWeb View",
        readonly=True,
        ondelete="restrict",
        help="Only when printing in the customer language: the page, called by "
        "the main view with t-lang.",
    )
    comment = fields.Char()
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        string="Author",
    )
    is_active = fields.Boolean(compute="_compute_is_active", string="Active")

    _sql_constraints = [
        (
            "report_version_unique",
            "unique(report_id, version_no)",
            "The version number must be unique per report.",
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
                    self.env._("The report definition is not valid JSON: %s", exc)
                ) from exc

    def write(self, vals):
        # No exception through the context: the context also comes from RPC clients.
        if IMMUTABLE_FIELDS & set(vals):
            raise UserError(
                self.env._(
                    "Report versions are immutable. "
                    "Create a new version to change their content."
                )
            )
        return super().write(vals)

    def unlink(self):
        raise UserError(
            self.env._(
                "Report versions cannot be deleted: the history is permanent."
            )
        )
