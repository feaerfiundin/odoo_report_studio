# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import json

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..lib.compiler import CompileError, compile_templates


class RsBlock(models.Model):
    """Reusable block (custom content) of Report Studio.

    It holds one block of the editor (e.g. a Section with the fields of a
    contact) with field paths relative to its own model (e.g. res.partner:
    ``name``, ``street``). Inserted into a report of another model, the paths
    get the prefix of the linking field (``partner_id.name``). The insertion
    is a copy: later changes of the saved block do not touch the reports.
    """

    _name = "rs.block"
    _description = "Report Studio - Reusable Block"
    _order = "name"

    name = fields.Char(required=True)
    model_name = fields.Char(
        string="Model",
        required=True,
        help="Model of the block data (e.g. res.partner); field paths are "
        "relative to it.",
    )
    model_description = fields.Char(
        compute="_compute_model_description", string="Model Description"
    )
    definition = fields.Text(required=True, help="JSON of the block.")
    block_type = fields.Char(compute="_compute_block_type", string="Block Type")
    user_id = fields.Many2one(
        "res.users", string="Author", default=lambda self: self.env.user, readonly=True
    )

    @api.depends("model_name")
    def _compute_model_description(self):
        for block in self:
            model = self.env["ir.model"].sudo()._get(block.model_name)
            block.model_description = model.name if model else block.model_name

    @api.depends("definition")
    def _compute_block_type(self):
        for block in self:
            try:
                block.block_type = json.loads(block.definition or "{}").get("type")
            except (TypeError, ValueError):
                block.block_type = False

    def _check_block(self, model_name, block):
        """The block must compile on its model (same rules as the reports)."""
        if model_name not in self.env:
            raise UserError(self.env._("Model %s not found.", model_name))
        self.env[model_name].check_access("read")
        if not isinstance(block, dict) or block.get("type") in (None, "column"):
            raise UserError(self.env._("This block cannot be saved as a reusable block."))
        report = self.env["rs.report"]
        try:
            compile_templates(
                {"children": [block]},
                model_name,
                "report_studio.rs_block_check",
                resolver=report._resolve_field,
                gettext=report._gettext,
            )
        except CompileError as exc:
            raise UserError(
                self.env._(
                    "Invalid block: %s",
                    exc.translate(report._gettext),
                )
            ) from exc

    @api.model
    def create_from_editor(self, name, model_name, block):
        """Save a block of the editor; paths already relative to model_name."""
        if isinstance(block, str):
            block = json.loads(block)
        if not (name or "").strip():
            raise UserError(self.env._("Enter the name of the block."))
        self._check_block(model_name, block)
        return self.create(
            {"name": name.strip(), "model_name": model_name, "definition": json.dumps(block)}
        ).id

    @api.model
    def get_for_model(self, report_model):
        """Blocks usable in a report of report_model.

        A block is usable when it is on the same model, or when the report
        model has many2one fields to the block model ("links").
        """
        if report_model not in self.env:
            return []
        fields_info = self.env[report_model].fields_get(
            attributes=["type", "relation", "string"]
        )
        result = []
        for block in self.search([]):
            links = sorted(
                (
                    {"name": name, "string": info.get("string") or name}
                    for name, info in fields_info.items()
                    if info["type"] == "many2one"
                    and info.get("relation") == block.model_name
                ),
                key=lambda link: link["string"],
            )
            same_model = block.model_name == report_model
            if not same_model and not links:
                continue
            result.append(
                {
                    "id": block.id,
                    "name": block.name,
                    "model": block.model_name,
                    "type": block.block_type,
                    "same_model": same_model,
                    "links": links,
                    "definition": json.loads(block.definition),
                }
            )
        return result
