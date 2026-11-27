/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { _t } from "@web/core/l10n/translation";

// Saved Layouts list: "New" and a click on a row open the Report Studio editor
// (client action) instead of the standard form. The editor opens on top of the
// list (breadcrumb), so search and filters are kept when going back.
function editorAction(name, params) {
    return { type: "ir.actions.client", tag: "report_studio.editor", name, params };
}

export class RsReportListController extends ListController {
    async createRecord() {
        await this.actionService.doAction(editorAction(_t("New Report"), { new: true }));
    }

    async openRecord(record) {
        await this.actionService.doAction(
            editorAction(record.data.name, { report_id: record.resId })
        );
    }
}

registry.category("views").add("rs_report_list", {
    ...listView,
    Controller: RsReportListController,
});
