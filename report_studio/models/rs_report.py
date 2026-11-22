# -*- coding: utf-8 -*-
import json
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib.compiler import CompileError, compile_definition

EMPTY_DEFINITION = json.dumps({"type": "page", "children": []})


class RsReport(models.Model):
    """Report disegnato con Report Studio.

    Il record contiene l'identità del report, il modello Odoo di riferimento,
    l'azione di stampa collegata e il puntatore alla versione attiva.
    Il contenuto vive nelle versioni (rs.report.version), ciascuna con il
    proprio template QWeb.
    """

    _name = "rs.report"
    _description = "Report Studio - Report"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model",
        string="Modello Odoo",
        required=True,
        ondelete="cascade",
        help="Modello su cui il report viene eseguito (es. sale.order).",
    )
    action_id = fields.Many2one(
        "ir.actions.report",
        string="Azione di stampa",
        readonly=True,
        copy=False,
        ondelete="set null",
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

    @api.model_create_multi
    def create(self, vals_list):
        reports = super().create(vals_list)
        for report in reports:
            report._create_version(EMPTY_DEFINITION, comment="Versione iniziale")
        return reports

    def _resolve_field(self, model_name, path):
        """Ritorna (tipo, modello_relazione) per un percorso di campo, None se non valido."""
        current = model_name
        ftype = comodel = None
        parts = path.split(".")
        for index, part in enumerate(parts):
            if current not in self.env:
                return None
            field = self.env[current]._fields.get(part)
            if not field:
                return None
            ftype = field.type
            comodel = field.comodel_name if field.relational else None
            if index < len(parts) - 1:
                if not field.relational:
                    return None
                current = comodel
        return ftype, comodel

    def _ensure_report_action(self, report_key):
        """Crea l'azione di stampa al primo uso, poi punta sempre alla versione attiva."""
        self.ensure_one()
        if self.action_id:
            self.action_id.write({"report_name": report_key})
            return
        action = self.env["ir.actions.report"].create({
            "name": self.name,
            "model": self.model_id.model,
            "report_type": "qweb-pdf",
            "report_name": report_key,
            "binding_model_id": self.model_id.id,
            "binding_type": "report",
        })
        self.action_id = action

    def _create_version(self, definition, comment=False):
        """Compila la definizione, crea una nuova versione immutabile e la rende attiva."""
        self.ensure_one()
        definition = definition or EMPTY_DEFINITION
        next_no = max(self.version_ids.mapped("version_no"), default=0) + 1
        report_key = "report_studio.rs_report_%s_v%s" % (self.id, next_no)
        try:
            arch = compile_definition(
                definition, self.model_id.model, report_key,
                resolver=self._resolve_field,
            )
        except CompileError as exc:
            raise UserError(_("Definizione del report non valida: %s") % exc)

        view = self.env["ir.ui.view"].create({
            "name": "%s - v%s" % (self.name, next_no),
            "type": "qweb",
            "key": report_key,
            "arch": arch,
        })
        version = self.env["rs.report.version"].with_context(
            rs_internal_write=True
        ).create({
            "report_id": self.id,
            "version_no": next_no,
            "definition": definition,
            "comment": comment,
            "arch": arch,
            "view_id": view.id,
        })
        self.current_version_id = version
        self._ensure_report_action(report_key)
        return version

    def _render_preview_pdf(self, definition, res_id):
        """Renderizza un PDF di anteprima da una definizione non ancora salvata.

        Crea vista e azione temporanee e le elimina sempre al termine, anche
        in caso di errore. Il chiamante deve aver già verificato i permessi
        di lettura sul record.
        """
        self.ensure_one()
        key = "report_studio.preview_%s_%s" % (self.id, uuid.uuid4().hex)
        try:
            arch = compile_definition(
                definition or EMPTY_DEFINITION,
                self.model_id.model,
                key,
                resolver=self._resolve_field,
            )
        except CompileError as exc:
            raise UserError(_("Definizione del report non valida: %s") % exc)

        view = self.env["ir.ui.view"].sudo().create({
            "name": "%s - anteprima" % self.name,
            "type": "qweb",
            "key": key,
            "arch": arch,
        })
        action = self.env["ir.actions.report"].sudo().create({
            "name": "%s - anteprima" % self.name,
            "model": self.model_id.model,
            "report_type": "qweb-pdf",
            "report_name": key,
        })
        try:
            pdf, _fmt = action._render_qweb_pdf(key, res_ids=[res_id])
            return pdf
        finally:
            action.unlink()
            view.unlink()

    def action_restore_version(self, version):
        """Ripristina una versione creando una nuova versione copiata da essa."""
        self.ensure_one()
        if version.report_id != self:
            raise UserError(_("La versione non appartiene a questo report."))
        return self._create_version(
            version.definition,
            comment=_("Ripristino dalla versione %s") % version.version_no,
        )
