# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import lxml.html

from odoo import models

# Sections repeated on every page (see lib/compiler.py, section "position").
HEADER_CLASS = "o_rs_page_header"
FOOTER_CLASS = "o_rs_page_footer"
EXTRA_TOP = "data-report-rs-extra-top"
EXTRA_BOTTOM = "data-report-rs-extra-bottom"


def _klass(name):
    return "contains(concat(' ', normalize-space(@class), ' '), ' %s ')" % name


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _prepare_html(self, html, report_model=False):
        """Move the Report Studio sections repeated on every page into the
        header / footer of their document, before Odoo splits the PDF parts.

        wkhtmltopdf draws header and footer on every page: a section at the
        top goes under the company header, one at the bottom above the company
        footer. The page margins grow by the height of these sections
        (see _build_wkhtmltopdf_args).
        """
        raw = html if isinstance(html, bytes) else (html or "").encode()
        if HEADER_CLASS.encode() not in raw and FOOTER_CLASS.encode() not in raw:
            return super()._prepare_html(html, report_model=report_model)
        root = lxml.html.fromstring(raw, parser=lxml.html.HTMLParser(encoding="utf-8"))
        extra_top = extra_bottom = 0.0
        for article in root.xpath("//div[%s]" % _klass("article")):
            top = bottom = 0.0
            # Documents without header/footer (basic layout): one empty pair per
            # document, so Odoo still matches header/footer and document by index.
            header = article.xpath("preceding::div[%s][1]" % _klass("header"))
            footer = article.xpath("following::div[%s][1]" % _klass("footer"))
            for node in article.xpath(".//div[%s]" % _klass(HEADER_CLASS)):
                if not header:
                    header = [lxml.html.Element("div", {"class": "header"})]
                    article.addprevious(header[0])
                node.getparent().remove(node)
                header[0].append(node)
                top += float(node.get("data-rs-height") or 0)
            nodes = article.xpath(".//div[%s]" % _klass(FOOTER_CLASS))
            for node in reversed(nodes):
                if not footer:
                    footer = [lxml.html.Element("div", {"class": "footer"})]
                    article.addnext(footer[0])
                node.getparent().remove(node)
                footer[0].insert(0, node)
                bottom += float(node.get("data-rs-height") or 0)
            extra_top = max(extra_top, top)
            extra_bottom = max(extra_bottom, bottom)
        if extra_top:
            root.set(EXTRA_TOP, "%g" % extra_top)
        if extra_bottom:
            root.set(EXTRA_BOTTOM, "%g" % extra_bottom)
        return super()._prepare_html(
            lxml.html.tostring(root, encoding="utf-8"), report_model=report_model
        )

    def _build_wkhtmltopdf_args(self, *args, **kwargs):
        """Enlarge the top / bottom margins for the repeated sections."""
        command_args = super()._build_wkhtmltopdf_args(*args, **kwargs)
        specific = kwargs.get("specific_paperformat_args")
        if specific is None and len(args) > 2:
            specific = args[2]
        specific = specific or {}
        for flag, key in (("--margin-top", EXTRA_TOP), ("--margin-bottom", EXTRA_BOTTOM)):
            extra = float(specific.get(key) or 0)
            if extra and flag in command_args:
                index = command_args.index(flag) + 1
                command_args[index] = "%g" % (float(command_args[index]) + extra)
        return command_args
