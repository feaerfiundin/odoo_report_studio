/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const BLOCK_TYPES = [
    ["section", "Sezione"],
    ["text", "Testo"],
    ["field", "Campo"],
    ["table", "Tabella"],
    ["if", "Condizione"],
];

let uidCounter = 0;
const nextUid = () => ++uidCounter;

function defaultBlock(type) {
    const base = { _uid: nextUid(), type };
    switch (type) {
        case "section":
            return { ...base, class: "", children: [] };
        case "text":
            return { ...base, content: "Testo", class: "" };
        case "field":
            return { ...base, path: "" };
        case "table":
            return { ...base, source: "", columns: [{ _uid: nextUid(), path: "", label: "" }] };
        case "if":
            return { ...base, path: "", op: "==", value: "", children: [] };
    }
    return base;
}

// Aggiunge _uid ai blocchi e alle colonne, solo per l'editor.
function withUids(block) {
    const copy = { ...block, _uid: nextUid() };
    if (Array.isArray(block.children)) copy.children = block.children.map(withUids);
    if (Array.isArray(block.columns)) {
        copy.columns = block.columns.map((c) => ({ ...c, _uid: nextUid() }));
    }
    return copy;
}

function parseLiteral(text) {
    if (text === "" || text === null || text === undefined) return null;
    if (text === "true") return true;
    if (text === "false") return false;
    if (text === "null") return null;
    if (!isNaN(Number(text))) return Number(text);
    return String(text);
}

// Toglie gli _uid e normalizza i valori prima dell'invio al server.
function cleanBlock(block) {
    const { _uid, ...rest } = block;
    const out = { ...rest };
    if (Array.isArray(block.children)) out.children = block.children.map(cleanBlock);
    if (Array.isArray(block.columns)) {
        out.columns = block.columns.map(({ _uid: _c, ...col }) => col);
    }
    if (block.type === "if") out.value = parseLiteral(block.value);
    return out;
}

function cleanDefinition(definition) {
    return {
        layout: definition.layout || "external",
        children: definition.children.map(cleanBlock),
    };
}

// Messaggio leggibile da un errore RPC di Odoo (UserError, ValidationError...).
function errorMessage(error, fallback) {
    return error?.data?.message || (typeof error?.message === "string" && error.message) || fallback;
}

function findNode(children, target) {
    for (let index = 0; index < children.length; index++) {
        const node = children[index];
        if (node._uid === target) return { node, list: children, index };
        if (node.children) {
            const found = findNode(node.children, target);
            if (found) return found;
        }
    }
    return null;
}

class BlockNode extends Component {
    static template = "report_studio.BlockNode";
    static props = { node: Object, selectedUid: { type: [Number, { value: null }] }, onSelect: Function };

    setup() {
        // Il nodo viene osservato da questo componente: senza, le modifiche fatte
        // nel pannello Proprietà ridisegnano solo il padre e l'etichetta resta vecchia.
        // L'istanza è legata al nodo dal t-key (_uid), quindi il nodo non cambia.
        this.node = useState(this.props.node);
    }

    get label() {
        const n = this.node;
        switch (n.type) {
            case "section":
                return "Sezione";
            case "text":
                return `Testo: ${n.content}`;
            case "field":
                return `Campo: ${n.path}`;
            case "table":
                return `Tabella: ${n.source}`;
            case "if":
                return `Se ${n.path} ${n.op} ${n.value}`;
        }
        return n.type;
    }

    onClick(ev) {
        ev.stopPropagation();
        this.props.onSelect(this.node._uid);
    }
}
BlockNode.components = { BlockNode };

export class ReportStudioApp extends Component {
    static template = "report_studio.App";
    static components = { BlockNode };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.blockTypes = BLOCK_TYPES;
        this.state = useState({
            // list | new | edit
            view: "list",
            reports: [],
            // nuovo report
            newName: "",
            newModel: "",
            newSource: "",
            models: [],
            sources: [],
            // editor
            reportId: false,
            reportName: "",
            modelName: "",
            mode: "blocks",
            qwebText: "",
            definition: { children: [] },
            selectedUid: null,
            fieldCache: {},
            fields: [],
            versions: [],
            records: [],
            recordId: false,
            comment: "",
            copyName: "",
            previewUrl: null,
            dirty: false,
        });
        onWillStart(async () => {
            await this.loadList();
            const reportId = this.props.action?.params?.report_id;
            if (reportId) {
                await this.openEditor(reportId);
            }
        });
    }

    // ----- elenco -----

    async loadList() {
        this.state.reports = await this.orm.searchRead(
            "rs.report",
            [["active", "=", true]],
            ["name", "model_name", "report_mode", "write_date"],
            { order: "write_date desc" }
        );
    }

    showList() {
        this.state.view = "list";
        this.loadList();
    }

    async onOpenRow(ev) {
        await this.openEditor(parseInt(ev.currentTarget.dataset.id));
    }

    // ----- nuovo report -----

    async openNew() {
        this.state.newName = "";
        this.state.newModel = "";
        this.state.newSource = "";
        this.state.models = await this.orm.call("rs.report", "get_model_options", []);
        this.state.sources = await this.orm.call("rs.report", "get_source_catalog", []);
        this.state.view = "new";
    }

    get nativeSources() {
        return this.state.sources.filter((s) => s.group === "Documenti Odoo");
    }

    get studioSources() {
        return this.state.sources.filter((s) => s.group === "Report Studio");
    }

    onNewSourceChange(ev) {
        this.state.newSource = ev.target.value;
    }

    onOpenVisualEditor() {
        if (!this.state.newName) {
            this.notification.add("Inserisci il nome del report", { type: "warning" });
            return;
        }
        if (this.state.newSource) {
            this.confirmCopy();
        } else {
            this.createNew();
        }
    }

    async createNew() {
        if (!this.state.newModel) {
            this.notification.add("Scegli il modello", { type: "warning" });
            return;
        }
        const newId = await this.orm.call("rs.report", "create_new_report", [], {
            name: this.state.newName,
            model_name: this.state.newModel,
        });
        await this.openEditor(newId);
    }

    confirmCopy() {
        this.dialog.add(ConfirmationDialog, {
            title: "Crea copia editabile",
            body: "Verrà creata una copia modificabile del documento selezionato, con il suo modello. L'originale non verrà modificato. Vuoi continuare?",
            confirmLabel: "Crea copia",
            confirm: async () => {
                const newId = await this.orm.call("rs.report", "create_from_source", [], {
                    name: this.state.newName,
                    source_key: this.state.newSource,
                });
                await this.openEditor(newId);
            },
            cancel: () => {},
        });
    }

    // ----- editor -----

    async openEditor(reportId) {
        await this.selectReport(reportId);
        this.state.view = "edit";
    }

    // Campi di un modello, letti una sola volta e tenuti in cache.
    async fetchFields(model) {
        if (!this.state.fieldCache[model]) {
            this.state.fieldCache[model] = await this.orm.call("rs.report", "get_model_fields", [model]);
        }
        return this.state.fieldCache[model];
    }

    // Carica i campi dei modelli collegati alle tabelle, per suggerire le colonne.
    async loadTableFields(blocks) {
        for (const block of blocks) {
            if (block.type === "table") {
                const relation = this.state.fields.find((f) => f.name === block.source)?.relation;
                if (relation) await this.fetchFields(relation).catch(() => {});
            }
            if (block.children) await this.loadTableFields(block.children);
        }
    }

    async loadVersions() {
        this.state.versions = await this.orm.searchRead(
            "rs.report.version",
            [["report_id", "=", this.state.reportId]],
            ["version_no", "comment", "is_active", "user_id"],
            { order: "version_no desc" }
        );
    }

    async loadRecords() {
        try {
            this.state.records = await this.orm.searchRead(
                this.state.modelName, [], ["display_name"], { limit: 50 }
            );
        } catch (error) {
            this.state.records = [];
        }
        if (!this.state.records.find((r) => r.id === this.state.recordId)) {
            this.state.recordId = this.state.records.length ? this.state.records[0].id : false;
        }
    }

    async selectReport(reportId) {
        const [report] = await this.orm.read(
            "rs.report", [reportId], ["name", "model_name", "current_version_id", "report_mode"]
        );
        this.state.reportId = reportId;
        this.state.reportName = report.name;
        this.state.modelName = report.model_name;
        this.state.mode = report.report_mode;
        this.state.fields = await this.fetchFields(report.model_name);
        await this.loadVersions();
        const [version] = await this.orm.read(
            "rs.report.version", [report.current_version_id[0]], ["definition"]
        );
        const parsed = JSON.parse(version.definition);
        if (parsed.mode === "qweb") {
            this.state.mode = "qweb";
            this.state.qwebText = parsed.arch || "";
            this.state.definition = { children: [] };
        } else {
            this.state.definition = {
                layout: parsed.layout,
                children: (parsed.children || []).map(withUids),
            };
            await this.loadTableFields(this.state.definition.children);
        }
        this.state.selectedUid = null;
        this.state.previewUrl = null;
        this.state.dirty = false;
        await this.loadRecords();
    }

    backToList() {
        this.state.view = "list";
        this.state.previewUrl = null;
        this.loadList();
    }

    currentDefinitionJson() {
        if (this.state.mode === "qweb") {
            return JSON.stringify({ mode: "qweb", arch: this.state.qwebText });
        }
        return JSON.stringify(cleanDefinition(this.state.definition));
    }

    get selected() {
        if (!this.state.selectedUid) return null;
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        return found ? found.node : null;
    }

    get tableColumnFields() {
        const sel = this.selected;
        if (!sel || sel.type !== "table") return [];
        const sourceField = this.state.fields.find((f) => f.name === sel.source);
        if (!sourceField || !sourceField.relation) return [];
        return this.state.fieldCache[sourceField.relation] || [];
    }

    selectBlock(uid) {
        this.state.selectedUid = uid;
    }

    markDirty() {
        this.state.dirty = true;
    }

    onAddBlock(ev) {
        const type = ev.currentTarget.dataset.type;
        const block = defaultBlock(type);
        let target = this.state.definition.children;
        const sel = this.selected;
        if (sel) {
            target = sel.children ? sel.children : findNode(this.state.definition.children, sel._uid).list;
        }
        target.push(block);
        this.state.selectedUid = block._uid;
        this.markDirty();
    }

    onTableSourceChange(ev) {
        const sel = this.selected;
        if (!sel) return;
        sel.source = ev.target.value;
        const field = this.state.fields.find((f) => f.name === sel.source);
        if (field && field.relation) {
            this.fetchFields(field.relation).catch(() => {});
        }
        this.markDirty();
    }

    onAddColumn() {
        const sel = this.selected;
        if (!sel || sel.type !== "table") return;
        sel.columns.push({ _uid: nextUid(), path: "", label: "" });
        this.markDirty();
    }

    onRemoveColumn(ev) {
        const sel = this.selected;
        if (!sel || sel.type !== "table") return;
        const uid = parseInt(ev.currentTarget.dataset.uid);
        sel.columns = sel.columns.filter((c) => c._uid !== uid);
        this.markDirty();
    }

    onMove(ev) {
        const direction = parseInt(ev.currentTarget.dataset.dir);
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        if (!found) return;
        const target = found.index + direction;
        if (target < 0 || target >= found.list.length) return;
        [found.list[found.index], found.list[target]] = [found.list[target], found.list[found.index]];
        this.markDirty();
    }

    onDelete() {
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        if (!found) return;
        found.list.splice(found.index, 1);
        this.state.selectedUid = null;
        this.markDirty();
    }

    async onRecordChange(ev) {
        this.state.recordId = parseInt(ev.target.value);
    }

    async saveVersion() {
        try {
            await this.orm.call("rs.report", "action_save_version", [[this.state.reportId]], {
                definition: this.currentDefinitionJson(),
                comment: this.state.comment || false,
            });
            this.state.comment = "";
            this.state.dirty = false;
            await this.loadVersions();
            this.notification.add("Versione salvata", { type: "success" });
        } catch (error) {
            this.notification.add(errorMessage(error, "Salvataggio non riuscito"), { type: "danger" });
        }
    }

    async preview() {
        const body = new FormData();
        body.append("report_id", this.state.reportId);
        body.append("res_id", this.state.recordId);
        body.append("definition", this.currentDefinitionJson());
        body.append("csrf_token", odoo.csrf_token);
        const response = await fetch("/report_studio/preview", { method: "POST", body });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            this.notification.add(err.error || "Anteprima non riuscita", { type: "danger" });
            return;
        }
        const blob = await response.blob();
        if (this.state.previewUrl) URL.revokeObjectURL(this.state.previewUrl);
        this.state.previewUrl = URL.createObjectURL(blob);
    }

    async restoreVersion(ev) {
        const versionId = parseInt(ev.currentTarget.dataset.id);
        await this.orm.call("rs.report", "restore_version_by_id", [[this.state.reportId], versionId]);
        await this.selectReport(this.state.reportId);
        this.notification.add("Versione ripristinata come nuova versione", { type: "success" });
    }

    async copyVersion(ev) {
        const versionId = parseInt(ev.currentTarget.dataset.id);
        const name = this.state.copyName || `${this.state.reportName} (copia)`;
        const newId = await this.orm.call(
            "rs.report", "copy_version_by_id", [[this.state.reportId], versionId, name]
        );
        this.state.copyName = "";
        await this.openEditor(newId);
        this.notification.add("Nuovo report creato dalla copia", { type: "success" });
    }

    async archiveReport() {
        await this.orm.write("rs.report", [this.state.reportId], { active: false });
        this.notification.add("Report archiviato", { type: "info" });
        this.backToList();
    }
}

registry.category("actions").add("report_studio.editor", ReportStudioApp);
