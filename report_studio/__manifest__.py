# -*- coding: utf-8 -*-
{
    "name": "Report Studio",
    "summary": "Editor WYSIWYG a blocchi per report QWeb/PDF in Odoo",
    "version": "18.0.0.1.0",
    "category": "Reporting",
    "author": "feaerfiundin",
    "license": "AGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/res_groups.xml",
        "security/ir.model.access.csv",
        "views/report_studio_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "report_studio/static/src/js/report_studio_editor.js",
            "report_studio/static/src/xml/report_studio_editor.xml",
            "report_studio/static/src/scss/editor.scss",
        ],
    },
    "installable": True,
    "application": False,
}
