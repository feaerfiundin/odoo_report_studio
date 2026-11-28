# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import json
import uuid
from contextlib import contextmanager

from odoo import api, fields, models
from odoo.addons.base.models.ir_qweb import QWebException
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import test_python_expr

from ..lib.compiler import CompileError, compile_templates

EMPTY_DEFINITION = json.dumps({"children": []})


def _is_qweb_definition(definition):
    """True when the definition (JSON string) is in free QWeb mode."""
    try:
        parsed = json.loads(definition)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("mode") == "qweb"


class RsReport(models.Model):
    """Report designed with Report Studio.

    The record holds the identity of the report, the Odoo model it runs on,
    the linked print action and the pointer to the active version. The
    content lives in the versions (rs.report.version): a JSON definition in
    blocks mode, a QWeb template in free QWeb mode.

    Note on access rights: regular users cannot read ir.model,
    ir.model.fields and ir.ui.view. That is why the technical name of the
    model is stored in ``model_name`` and the editor uses
    get_model_options() and get_model_fields() instead of reading those
    models directly.
    """

    _name = "rs.report"
    _description = "Report Studio - Report"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    report_mode = fields.Selection(
        [("blocks", "Blocks"), ("qweb", "Free QWeb")],
        default="blocks",
        required=True,
        string="Mode",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        required=True,
        ondelete="cascade",
        help="Model the report runs on (e.g. sale.order).",
    )
    model_name = fields.Char(
        related="model_id.model",
        store=True,
        readonly=True,
        index=True,
        string="Technical Model Name",
    )
    action_id = fields.Many2one(
        "ir.actions.report",
        string="Print Action",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    report_key = fields.Char(
        related="action_id.report_name",
        string="Template Technical Name",
    )

    # ----- printing (Reports page) -----
    # Copied to the print action (ir.actions.report) on every change: editors
    # have no write access to actions, the module updates them in sudo, only
    # for the reports it manages.
    in_print_menu = fields.Boolean(
        string="In Print Menu",
        copy=False,
        help="The report is listed in the Print menu of its model (e.g. on the "
        "invoice). An archived report is never listed.",
    )
    print_name = fields.Char(
        string="Print Menu Name",
        help="Entry in the Print menu. Empty: the report name.",
    )
    paperformat_id = fields.Many2one("report.paperformat", string="Paper Format")
    print_report_name = fields.Char(
        string="Printed Report Name",
        help="Python expression for the PDF file name, with the record in "
        "'object'. E.g.: 'Invoice - %s' % object.name",
    )
    attachment_use = fields.Boolean(
        string="Reload from Attachment",
        help="When the PDF was already saved as an attachment, printing again "
        "uses it.",
    )
    attachment = fields.Char(
        string="Save as Attachment",
        help="Python expression for the attachment name; empty: not saved. "
        "E.g.: (object.name + '.pdf')",
    )

    version_ids = fields.One2many(
        "rs.report.version", "report_id", string="Versions"
    )
    current_version_id = fields.Many2one(
        "rs.report.version",
        string="Active Version",
        copy=False,
    )
    # Work in progress saved without a new version: the editor opens it, the
    # print action keeps using the active version.
    draft_definition = fields.Text(copy=False)
    draft_comment = fields.Char(copy=False)
    version_count = fields.Integer(
        compute="_compute_version_count", string="Number of Versions"
    )

    @api.depends("version_ids")
    def _compute_version_count(self):
        for report in self:
            report.version_count = len(report.version_ids)

    # ----- life cycle -----

    @api.model_create_multi
    def create(self, vals_list):
        reports = super().create(vals_list)
        definition = self.env.context.get("rs_initial_definition") or EMPTY_DEFINITION
        comment = self.env.context.get("rs_initial_comment") or self.env._("Initial version")
        for report in reports:
            report._create_version(definition, comment=comment)
        return reports

    # Report fields copied to the print action.
    _PRINT_FIELDS = (
        "name",
        "active",
        "in_print_menu",
        "print_name",
        "paperformat_id",
        "print_report_name",
        "attachment_use",
        "attachment",
    )

    def _print_action_vals(self):
        """Print action values. In the Print menu only when active and added."""
        self.ensure_one()
        return {
            "name": self.print_name or self.name,
            "binding_model_id": self.model_id.id
            if self.active and self.in_print_menu
            else False,
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
                    raise ValidationError(
                        self.env._(
                            "%(field)s: invalid expression.\n%(error)s",
                            field=report._fields[field]._description_string(self.env),
                            error=message,
                        )
                    )

    def write(self, vals):
        result = super().write(vals)
        if any(key in vals for key in self._PRINT_FIELDS):
            for report in self.filtered("action_id"):
                report.action_id.sudo().write(report._print_action_vals())
        return result

    def action_add_print_menu(self):
        """Button "Add to Print Menu" (Reports page)."""
        self.check_access("write")
        if self.filtered(lambda r: not r.active):
            raise UserError(
                self.env._(
                    "An archived report cannot be in the Print menu: "
                    "restore it first."
                )
            )
        self.write({"in_print_menu": True})
        return True

    def action_remove_print_menu(self):
        """Button "Remove from Print Menu" (Reports page)."""
        self.check_access("write")
        self.write({"in_print_menu": False})
        return True

    def unlink(self):
        """Also delete the QWeb views and print actions generated by the report.

        Versions are deleted by the database (ondelete cascade) without going
        through rs.report.version.unlink(), which protects them from being
        deleted one by one.
        """
        reports = self.sudo()
        views = reports.version_ids.view_id | reports.version_ids.document_view_id
        actions = reports.action_id
        result = super().unlink()
        views.exists().unlink()
        actions.exists().unlink()
        return result

    # ----- access rights -----

    def _check_model_access(self):
        """Users can only work on reports of models they can read."""
        self.ensure_one()
        self.env[self.model_name].check_access("read")

    def _can_edit_qweb(self):
        """Free QWeb can run code on the server: Administrators only."""
        return (
            self.env.user.has_group("report_studio.group_rs_manager")
            or self.env.user.has_group("base.group_system")
        )

    def _check_definition_permission(self, definition):
        if _is_qweb_definition(definition) and not self._can_edit_qweb():
            raise UserError(
                self.env._("Only Report Studio Administrators can edit free QWeb.")
            )

    # ----- compilation, views and print action -----

    def _resolve_field(self, model_name, path):
        """Return (type, comodel) for a field path, None when not valid."""
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

    def _gettext(self, text):
        """Translate a compiler message in the user interface language.

        The visual view is rendered in the language being edited
        (``render_canvas``), while its placeholders and errors belong to the
        editor: ``rs_ui_lang`` keeps the language of the user interface.
        """
        ui_lang = self.env.context.get("rs_ui_lang")
        env = self.with_context(lang=ui_lang).env if ui_lang else self.env
        return env._(text)

    def _compile(self, definition, report_key, annotate=False):
        """Compile the definition into QWeb templates [(key, xml)].

        Errors are raised as UserError, in the user language.
        """
        self.ensure_one()
        try:
            return compile_templates(
                definition,
                self.model_name,
                report_key,
                resolver=self._resolve_field,
                annotate=annotate,
                gettext=self._gettext,
            )
        except CompileError as exc:
            raise UserError(
                self.env._(
                    "Invalid report definition: %s", exc.translate(self._gettext)
                )
            ) from exc

    def _create_qweb_views(self, name, templates):
        """One QWeb view per template; the first one is the main one."""
        return [
            self._create_qweb_view(name if index == 0 else "%s - page" % name, key, arch)
            for index, (key, arch) in enumerate(templates)
        ]

    def _create_qweb_view(self, name, key, arch):
        return (
            self.env["ir.ui.view"]
            .sudo()
            .create(
                {
                    "name": name,
                    "type": "qweb",
                    "key": key,
                    "arch": arch,
                }
            )
        )

    def _ensure_report_action(self, report_key):
        """Create the print action on first use, then point it to the active version."""
        self.ensure_one()
        if self.action_id:
            self.action_id.sudo().write({"report_name": report_key})
            return
        self.action_id = (
            self.env["ir.actions.report"]
            .sudo()
            .create(
                {
                    **self._print_action_vals(),
                    "model": self.model_name,
                    "report_type": "qweb-pdf",
                    "report_name": report_key,
                    "binding_type": "report",
                }
            )
        )

    # ----- versions -----

    def _create_version(self, definition, comment=False):
        """Compile the definition, create a new immutable version and activate it."""
        self.ensure_one()
        self.check_access("write")
        self._check_model_access()
        definition = definition or EMPTY_DEFINITION
        self._check_definition_permission(definition)
        next_no = max(self.version_ids.mapped("version_no"), default=0) + 1
        report_key = "report_studio.rs_report_%s_v%s" % (self.id, next_no)
        templates = self._compile(definition, report_key)
        views = self._create_qweb_views("%s - v%s" % (self.name, next_no), templates)
        version = self.env["rs.report.version"].create(
            {
                "report_id": self.id,
                "version_no": next_no,
                "definition": definition,
                "comment": comment,
                "arch": "\n".join(arch for _key, arch in templates),
                "view_id": views[0].id,
                "document_view_id": views[1].id if len(views) > 1 else False,
            }
        )
        self.current_version_id = version
        self._ensure_report_action(report_key)
        return version

    def _get_own_version(self, version):
        """Check that the version (record or id) belongs to this report."""
        self.ensure_one()
        if isinstance(version, int):
            version = self.env["rs.report.version"].browse(version)
        version = version.exists()
        if not version or version.report_id != self:
            raise UserError(self.env._("The version does not belong to this report."))
        return version

    @contextmanager
    def _temporary_report(self, definition, annotate=False):
        """Temporary QWeb views and print action for an unsaved definition.

        Yield the template key; views and action are always deleted on exit,
        errors included.
        """
        self.ensure_one()
        definition = definition or EMPTY_DEFINITION
        self._check_definition_permission(definition)
        key = "report_studio.preview_%s_%s" % (self.id, uuid.uuid4().hex)
        templates = self._compile(definition, key, annotate=annotate)
        views = self._create_qweb_views("%s - preview" % self.name, templates)
        action = (
            self.env["ir.actions.report"]
            .sudo()
            .create(
                {
                    "name": "%s - preview" % self.name,
                    "model": self.model_name,
                    "report_type": "qweb-pdf",
                    "report_name": key,
                }
            )
        )
        try:
            yield key
        except QWebException as exc:
            # Access and user errors raised while rendering come wrapped in a
            # QWebException: give them back to the caller as they are.
            if isinstance(exc.__cause__, AccessError | UserError):
                raise exc.__cause__ from None
            raise
        finally:
            action.unlink()
            for view in reversed(views):
                view.unlink()

    def _render_preview_pdf(self, definition, res_id):
        """Preview PDF from a definition not saved yet.

        Rendering happens with the current user (not in sudo), so it respects
        the read access on the record and related fields; the caller checks
        the read access on the record anyway.
        """
        with self._temporary_report(definition) as key:
            pdf, _fmt = self.env["ir.actions.report"]._render_qweb_pdf(
                key, res_ids=[res_id]
            )
            return pdf

    def render_canvas(self, definition, res_id, lang=None):
        """HTML of the visual view of the editor for a record.

        It is the same page as the PDF (company layout included) with the
        blocks marked by ``data-rs-path`` for selection; incomplete blocks
        are shown as placeholders instead of raising an error. ``lang`` is
        the language being edited: translated texts and Odoo fields are shown
        in that language (active languages only).
        """
        self.ensure_one()
        self.check_access("read")
        if lang and lang in self._active_lang_codes():
            self = self.with_context(lang=lang, rs_ui_lang=self.env.lang)  # noqa: PLW0642
        record = self.env[self.model_name].browse(int(res_id)).exists()
        if not record:
            raise UserError(self.env._("Record not found."))
        record.check_access("read")
        with self._temporary_report(definition, annotate=True) as key:
            html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
                key, docids=[record.id]
            )
        return html.decode() if isinstance(html, bytes) else html

    # ----- languages -----

    def _active_lang_codes(self):
        return [code for code, _name in self.env["res.lang"].get_installed()]

    @api.model
    def _main_lang(self):
        """Main Odoo language: the default one of contacts, then the company
        one, then the first active one."""
        codes = self._active_lang_codes()
        for code in (
            self.env["ir.default"]._get("res.partner", "lang"),
            self.env.company.partner_id.lang,
        ):
            if code in codes:
                return code
        return codes[0] if codes else "en_US"

    @api.model
    def get_languages(self):
        """Languages for the editor: the active ones in Odoo and the main one."""
        return {
            "main": self._main_lang(),
            "langs": [
                {"code": code, "name": name}
                for code, name in self.env["res.lang"].get_installed()
            ],
        }

    # ----- data for the editor -----

    @api.model
    def get_editor_labels(self):
        """Labels of the editor, translated on the server.

        Short common words (Table, Solid, Top...) would get the translation of
        other modules in the web client, where JS translations are global;
        Python translations are per module, so these stay the module's own.
        """
        _ = self.env._
        return {
            "groups": {
                "content": _("Content"),
                "custom": _("Custom Content"),
                "layout": _("Layout"),
            },
            "blocks": {
                "text": _("Text"),
                "field": _("Field"),
                "table": _("Table"),
                "section": _("Section"),
                "columns": _("Columns"),
                "column": _("Column"),
                "if": _("Condition"),
                "separator": _("Separator"),
                "spacer": _("Spacer"),
                "page_break": _("Page Break"),
            },
            "margins": {
                "top": _("Top"),
                "right": _("Right"),
                "bottom": _("Bottom"),
                "left": _("Left"),
            },
            "aligns": {
                "left": _("Left"),
                "center": _("Center"),
                "right": _("Right"),
                "justify": _("Justify"),
            },
            "separators": {
                "solid": _("Solid"),
                "dashed": _("Dashed"),
                "dotted": _("Dotted"),
            },
            "borders": {
                "solid": _("Single"),
                "double": _("Double"),
                "dashed": _("Dashed"),
                "dotted": _("Dotted"),
            },
            "border_presets": {
                "all": _("All"),
                "none": _("No borders"),
                "outer": _("Outer"),
                "horizontal": _("Horizontal lines"),
                "vertical": _("Vertical lines"),
                "header": _("Under the header"),
            },
            "section_positions": {
                "flow": _("In the flow of the page"),
                "header": _("At the top of every page"),
                "footer": _("At the bottom of every page"),
            },
            "width_modes": {
                "full": _("Full width"),
                "percent": _("Percent of the page"),
                "mm": _("Fixed width (mm)"),
            },
            "valigns": {
                "top": _("Top of the cell"),
                "middle": _("Middle of the cell"),
                "bottom": _("Bottom of the cell"),
            },
            # Classes offered by the CSS Class menu of the Section: Bootstrap
            # utilities available in the reports, plus o_rs_keep_together
            # (static/src/scss/report.scss).
            "css_classes": [
                ["small", _("Small text")],
                ["text-muted", _("Grey text")],
                ["fw-bold", _("Bold text")],
                ["fst-italic", _("Italic text")],
                ["text-uppercase", _("Uppercase text")],
                ["bg-light", _("Light grey background")],
                ["rounded", _("Rounded corners")],
                ["p-2", _("Inner spacing")],
                ["mt-3", _("Space above")],
                ["mb-3", _("Space below")],
                ["o_rs_keep_together", _("Do not split across pages")],
            ],
            "soon": {
                "template": _("Template"),
                "saveTemplate": _("Save as Template"),
                "testPrint": _("Test Print"),
                "help": _("Help"),
            },
        }

    @api.model
    def get_model_options(self):
        """Models available for a new report: only those the user can read."""
        options = []
        models_ = self.env["ir.model"].sudo().search(
            [("transient", "=", False)], order="model"
        )
        for model in models_:
            if model.model not in self.env:
                continue
            records = self.env[model.model]
            if records._abstract or not records.has_access("read"):
                continue
            options.append({"model": model.model, "name": model.name})
        return options

    @api.model
    def get_model_fields(self, model_name):
        """Fields of a model for the editor suggestions."""
        if model_name not in self.env:
            raise UserError(self.env._("Model %s not found.", model_name))
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
        """Starting documents: native Odoo/module documents and Studio reports.

        Native documents become free QWeb copies, editable by Administrators
        only: they are not offered to the other roles.
        """
        items = []
        if self._can_edit_qweb():
            actions = self.env["ir.actions.report"].search(
                [("report_type", "=", "qweb-pdf")], order="name"
            )
            for action in actions:
                if not action.model or (action.report_name or "").startswith(
                    "report_studio."
                ):
                    continue
                items.append(
                    {
                        "key": "action:%s" % action.id,
                        "label": "%s (%s)" % (action.name, action.model),
                        "group": self.env._("Odoo Documents"),
                    }
                )
        for report in self.search([]):
            items.append(
                {
                    "key": "report:%s" % report.id,
                    "label": "%s (%s)" % (report.name, report.model_name),
                    "group": "Report Studio",
                }
            )
        return items

    # ----- creation: new report, version copy, document copy -----

    def _get_model(self, model_name):
        model = self.env["ir.model"]._get(model_name)
        if not model:
            raise UserError(self.env._("Model %s not found.", model_name))
        return model

    @api.model
    def create_new_report(self, name, model_name):
        """New empty blocks report on the given model."""
        model = self._get_model(model_name)
        return self.create(
            {"name": name, "model_id": model.id, "report_mode": "blocks"}
        ).id

    @api.model
    def create_from_source(self, name, source_key):
        """Create an editable report from an Odoo document or a Studio report."""
        kind, _sep, raw_id = (source_key or "").partition(":")
        if not raw_id.isdigit():
            raise UserError(self.env._("Invalid starting document."))
        if kind == "report":
            source = self.browse(int(raw_id)).exists()
            if not source:
                raise UserError(self.env._("Starting report not found."))
            definition = source.current_version_id.definition
            model_name = source.model_name
            mode = source.report_mode
            comment = self.env._("Copy of %s", source.name)
        elif kind == "action":
            action = self.env["ir.actions.report"].browse(int(raw_id)).exists()
            if not action:
                raise UserError(self.env._("Starting document not found."))
            view = self.env["ir.ui.view"].sudo().search(
                [("key", "=", action.report_name), ("type", "=", "qweb")], limit=1
            )
            if not view:
                raise UserError(
                    self.env._("QWeb template of document %s not found.", action.name)
                )
            definition = json.dumps({"mode": "qweb", "arch": view.arch_db})
            model_name = action.model
            mode = "qweb"
            comment = self.env._("Copy of Odoo document %s", action.name)
        else:
            raise UserError(self.env._("Invalid starting document."))
        model = self._get_model(model_name)
        return (
            self.with_context(
                rs_initial_definition=definition,
                rs_initial_comment=comment,
            )
            .create({"name": name, "model_id": model.id, "report_mode": mode})
            .id
        )

    def action_copy_version_to_new_report(self, version, name=None):
        """Create a new report from the definition of a version, without history.

        The new report starts from version 1 and does not inherit the earlier
        versions of the original.
        """
        version = self._get_own_version(version)
        return self.with_context(
            rs_initial_definition=version.definition,
            rs_initial_comment=self.env._(
                "Copy of %(name)s, version %(version)s",
                name=self.name,
                version=version.version_no,
            ),
        ).create(
            {
                "name": name or self.env._("%s (copy)", self.name),
                "model_id": self.model_id.id,
                "report_mode": self.report_mode,
            }
        )

    def action_restore_version(self, version):
        """Restore a version by creating a new version copied from it."""
        version = self._get_own_version(version)
        return self._create_version(
            version.definition,
            comment=self.env._("Restored from version %s", version.version_no),
        )

    # ----- public methods called by the editor (they return ids) -----

    def action_save_version(self, definition, comment=False):
        """New version from the editor; the draft, if any, is consumed."""
        self.ensure_one()
        version = self._create_version(definition, comment=comment)
        self.write({"draft_definition": False, "draft_comment": False})
        return version.id

    def save_draft(self, definition, comment=False):
        """Save the work in progress without a new version (not printed)."""
        self.ensure_one()
        self.check_access("write")
        self._check_definition_permission(definition or EMPTY_DEFINITION)
        self.write({"draft_definition": definition, "draft_comment": comment or False})
        return True

    def discard_draft(self):
        self.ensure_one()
        self.check_access("write")
        self.write({"draft_definition": False, "draft_comment": False})
        return True

    def activate_version_by_id(self, version_id):
        """Make an existing version the active (printed) one, without copying it."""
        self.ensure_one()
        self.check_access("write")
        version = self._get_own_version(int(version_id))
        self.current_version_id = version
        self._ensure_report_action(version.view_id.key)
        return version.id

    def delete_version_by_id(self, version_id):
        """Delete an old version (never the active one)."""
        self.ensure_one()
        self.check_access("write")
        self._get_own_version(int(version_id)).unlink()
        return True

    def set_version_comment(self, version_id, comment):
        self.ensure_one()
        self.check_access("write")
        self._get_own_version(int(version_id)).write({"comment": comment or False})
        return True

    def restore_version_by_id(self, version_id):
        return self.action_restore_version(int(version_id)).id

    def copy_version_by_id(self, version_id, name=None):
        return self.action_copy_version_to_new_report(int(version_id), name=name).id
