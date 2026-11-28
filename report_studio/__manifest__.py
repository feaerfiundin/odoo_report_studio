# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Report Studio",
    "summary": "Block based visual designer for QWeb/PDF reports, with versioning",
    "version": "18.0.0.3.0",
    "development_status": "Alpha",
    "category": "Reporting",
    "website": "https://github.com/feaerfiundin/odoo_report_studio",
    "author": "feaerfiundin",
    "maintainers": ["feaerfiundin"],
    "license": "AGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/res_groups.xml",
        "security/ir.model.access.csv",
        "views/res_users_views.xml",
        "views/rs_report_views.xml",
        "views/rs_block_views.xml",
        "views/report_studio_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "report_studio/static/src/js/column_widths.js",
            "report_studio/static/src/js/field_selector.js",
            "report_studio/static/src/js/table_style_dialog.js",
            "report_studio/static/src/js/editor_dialogs.js",
            "report_studio/static/src/js/report_studio_app.js",
            "report_studio/static/src/js/rs_report_list.js",
            "report_studio/static/src/xml/report_studio_app.xml",
            "report_studio/static/src/xml/field_selector.xml",
            "report_studio/static/src/xml/editor_dialogs.xml",
            "report_studio/static/src/scss/editor.scss",
        ],
        "web.report_assets_common": [
            "report_studio/static/src/scss/report.scss",
        ],
    },
    "installable": True,
    "application": False,
}
