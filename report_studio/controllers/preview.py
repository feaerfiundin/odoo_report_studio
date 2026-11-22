# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class ReportStudioPreview(http.Controller):

    @http.route("/report_studio/preview", type="http", auth="user", methods=["POST"])
    def preview(self, report_id, res_id, definition, **kwargs):
        """Anteprima PDF di una definizione (anche non salvata) su un record reale.

        Parametri (form-encoded, con csrf_token):
          report_id  - id di rs.report
          res_id     - id del record del modello del report
          definition - definizione JSON dei blocchi
        """
        try:
            report_id = int(report_id)
            res_id = int(res_id)
        except (TypeError, ValueError):
            return request.make_json_response({"error": "Parametri non validi"}, status=400)

        report = request.env["rs.report"].browse(report_id)
        if not report.exists():
            return request.make_json_response({"error": "Report non trovato"}, status=404)

        try:
            report.check_access_rights("read")
            report.check_access_rule("read")

            record = request.env[report.model_id.model].browse(res_id)
            if not record.exists():
                return request.make_json_response({"error": "Record non trovato"}, status=404)
            record.check_access_rights("read")
            record.check_access_rule("read")

            pdf = report._render_preview_pdf(definition, record.id)
        except (AccessError, UserError) as exc:
            return request.make_json_response({"error": str(exc)}, status=400)

        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", "inline; filename=anteprima.pdf"),
            ],
        )
