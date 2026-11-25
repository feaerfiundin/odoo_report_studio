# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _error(message, status):
    return request.make_json_response({"error": message}, status=status)


class ReportStudioPreview(http.Controller):

    @http.route("/report_studio/preview", type="http", auth="user", methods=["POST"])
    def preview(self, report_id, res_id, definition, **kwargs):
        """Anteprima PDF di una definizione (anche non salvata) su un record reale.

        Parametri (form-encoded, con csrf_token):
          report_id  - id di rs.report
          res_id     - id del record del modello del report
          definition - definizione JSON dei blocchi

        Errori: JSON {"error": messaggio} con stato 400 (dati o permessi),
        404 (report o record inesistente) o 500 (errore di rendering).
        """
        try:
            report_id = int(report_id)
            res_id = int(res_id)
        except (TypeError, ValueError):
            return _error("Parametri non validi", 400)

        report = request.env["rs.report"].browse(report_id)
        try:
            if not report.exists():
                return _error("Report non trovato", 404)
            report.check_access("read")
            record = request.env[report.model_name].browse(res_id)
            if not record.exists():
                return _error("Record non trovato", 404)
            record.check_access("read")
            pdf = report._render_preview_pdf(definition, record.id)
        except (AccessError, UserError) as exc:
            return _error(str(exc), 400)
        except Exception as exc:  # errori QWeb o di wkhtmltopdf: messaggio all'editor
            _logger.exception("Anteprima Report Studio non riuscita (report %s, record %s)", report_id, res_id)
            return _error("Errore durante il rendering dell'anteprima: %s" % exc, 500)

        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", "inline; filename=anteprima.pdf"),
            ],
        )
