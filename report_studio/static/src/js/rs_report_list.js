/** @odoo-module **/
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

// Elenco Saved Layouts: "Nuovo" e il clic su una riga aprono l'editor di
// Report Studio (azione client) invece del form standard. L'editor si apre
// sopra l'elenco (breadcrumb), così tornando indietro ricerca e filtri restano.
function editorAction(name, params) {
    return { type: "ir.actions.client", tag: "report_studio.editor", name, params };
}

export class RsReportListController extends ListController {
    async createRecord() {
        await this.actionService.doAction(editorAction("Nuovo", { new: true }));
    }

    async openRecord(record) {
        await this.actionService.doAction(editorAction(record.data.name, { report_id: record.resId }));
    }
}

registry.category("views").add("rs_report_list", {
    ...listView,
    Controller: RsReportListController,
});
