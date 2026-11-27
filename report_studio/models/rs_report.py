# -*- coding: utf-8 -*-
import json
import uuid
from contextlib import contextmanager

from odoo import _, api, fields, models
from odoo.addons.base.models.ir_qweb import QWebException
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import test_python_expr

from ..lib.compiler import CompileError, compile_definition

EMPTY_DEFINITION = json.dumps({"children": []})


def _is_qweb_definition(definition):
    """True se la definizione (stringa JSON) è in modalità QWeb libero."""
    try:
        parsed = json.loads(definition)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("mode") == "qweb"


class RsReport(models.Model):
    """Report disegnato con Report Studio.

    Il record contiene l'identità del report, il modello Odoo di riferimento,
    l'azione di stampa collegata e il puntatore alla versione attiva.
    Il contenuto vive nelle versioni (rs.report.version): in modalità a blocchi
    è una definizione JSON, in modalità QWeb libero è un template QWeb.

    Nota sui permessi: gli utenti normali non possono leggere ir.model,
    ir.model.fields e ir.ui.view. Per questo il nome tecnico del modello è
    memorizzato in ``model_name`` e l'editor usa get_model_options() e
    get_model_fields() invece di leggere quei modelli direttamente.
    """

    _name = "rs.report"
    _description = "Report Studio - Report"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    report_mode = fields.Selection(
        [("blocks", "Blocchi"), ("qweb", "QWeb libero")],
        default="blocks",
        required=True,
        string="Modalità",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Modello Odoo",
        required=True,
        ondelete="cascade",
        help="Modello su cui il report viene eseguito (es. sale.order).",
    )
    model_name = fields.Char(
        related="model_id.model",
        store=True,
        readonly=True,
        index=True,
        string="Modello tecnico",
    )
    action_id = fields.Many2one(
        "ir.actions.report",
        string="Azione di stampa",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    report_key = fields.Char(
        related="action_id.report_name", string="Nome tecnico del template",
    )

    # ----- stampa (pagina Report) -----
    # Copiati sull'azione di stampa (ir.actions.report) a ogni modifica: gli
    # editor non hanno accesso in scrittura alle azioni, il modulo le aggiorna
    # in sudo solo per i report che gestisce.
    in_print_menu = fields.Boolean(
        string="Nel menu Stampa",
        copy=False,
        help="Il report compare nel menu Stampa del suo modello (es. dalla fattura). "
             "Un report archiviato non compare comunque.",
    )
    print_name = fields.Char(
        string="Nome nel menu Stampa",
        help="Voce nel menu Stampa. Vuoto: il nome del report.",
    )
    paperformat_id = fields.Many2one("report.paperformat", string="Formato carta")
    print_report_name = fields.Char(
        string="Nome del file stampato",
        help="Espressione Python per il nome del PDF, con il record in 'object'. "
             "Es.: 'Fattura - %s' % object.name",
    )
    attachment_use = fields.Boolean(
        string="Riusa l'allegato alla ristampa",
        help="Se il PDF è già stato salvato come allegato, la ristampa usa quello.",
    )
    attachment = fields.Char(
        string="Salva come allegato",
        help="Espressione Python per il nome dell'allegato; vuoto: non salvato. "
             "Es.: (object.name + '.pdf')",
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

    # ----- ciclo di vita -----

    @api.model_create_multi
    def create(self, vals_list):
        reports = super().create(vals_list)
        definition = self.env.context.get("rs_initial_definition") or EMPTY_DEFINITION
        comment = self.env.context.get("rs_initial_comment") or _("Versione iniziale")
        for report in reports:
            report._create_version(definition, comment=comment)
        return reports

    # Campi del report che finiscono sull'azione di stampa.
    _PRINT_FIELDS = (
        "name", "active", "in_print_menu", "print_name", "paperformat_id",
        "print_report_name", "attachment_use", "attachment",
    )

    def _print_action_vals(self):
        """Valori dell'azione di stampa. Nel menu Stampa solo se attivo e aggiunto."""
        self.ensure_one()
        return {
            "name": self.print_name or self.name,
            "binding_model_id": self.model_id.id if self.active and self.in_print_menu else False,
            "paperformat_id": self.paperformat_id.id,
            "print_report_name": self.print_report_name or False,
            "attachment_use": self.attachment_use,
            "attachment": self.attachment or False,
        }

    @api.constrains("print_report_name", "attachment")
    def _check_print_expressions(self):
        for report in self:
            for field in ("print_report_name", "attachment"):
                expr = report[field]
                message = expr and test_python_expr(expr.strip(), mode="eval")
                if message:
                    raise ValidationError(_("%(field)s: espressione non valida.\n%(error)s",
                                            field=report._fields[field].string, error=message))

    def write(self, vals):
        result = super().write(vals)
        if any(key in vals for key in self._PRINT_FIELDS):
            for report in self.filtered("action_id"):
                report.action_id.sudo().write(report._print_action_vals())
        return result

    def action_add_print_menu(self):
        """Pulsante "Aggiungi al menu Stampa" (pagina Report)."""
        self.check_access("write")
        if self.filtered(lambda r: not r.active):
            raise UserError(_("Un report archiviato non può stare nel menu Stampa: riattivalo prima."))
        self.write({"in_print_menu": True})
        return True

    def action_remove_print_menu(self):
        """Pulsante "Rimuovi dal menu Stampa" (pagina Report)."""
        self.check_access("write")
        self.write({"in_print_menu": False})
        return True

    def unlink(self):
        """Elimina anche viste QWeb e azioni di stampa generate dal report.

        Le versioni vengono eliminate dal database (ondelete cascade) senza
        passare da rs.report.version.unlink(), che le protegge dall'eliminazione
        singola.
        """
        reports = self.sudo()
        views = reports.version_ids.view_id
        actions = reports.action_id
        result = super().unlink()
        views.exists().unlink()
        actions.exists().unlink()
        return result

    # ----- permessi -----

    def _check_model_access(self):
        """L'utente può lavorare sui report solo dei modelli che può leggere."""
        self.ensure_one()
        self.env[self.model_name].check_access("read")

    def _can_edit_qweb(self):
        """Il QWeb libero può eseguire codice sul server: solo gli Amministratori."""
        return (
            self.env.user.has_group("report_studio.group_rs_manager")
            or self.env.user.has_group("base.group_system")
        )

    def _check_definition_permission(self, definition):
        if _is_qweb_definition(definition) and not self._can_edit_qweb():
            raise UserError(_("Solo gli Amministratori di Report Studio possono modificare il QWeb libero."))

    # ----- compilazione, viste e azione di stampa -----

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

    def _compile(self, definition, report_key, annotate=False):
        """Compila la definizione nel template QWeb; errori come UserError."""
        self.ensure_one()
        try:
            return compile_definition(
                definition, self.model_name, report_key,
                resolver=self._resolve_field, annotate=annotate,
            )
        except CompileError as exc:
            raise UserError(_("Definizione del report non valida: %s") % exc) from exc

    def _create_qweb_view(self, name, key, arch):
        return self.env["ir.ui.view"].sudo().create({
            "name": name,
            "type": "qweb",
            "key": key,
            "arch": arch,
        })

    def _ensure_report_action(self, report_key):
        """Crea l'azione di stampa al primo uso, poi punta sempre alla versione attiva."""
        self.ensure_one()
        if self.action_id:
            self.action_id.sudo().write({"report_name": report_key})
            return
        self.action_id = self.env["ir.actions.report"].sudo().create({
            **self._print_action_vals(),
            "model": self.model_name,
            "report_type": "qweb-pdf",
            "report_name": report_key,
            "binding_type": "report",
        })

    # ----- versioni -----

    def _create_version(self, definition, comment=False):
        """Compila la definizione, crea una nuova versione immutabile e la rende attiva."""
        self.ensure_one()
        self.check_access("write")
        self._check_model_access()
        definition = definition or EMPTY_DEFINITION
        self._check_definition_permission(definition)
        next_no = max(self.version_ids.mapped("version_no"), default=0) + 1
        report_key = "report_studio.rs_report_%s_v%s" % (self.id, next_no)
        arch = self._compile(definition, report_key)
        view = self._create_qweb_view("%s - v%s" % (self.name, next_no), report_key, arch)
        version = self.env["rs.report.version"].create({
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

    def _get_own_version(self, version):
        """Verifica che la versione (record o id) appartenga a questo report."""
        self.ensure_one()
        if isinstance(version, int):
            version = self.env["rs.report.version"].browse(version)
        version = version.exists()
        if not version or version.report_id != self:
            raise UserError(_("La versione non appartiene a questo report."))
        return version

    @contextmanager
    def _temporary_report(self, definition, annotate=False):
        """Vista QWeb e azione di stampa temporanee per una definizione non salvata.

        Restituisce la chiave del template; vista e azione vengono eliminate
        sempre all'uscita, anche in caso di errore.
        """
        self.ensure_one()
        definition = definition or EMPTY_DEFINITION
        self._check_definition_permission(definition)
        key = "report_studio.preview_%s_%s" % (self.id, uuid.uuid4().hex)
        arch = self._compile(definition, key, annotate=annotate)
        view = self._create_qweb_view("%s - anteprima" % self.name, key, arch)
        action = self.env["ir.actions.report"].sudo().create({
            "name": "%s - anteprima" % self.name,
            "model": self.model_name,
            "report_type": "qweb-pdf",
            "report_name": key,
        })
        try:
            yield key
        except QWebException as exc:
            # Permessi e errori utente sollevati durante il rendering arrivano
            # avvolti in QWebException: li riporta come tali al chiamante.
            if isinstance(exc.__cause__, (AccessError, UserError)):
                raise exc.__cause__ from None
            raise
        finally:
            action.unlink()
            view.unlink()

    def _render_preview_pdf(self, definition, res_id):
        """PDF di anteprima da una definizione non ancora salvata.

        Il rendering avviene con l'utente corrente (non in sudo), così rispetta
        i diritti di lettura su record e campi collegati; il chiamante verifica
        comunque i permessi di lettura sul record.
        """
        with self._temporary_report(definition) as key:
            pdf, _fmt = self.env["ir.actions.report"]._render_qweb_pdf(key, res_ids=[res_id])
            return pdf

    def render_canvas(self, definition, res_id):
        """HTML della vista visuale dell'editor per un record.

        È la stessa pagina del PDF (layout aziendale compreso) con i blocchi
        marcati da ``data-rs-path`` per la selezione; i blocchi incompleti
        compaiono come segnaposto invece di generare un errore.
        """
        self.ensure_one()
        self.check_access("read")
        record = self.env[self.model_name].browse(int(res_id)).exists()
        if not record:
            raise UserError(_("Record non trovato."))
        record.check_access("read")
        with self._temporary_report(definition, annotate=True) as key:
            html, _fmt = self.env["ir.actions.report"]._render_qweb_html(key, docids=[record.id])
        return html.decode() if isinstance(html, bytes) else html

    # ----- dati per l'editor -----

    @api.model
    def get_model_options(self):
        """Modelli disponibili per un nuovo report: solo quelli che l'utente può leggere."""
        options = []
        for model in self.env["ir.model"].sudo().search([("transient", "=", False)], order="model"):
            if model.model not in self.env:
                continue
            records = self.env[model.model]
            if records._abstract or not records.has_access("read"):
                continue
            options.append({"model": model.model, "name": model.name})
        return options

    @api.model
    def get_model_fields(self, model_name):
        """Campi di un modello per i suggerimenti dell'editor."""
        if model_name not in self.env:
            raise UserError(_("Modello %s non trovato.") % model_name)
        records = self.env[model_name]
        records.check_access("read")
        info = records.fields_get(attributes=["type", "relation", "string"])
        return [
            {
                "name": name,
                "type": field["type"],
                "relation": field.get("relation") or False,
                "string": field.get("string") or name,
            }
            for name, field in sorted(info.items())
        ]

    @api.model
    def get_source_catalog(self):
        """Documenti di partenza: documenti nativi di Odoo/moduli e report Studio.

        I documenti nativi diventano copie in QWeb libero, modificabili solo
        dagli Amministratori: agli altri ruoli non vengono proposti.
        """
        items = []
        if self._can_edit_qweb():
            actions = self.env["ir.actions.report"].search(
                [("report_type", "=", "qweb-pdf")], order="name"
            )
            for action in actions:
                if not action.model or (action.report_name or "").startswith("report_studio."):
                    continue
                items.append({
                    "key": "action:%s" % action.id,
                    "label": "%s (%s)" % (action.name, action.model),
                    "group": "Documenti Odoo",
                })
        for report in self.search([]):
            items.append({
                "key": "report:%s" % report.id,
                "label": "%s (%s)" % (report.name, report.model_name),
                "group": "Report Studio",
            })
        return items

    # ----- creazione: nuovo report, copia di versione, copia di documento -----

    def _get_model(self, model_name):
        model = self.env["ir.model"]._get(model_name)
        if not model:
            raise UserError(_("Modello %s non trovato.") % model_name)
        return model

    @api.model
    def create_new_report(self, name, model_name):
        """Nuovo report a blocchi, vuoto, sul modello indicato."""
        model = self._get_model(model_name)
        return self.create({"name": name, "model_id": model.id, "report_mode": "blocks"}).id

    @api.model
    def create_from_source(self, name, source_key):
        """Crea un report modificabile da un documento Odoo o da un report Studio."""
        kind, _sep, raw_id = (source_key or "").partition(":")
        if not raw_id.isdigit():
            raise UserError(_("Documento di partenza non valido."))
        if kind == "report":
            source = self.browse(int(raw_id)).exists()
            if not source:
                raise UserError(_("Report di partenza non trovato."))
            definition = source.current_version_id.definition
            model_name = source.model_name
            mode = source.report_mode
            comment = _("Copia da %s") % source.name
        elif kind == "action":
            action = self.env["ir.actions.report"].browse(int(raw_id)).exists()
            if not action:
                raise UserError(_("Documento di partenza non trovato."))
            view = self.env["ir.ui.view"].sudo().search(
                [("key", "=", action.report_name), ("type", "=", "qweb")], limit=1
            )
            if not view:
                raise UserError(_("Template QWeb del documento %s non trovato.") % action.name)
            definition = json.dumps({"mode": "qweb", "arch": view.arch_db})
            model_name = action.model
            mode = "qweb"
            comment = _("Copia del documento Odoo %s") % action.name
        else:
            raise UserError(_("Documento di partenza non valido."))
        model = self._get_model(model_name)
        return self.with_context(
            rs_initial_definition=definition,
            rs_initial_comment=comment,
        ).create({"name": name, "model_id": model.id, "report_mode": mode}).id

    def action_copy_version_to_new_report(self, version, name=None):
        """Crea un nuovo report con la definizione di una versione, senza storico.

        Il nuovo report parte dalla versione 1 e non eredita le versioni
        precedenti dell'originale.
        """
        version = self._get_own_version(version)
        return self.with_context(
            rs_initial_definition=version.definition,
            rs_initial_comment=_("Copia da %s, versione %s") % (self.name, version.version_no),
        ).create({
            "name": name or _("%s (copia)") % self.name,
            "model_id": self.model_id.id,
            "report_mode": self.report_mode,
        })

    def action_restore_version(self, version):
        """Ripristina una versione creando una nuova versione copiata da essa."""
        version = self._get_own_version(version)
        return self._create_version(
            version.definition,
            comment=_("Ripristino dalla versione %s") % version.version_no,
        )

    # ----- metodi pubblici chiamati dall'editor (restituiscono id) -----

    def action_save_version(self, definition, comment=False):
        self.ensure_one()
        return self._create_version(definition, comment=comment).id

    def restore_version_by_id(self, version_id):
        return self.action_restore_version(int(version_id)).id

    def copy_version_by_id(self, version_id, name=None):
        return self.action_copy_version_to_new_report(int(version_id), name=name).id
