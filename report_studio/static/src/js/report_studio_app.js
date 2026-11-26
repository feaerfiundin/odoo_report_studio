/** @odoo-module **/
import { Component, useState, useRef, useEffect, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { user } from "@web/core/user";
import { addColumn, ensureWidths, removeColumn, setWidth, totalWidth } from "./column_widths";

// Dimensioni del carattere proposte (pt); vuoto = quella del layout.
const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36];
// Proprietà carattere per tipo di blocco.
const FONT_KEYS = {
    text: ["font"],
    field: ["label_font", "font"],
    table: ["head_font", "body_font"],
};

// Cassetta degli strumenti (colonna sinistra), per gruppi.
const BLOCK_GROUPS = [
    {
        label: "Contenuto",
        items: [
            { type: "text", label: "Testo", icon: "fa-font" },
            { type: "field", label: "Campo", icon: "fa-database" },
            { type: "table", label: "Tabella", icon: "fa-table" },
        ],
    },
    {
        label: "Impaginazione",
        items: [
            { type: "section", label: "Sezione", icon: "fa-square-o" },
            { type: "columns", label: "Colonne", icon: "fa-columns" },
            { type: "if", label: "Condizione", icon: "fa-code-fork" },
            { type: "separator", label: "Separatore", icon: "fa-minus" },
            { type: "spacer", label: "Spaziatore", icon: "fa-arrows-v" },
            { type: "page_break", label: "Interruzione di pagina", icon: "fa-file-o" },
        ],
    },
];
const BLOCK_LABELS = {
    ...Object.fromEntries(BLOCK_GROUPS.flatMap((g) => g.items.map((i) => [i.type, i.label]))),
    column: "Colonna",
};
// Blocchi con i 4 margini interni (mm).
const MARGIN_TYPES = ["section", "columns", "column"];
const MARGIN_SIDES = [
    ["top", "Sopra"],
    ["right", "Destra"],
    ["bottom", "Sotto"],
    ["left", "Sinistra"],
];
const COLUMN_COUNTS = [2, 3, 4];
// Allineamento del testo: vuoto = come il contenitore (il documento è a sinistra).
const ALIGN_TYPES = ["text", "field", "section", "columns", "column", "table"];
const ALIGNMENTS = [
    ["left", "Sinistra", "fa-align-left"],
    ["center", "Centro", "fa-align-center"],
    ["right", "Destra", "fa-align-right"],
    ["justify", "Giustificato", "fa-align-justify"],
];

// Proprietà facoltative sempre presenti nell'editor (reattività dei pannelli).
function ensureEditorKeys(block) {
    if (ALIGN_TYPES.includes(block.type) && block.align === undefined) block.align = "";
    for (const column of block.type === "table" ? block.columns || [] : []) {
        if (column.align === undefined) column.align = "";
    }
    return block;
}
const SEPARATOR_STYLES = [
    ["solid", "Continua"],
    ["dashed", "Tratteggiata"],
    ["dotted", "Puntinata"],
];
const zeroMargins = () => ({ top: 0, right: 0, bottom: 0, left: 0 });
// Nuova colonna: un po' di margine ai lati, così il testo non tocca la riga verticale.
const newColumn = () => ({
    _uid: nextUid(),
    type: "column",
    align: "",
    margins: { top: 0, right: 2, bottom: 0, left: 2 },
    children: [],
});

// Stile iniettato nella vista visuale (iframe): contorni, selezione, segnaposto.
const CANVAS_STYLE = `
[data-rs-path] { cursor: pointer; outline: 1px dashed rgba(113, 75, 103, .25); outline-offset: 2px; }
[data-rs-path]:hover { outline: 1px dashed rgba(113, 75, 103, .8); }
.o_rs_cv_selected, .o_rs_cv_selected:hover { outline: 2px solid #714B67 !important; background: rgba(113, 75, 103, .06); }
span.o_rs_cv_block { display: inline-block; min-width: 1em; }
.o_rs_cv_empty { color: #999; font-style: italic; font-size: 12px; padding: 4px 0; }
.o_rs_cv_invalid { background: #fff3cd; color: #856404; padding: 2px 6px; font-size: 12px; }
.o_rs_cv_if_label { font-size: 11px; color: #714B67; }
.o_rs_cv_if_false { font-size: 11px; color: #999; font-style: italic; }
td.o_rs_cv_column { outline-offset: -2px; }
.o_rs_cv_page_break { border-top: 2px dashed #714B67; color: #714B67; font-size: 11px; text-align: center; }
.o_rs_cv_spacer { background: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(113, 75, 103, .06) 4px, rgba(113, 75, 103, .06) 8px); }
`;

const CANVAS_DELAY = 400;

let uidCounter = 0;
const nextUid = () => ++uidCounter;

function defaultBlock(type) {
    return ensureEditorKeys(baseBlock(type));
}

function baseBlock(type) {
    const base = { _uid: nextUid(), type };
    switch (type) {
        case "section":
            return { ...base, class: "", margins: zeroMargins(), children: [] };
        case "columns":
            return { ...base, divider: false, margins: zeroMargins(), children: [newColumn(), newColumn()] };
        case "separator":
            return { ...base, style: "solid", thickness: 1 };
        case "spacer":
            return { ...base, height: 10 };
        case "page_break":
            return base;
        case "text":
            return { ...base, content: "Testo", class: "", font: {} };
        case "field":
            return { ...base, path: "", label: "", label_font: {}, font: {} };
        case "table":
            return {
                ...base,
                source: "",
                head_font: {},
                body_font: {},
                columns: [{ _uid: nextUid(), path: "", label: "", width: 100, locked: false }],
            };
        case "if":
            return { ...base, path: "", op: "==", value: "", children: [] };
    }
    return base;
}

// Aggiunge _uid ai blocchi e alle colonne, solo per l'editor, e completa i
// blocchi salvati prima dei controlli carattere e delle larghezze.
function withUids(block) {
    const copy = { ...block, _uid: nextUid() };
    if (Array.isArray(block.children)) copy.children = block.children.map(withUids);
    if (Array.isArray(block.columns)) {
        copy.columns = block.columns.map((c) => ({ ...c, _uid: nextUid() }));
        ensureWidths(copy.columns);
    }
    for (const key of FONT_KEYS[block.type] || []) {
        copy[key] = { ...(block[key] || {}) };
    }
    if (block.type === "field" && copy.label === undefined) copy.label = "";
    if (MARGIN_TYPES.includes(block.type)) copy.margins = { ...zeroMargins(), ...(block.margins || {}) };
    return ensureEditorKeys(copy);
}

// Solo le proprietà carattere impostate; undefined se nessuna.
function cleanFont(font) {
    const out = {};
    if (font?.size) out.size = Number(font.size);
    for (const key of ["bold", "italic", "underline"]) {
        if (font?.[key]) out[key] = true;
    }
    return Object.keys(out).length ? out : undefined;
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
        out.columns = block.columns.map(({ _uid: _c, ...col }) => {
            if (!col.align) delete col.align;
            return col;
        });
    }
    if (!out.align) delete out.align;
    if (block.type === "if") out.value = parseLiteral(block.value);
    for (const key of FONT_KEYS[block.type] || []) {
        const font = cleanFont(block[key]);
        if (font) out[key] = font;
        else delete out[key];
    }
    if (block.type === "field" && !block.label?.trim()) delete out.label;
    if (MARGIN_TYPES.includes(block.type)) {
        const margins = Object.fromEntries(
            MARGIN_SIDES.map(([side]) => [side, Number(block.margins?.[side]) || 0])
        );
        if (Object.values(margins).some((v) => v)) out.margins = margins;
        else delete out.margins;
    }
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

// Anteprima PDF in un popup, con la scelta del record.
class PreviewDialog extends Component {
    static template = "report_studio.PreviewDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        reportId: Number,
        definition: String,
        records: Array,
        recordId: [Number, Boolean],
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({ recordId: this.props.recordId, url: null, loading: false, error: "" });
        onWillStart(() => this.load());
        onWillUnmount(() => this.state.url && URL.revokeObjectURL(this.state.url));
    }

    onRecordChange(ev) {
        this.state.recordId = parseInt(ev.target.value);
        this.load();
    }

    async load() {
        if (!this.state.recordId) {
            this.state.error = "Nessun record disponibile per l'anteprima.";
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        const body = new FormData();
        body.append("report_id", this.props.reportId);
        body.append("res_id", this.state.recordId);
        body.append("definition", this.props.definition);
        body.append("csrf_token", odoo.csrf_token);
        try {
            const response = await fetch("/report_studio/preview", { method: "POST", body });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                this.state.error = err.error || "Anteprima non riuscita";
                this.notification.add(this.state.error, { type: "danger" });
                return;
            }
            const blob = await response.blob();
            if (this.state.url) URL.revokeObjectURL(this.state.url);
            this.state.url = URL.createObjectURL(blob);
        } finally {
            this.state.loading = false;
        }
    }
}

export class ReportStudioApp extends Component {
    static template = "report_studio.App";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.blockGroups = BLOCK_GROUPS;
        this.blockLabels = BLOCK_LABELS;
        this.fontSizes = FONT_SIZES;
        this.marginSides = MARGIN_SIDES;
        this.columnCounts = COLUMN_COUNTS;
        this.separatorStyles = SEPARATOR_STYLES;
        this.alignments = ALIGNMENTS;
        this.totalWidth = totalWidth;
        this.canvasRef = useRef("canvas");
        this.canvasTimer = null;
        this.state = useState({
            // new | edit (l'elenco è la vista standard action_rs_report_list)
            view: "new",
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
            active: true,
            canWrite: false,
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
            dirty: false,
            // vista visuale
            canvasHtml: "",
            canvasError: "",
            canvasLoading: false,
        });
        onWillStart(async () => {
            const [editor, system] = await Promise.all([
                user.hasGroup("report_studio.group_rs_editor"),
                user.hasGroup("base.group_system"),
            ]);
            this.state.canWrite = editor || system;
            const params = this.props.action?.params || {};
            if (params.report_id) {
                await this.openEditor(params.report_id);
            } else if (params.new) {
                await this.openNew();
            } else {
                // Aperta senza parametri (vecchio menu, URL ricaricato): va all'elenco.
                this.goToList();
            }
        });
        onWillUnmount(() => clearTimeout(this.canvasTimer));
        // Nuovo HTML della vista visuale: lo carica nell'iframe mantenendo lo scroll.
        // Riparte anche quando l'iframe compare (passaggio da "Nuovo" all'editor).
        useEffect(
            (html, frame) => {
                if (!frame || !html) return;
                const scroll = frame.contentWindow?.scrollY || 0;
                frame.onload = () => this.setupCanvas(frame, scroll);
                frame.srcdoc = html;
            },
            () => [this.state.canvasHtml, this.canvasRef.el]
        );
        // Selezione cambiata: aggiorna solo l'evidenziazione, senza ridisegnare.
        useEffect(
            () => this.highlightSelection(),
            () => [this.state.selectedUid]
        );
    }

    // ----- elenco -----

    // Torna all'elenco Saved Layouts: ripristina quello da cui si è arrivati
    // (con ricerca, filtri e raggruppamenti), altrimenti lo apre da capo.
    async goToList() {
        const stack = this.env.config?.breadcrumbs || [];
        if (stack.length > 1) {
            try {
                await this.action.restore();
                return;
            } catch {
                // nessun controller precedente: apre l'elenco da capo
            }
        }
        await this.action.doAction("report_studio.action_rs_report_list", { clearBreadcrumbs: true });
    }

    showList() {
        return this.goToList();
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
        } catch {
            this.state.records = [];
        }
        if (!this.state.records.find((r) => r.id === this.state.recordId)) {
            this.state.recordId = this.state.records.length ? this.state.records[0].id : false;
        }
    }

    async selectReport(reportId) {
        const [report] = await this.orm.read(
            "rs.report",
            [reportId],
            ["name", "model_name", "current_version_id", "report_mode", "active"],
            { context: { active_test: false } }
        );
        this.state.reportId = reportId;
        this.state.reportName = report.name;
        this.state.modelName = report.model_name;
        this.state.mode = report.report_mode;
        this.state.active = report.active;
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
        this.state.dirty = false;
        await this.loadRecords();
        this.refreshCanvas();
    }

    backToList() {
        return this.showList();
    }

    currentDefinitionJson() {
        if (this.state.mode === "qweb") {
            return JSON.stringify({ mode: "qweb", arch: this.state.qwebText });
        }
        return JSON.stringify(cleanDefinition(this.state.definition));
    }

    // ----- vista visuale -----

    // Ridisegna la pagina dopo una pausa nelle modifiche (le digitazioni non
    // generano una chiamata al server per ogni tasto).
    scheduleCanvas() {
        clearTimeout(this.canvasTimer);
        this.canvasTimer = setTimeout(() => this.refreshCanvas(), CANVAS_DELAY);
    }

    async refreshCanvas() {
        clearTimeout(this.canvasTimer);
        if (this.state.mode === "qweb" || !this.state.reportId) return;
        if (!this.state.recordId) {
            this.state.canvasError = `Nessun record di ${this.state.modelName} da mostrare: creane uno per vedere la pagina.`;
            return;
        }
        this.state.canvasLoading = true;
        try {
            const html = await this.orm.call(
                "rs.report", "render_canvas",
                [[this.state.reportId], this.currentDefinitionJson(), this.state.recordId]
            );
            this.state.canvasError = "";
            this.state.canvasHtml = html;
        } catch (error) {
            this.state.canvasError = errorMessage(error, "Impossibile disegnare la pagina");
        } finally {
            this.state.canvasLoading = false;
        }
    }

    setupCanvas(frame, scroll) {
        const doc = frame.contentDocument;
        if (!doc) return;
        const style = doc.createElement("style");
        style.textContent = CANVAS_STYLE;
        doc.head.appendChild(style);
        doc.addEventListener("click", (ev) => {
            ev.preventDefault();
            const el = ev.target.closest("[data-rs-path]");
            this.state.selectedUid = el ? this.uidAtPath(el.dataset.rsPath) : null;
        });
        frame.contentWindow.scrollTo(0, scroll);
        this.highlightSelection();
    }

    highlightSelection() {
        const doc = this.canvasRef.el?.contentDocument;
        if (!doc) return;
        doc.querySelectorAll(".o_rs_cv_selected").forEach((el) => el.classList.remove("o_rs_cv_selected"));
        const path = this.pathOfUid(this.state.selectedUid);
        if (path !== null) {
            doc.querySelector(`[data-rs-path="${path}"]`)?.classList.add("o_rs_cv_selected");
        }
    }

    // Posizione nell'albero ("0.2.1") <-> _uid del blocco nell'editor.
    uidAtPath(path) {
        let list = this.state.definition.children;
        let node = null;
        for (const index of path.split(".").map(Number)) {
            node = list?.[index];
            if (!node) return null;
            list = node.children;
        }
        return node._uid;
    }

    pathOfUid(uid, children = this.state.definition.children, prefix = "") {
        if (!uid) return null;
        for (let index = 0; index < children.length; index++) {
            const node = children[index];
            const path = prefix ? `${prefix}.${index}` : String(index);
            if (node._uid === uid) return path;
            if (node.children) {
                const found = this.pathOfUid(uid, node.children, path);
                if (found !== null) return found;
            }
        }
        return null;
    }

    // ----- blocchi e proprietà -----

    get selected() {
        if (!this.state.selectedUid) return null;
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        return found ? found.node : null;
    }

    get selectedParentUid() {
        const path = this.pathOfUid(this.state.selectedUid);
        if (!path || !path.includes(".")) return null;
        return this.uidAtPath(path.split(".").slice(0, -1).join("."));
    }

    get tableColumnFields() {
        const sel = this.selected;
        if (!sel || sel.type !== "table") return [];
        const sourceField = this.state.fields.find((f) => f.name === sel.source);
        if (!sourceField || !sourceField.relation) return [];
        return this.state.fieldCache[sourceField.relation] || [];
    }

    selectParent() {
        this.state.selectedUid = this.selectedParentUid;
    }

    markDirty() {
        this.state.dirty = true;
        this.scheduleCanvas();
    }

    onAddBlock(ev) {
        const type = ev.currentTarget.dataset.type;
        const block = defaultBlock(type);
        let target = this.state.definition.children;
        let index = null;
        const sel = this.selected;
        if (sel && sel.children && sel.type !== "columns") {
            target = sel.children; // dentro Sezione, Condizione, Colonna
        } else if (sel) {
            // dopo il blocco selezionato (un blocco Colonne accetta solo colonne)
            const found = findNode(this.state.definition.children, sel._uid);
            target = found.list;
            index = found.index + 1;
        }
        if (index === null) target.push(block);
        else target.splice(index, 0, block);
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
        addColumn(sel.columns, { _uid: nextUid(), path: "", label: "", align: "" });
        this.markDirty();
    }

    onRemoveColumn(ev) {
        const sel = this.selected;
        if (!sel || sel.type !== "table") return;
        const uid = parseInt(ev.currentTarget.dataset.uid);
        const column = sel.columns.find((c) => c._uid === uid);
        if (column) removeColumn(sel.columns, column);
        this.markDirty();
    }

    // Larghezza in %: le altre colonne libere si ricalcolano in proporzione.
    onColumnWidth(uid, ev) {
        const sel = this.selected;
        const column = sel?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        setWidth(sel.columns, column, ev.target.value);
        ev.target.value = column.width; // mostra il valore effettivo (limitato)
        this.markDirty();
    }

    onColumnLock(uid, ev) {
        const column = this.selected?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        column.locked = ev.target.checked;
        this.markDirty();
    }

    // ----- controlli carattere -----

    onFontSize(font, ev) {
        font.size = ev.target.value ? Number(ev.target.value) : null;
        this.markDirty();
    }

    toggleFont(font, key) {
        font[key] = !font[key];
        this.markDirty();
    }

    // Numero di colonne: i blocchi delle colonne tolte passano nell'ultima rimasta.
    onColumnsCount(ev) {
        const sel = this.selected;
        if (!sel || sel.type !== "columns") return;
        const count = parseInt(ev.target.value);
        while (sel.children.length < count) sel.children.push(newColumn());
        if (sel.children.length > count) {
            const removed = sel.children.splice(count);
            sel.children[count - 1].children.push(...removed.flatMap((c) => c.children));
        }
        this.markDirty();
    }

    // Secondo clic sul pulsante attivo: torna a "come il contenitore".
    setAlign(target, value) {
        target.align = target.align === value ? "" : value;
        this.markDirty();
    }

    onColumnAlign(uid, ev) {
        const column = this.selected?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        column.align = ev.target.value;
        this.markDirty();
    }

    onMargin(margins, side, ev) {
        const value = Math.min(Math.max(Number(ev.target.value) || 0, 0), 100);
        margins[side] = value;
        ev.target.value = value;
        this.markDirty();
    }

    onMove(ev) {
        if (this.selected?.type === "column") return;
        const direction = parseInt(ev.currentTarget.dataset.dir);
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        if (!found) return;
        const target = found.index + direction;
        if (target < 0 || target >= found.list.length) return;
        [found.list[found.index], found.list[target]] = [found.list[target], found.list[found.index]];
        this.markDirty();
    }

    onDelete() {
        if (this.selected?.type === "column") return;
        const found = findNode(this.state.definition.children, this.state.selectedUid);
        if (!found) return;
        found.list.splice(found.index, 1);
        this.state.selectedUid = null;
        this.markDirty();
    }

    onRecordChange(ev) {
        this.state.recordId = parseInt(ev.target.value);
        this.refreshCanvas();
    }

    // ----- barra in alto -----

    async onToggleActive(ev) {
        const active = ev.target.checked;
        try {
            await this.orm.write("rs.report", [this.state.reportId], { active });
            this.state.active = active;
            this.notification.add(active ? "Report attivato" : "Report archiviato", { type: "info" });
        } catch (error) {
            ev.target.checked = this.state.active;
            this.notification.add(errorMessage(error, "Modifica non riuscita"), { type: "danger" });
        }
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

    preview() {
        this.dialog.add(PreviewDialog, {
            reportId: this.state.reportId,
            definition: this.currentDefinitionJson(),
            records: this.state.records,
            recordId: this.state.recordId,
        });
    }

    // ----- versioni -----

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
}

registry.category("actions").add("report_studio.editor", ReportStudioApp);
