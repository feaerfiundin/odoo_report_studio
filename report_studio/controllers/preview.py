# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
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
        """PDF preview of a definition (even unsaved) on a real record.

        Parameters (form-encoded, with csrf_token):
          report_id  - id of rs.report
          res_id     - id of the record of the report model
          definition - JSON definition of the blocks

        Errors: JSON {"error": message} with status 400 (data or access
        rights), 404 (missing report or record) or 500 (rendering error).
        """
        env = request.env
        try:
            report_id = int(report_id)
            res_id = int(res_id)
        except (TypeError, ValueError):
            return _error(env._("Invalid parameters"), 400)

        report = env["rs.report"].browse(report_id)
        try:
            if not report.exists():
                return _error(env._("Report not found"), 404)
            report.check_access("read")
            record = env[report.model_name].browse(res_id)
            if not record.exists():
                return _error(env._("Record not found"), 404)
            record.check_access("read")
            pdf = report._render_preview_pdf(definition, record.id)
        except (AccessError, UserError) as exc:
            return _error(str(exc), 400)
        except Exception as exc:  # QWeb or wkhtmltopdf errors: message to the editor
            _logger.exception(
                "Report Studio preview failed (report %s, record %s)", report_id, res_id
            )
            return _error(env._("Error while rendering the preview: %s", exc), 500)

        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", "inline; filename=preview.pdf"),
            ],
        )
