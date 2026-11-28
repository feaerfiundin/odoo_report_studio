/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import { Component, useState, useRef, useEffect, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { addColumn, ensureWidths, removeColumn, setWidth, totalWidth } from "./column_widths";
import { FieldSelector } from "./field_selector";
import { TableStyleDialog, cleanTableStyle } from "./table_style_dialog";

// Fields that can be the source of a Table.
const isX2many = (field) => ["one2many", "many2many"].includes(field.type);

// Proposed font sizes (pt); empty = the layout one.
const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36];
// Font properties per block type.
const FONT_KEYS = {
    text: ["font"],
    field: ["label_font", "font"],
    table: ["head_font", "body_font"],
};

// Toolbox (left column), by group. Labels come from the server
// (rs.report.get_editor_labels): see there why.
const BLOCK_GROUPS = [
    {
        key: "content",
        items: [
            { type: "text", icon: "fa-font" },
            { type: "field", icon: "fa-database" },
            { type: "table", icon: "fa-table" },
        ],
    },
    {
        key: "layout",
        items: [
            { type: "section", icon: "fa-square-o" },
            { type: "columns", icon: "fa-columns" },
            { type: "if", icon: "fa-code-fork" },
            { type: "separator", icon: "fa-minus" },
            { type: "spacer", icon: "fa-arrows-v" },
            { type: "page_break", icon: "fa-file-o" },
        ],
    },
];
// Blocks with the 4 inner margins (mm).
const MARGIN_TYPES = ["section", "columns", "column", "table"];
const MARGIN_SIDES = ["top", "right", "bottom", "left"];
const COLUMN_COUNTS = [2, 3, 4];
// Text alignment: empty = as the container (the document is left aligned).
const ALIGN_TYPES = ["text", "field", "section", "columns", "column", "table"];
const ALIGNMENTS = [
    ["left", "fa-align-left"],
    ["center", "fa-align-center"],
    ["right", "fa-align-right"],
    ["justify", "fa-align-justify"],
];

// Optional properties always present in the editor (panel reactivity).
function ensureEditorKeys(block) {
    if (ALIGN_TYPES.includes(block.type) && block.align === undefined) block.align = "";
    for (const column of block.type === "table" ? block.columns || [] : []) {
        if (column.align === undefined) column.align = "";
    }
    return block;
}
const SEPARATOR_STYLES = ["solid", "dashed", "dotted"];
const zeroMargins = () => ({ top: 0, right: 0, bottom: 0, left: 0 });
// Section label (bar on top) and borders: defaults of the editor.
const newSectionTitle = () => ({
    text: "",
    translations: {},
    background: "#e9ecef",
    color: "",
    font: {},
    align: "",
});
const newBorder = () => ({ sides: [], style: "solid", width: 1, color: "#333333" });
const BORDER_STYLES = ["solid", "double", "dashed", "dotted"];
const BORDER_WIDTHS = [1, 2, 3, 4, 5, 6];
// New column: some side margin, so the text does not touch the vertical line.
const newColumn = () => ({
    _uid: nextUid(),
    type: "column",
    align: "",
    margins: { top: 0, right: 2, bottom: 0, left: 2 },
    children: [],
});

// Style injected into the visual view (iframe): outlines, selection, placeholders.
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
            return {
                ...base,
                class: "",
                margins: zeroMargins(),
                title: newSectionTitle(),
                border: newBorder(),
                children: [],
            };
        case "columns":
            return { ...base, divider: false, margins: zeroMargins(), children: [newColumn(), newColumn()] };
        case "separator":
            return { ...base, style: "solid", thickness: 1 };
        case "spacer":
            return { ...base, height: 10 };
        case "page_break":
            return base;
        case "text":
            return { ...base, content: "", class: "", font: {} };
        case "field":
            return { ...base, path: "", label: "", label_font: {}, font: {} };
        case "table":
            return {
                ...base,
                source: "",
                head_font: {},
                body_font: {},
                margins: zeroMargins(),
                columns: [{ _uid: nextUid(), path: "", label: "", width: 100, locked: false }],
            };
        case "if":
            return { ...base, path: "", op: "==", value: "", children: [] };
    }
    return base;
}

// Add _uid to blocks and columns, for the editor only, and complete the
// blocks saved before the font controls and the column widths existed.
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
    if (block.type === "section") {
        const title = { ...newSectionTitle(), ...(block.title || {}) };
        title.translations = { ...(title.translations || {}) };
        title.font = { ...(title.font || {}) };
        copy.title = title;
        copy.border = { ...newBorder(), ...(block.border || {}) };
        copy.border.sides = [...(copy.border.sides || [])];
    }
    return ensureEditorKeys(copy);
}

// Only the font properties that are set; undefined when none.
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

// Translations {language: text} without the empty ones; undefined when none.
function cleanTranslations(translations) {
    const out = Object.fromEntries(
        Object.entries(translations || {}).filter(([, text]) => typeof text === "string" && text.trim())
    );
    return Object.keys(out).length ? out : undefined;
}

// Translation key of each translatable text: content -> translations,
// label -> label_translations.
const TRANSLATION_KEY = {
    content: "translations",
    label: "label_translations",
    text: "translations",
};

// Languages in which the report has at least one translated text.
function translatedLangs(blocks, found = new Set()) {
    for (const block of blocks) {
        for (const tr of [block.translations, block.label_translations, block.title?.translations,
                          ...(block.columns || []).map((c) => c.label_translations)]) {
            Object.keys(cleanTranslations(tr) || {}).forEach((code) => found.add(code));
        }
        if (block.children) translatedLangs(block.children, found);
    }
    return found;
}

// Remove the _uid and normalize the values before sending to the server.
function cleanBlock(block) {
    const { _uid, ...rest } = block;
    const out = { ...rest };
    if (Array.isArray(block.children)) out.children = block.children.map(cleanBlock);
    if (Array.isArray(block.columns)) {
        out.columns = block.columns.map(({ _uid: _c, ...col }) => {
            if (!col.align) delete col.align;
            if (!col.background) delete col.background;
            if (!col.border_left) delete col.border_left;
            if (!col.border_right) delete col.border_right;
            col.label_translations = cleanTranslations(col.label_translations);
            if (!col.label_translations) delete col.label_translations;
            return col;
        });
    }
    if (block.type === "table") {
        const columnBorders = (block.columns || []).some((c) => c.border_left || c.border_right);
        out.style = cleanTableStyle(block.style, columnBorders);
        if (!out.style) delete out.style;
    }
    for (const key of ["translations", "label_translations"]) {
        if (key in out) {
            out[key] = cleanTranslations(out[key]);
            if (!out[key]) delete out[key];
        }
    }
    if (!out.align) delete out.align;
    if (block.type === "if") out.value = parseLiteral(block.value);
    for (const key of FONT_KEYS[block.type] || []) {
        const font = cleanFont(block[key]);
        if (font) out[key] = font;
        else delete out[key];
    }
    if (block.type === "field" && !block.label?.trim()) delete out.label;
    if (block.type === "section") {
        const title = { ...(block.title || {}) };
        title.translations = cleanTranslations(title.translations);
        title.font = cleanFont(title.font);
        for (const key of ["translations", "font", "background", "color", "align"]) {
            if (!title[key]) delete title[key];
        }
        if (title.text?.trim()) out.title = title;
        else delete out.title;
        if (block.border?.sides?.length) {
            out.border = {
                sides: MARGIN_SIDES.filter((side) => block.border.sides.includes(side)),
                style: block.border.style || "solid",
                width: Number(block.border.width) || 1,
                color: block.border.color || "#333333",
            };
        } else {
            delete out.border;
        }
    }
    if (MARGIN_TYPES.includes(block.type)) {
        const margins = Object.fromEntries(
            MARGIN_SIDES.map((side) => [side, Number(block.margins?.[side]) || 0])
        );
        if (Object.values(margins).some((v) => v)) out.margins = margins;
        else delete out.margins;
    }
    return out;
}

function cleanDefinition(definition) {
    const out = {
        layout: definition.layout || "external",
        children: definition.children.map(cleanBlock),
    };
    if (definition.base_lang) out.base_lang = definition.base_lang;
    if (definition.print_lang?.enabled) {
        out.print_lang = { enabled: true, field: definition.print_lang.field || "partner_id" };
    }
    return out;
}

// Readable message from an Odoo RPC error (UserError, ValidationError...).
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

// PDF preview in a popup, with the choice of the record.
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
            this.state.error = _t("No record available for the preview.");
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
                this.state.error = err.error || _t("Preview failed");
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
    static components = { Dropdown, DropdownItem, FieldSelector };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.fontSizes = FONT_SIZES;
        this.columnCounts = COLUMN_COUNTS;
        this.totalWidth = totalWidth;
        this.canvasRef = useRef("canvas");
        // Field loader for the field selectors (cached per model).
        this.loadFields = (model) => this.fetchFields(model);
        this.isX2many = isX2many;
        this.canvasTimer = null;
        this.state = useState({
            // new | edit (the list is the standard action_rs_report_list view)
            view: "new",
            // new report
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
            // visual view
            canvasHtml: "",
            canvasError: "",
            canvasLoading: false,
            // languages: the one of the base texts (main), the one being edited
            langs: [],
            mainLang: "",
            editLang: "",
        });
        onWillStart(async () => {
            const [editor, system] = await Promise.all([
                user.hasGroup("report_studio.group_rs_editor"),
                user.hasGroup("base.group_system"),
            ]);
            this.state.canWrite = editor || system;
            const [languages, labels] = await Promise.all([
                this.orm.call("rs.report", "get_languages", []),
                this.orm.call("rs.report", "get_editor_labels", []),
            ]);
            this.setLabels(labels);
            this.state.langs = languages.langs;
            this.state.mainLang = languages.main;
            const params = this.props.action?.params || {};
            if (params.report_id) {
                await this.openEditor(params.report_id);
            } else if (params.new) {
                await this.openNew();
            } else {
                // Opened without parameters (old menu, reloaded URL): go to the list.
                this.goToList();
            }
        });
        onWillUnmount(() => clearTimeout(this.canvasTimer));
        // New HTML of the visual view: load it in the iframe keeping the scroll.
        // Also runs when the iframe appears (from "New" to the editor).
        useEffect(
            (html, frame) => {
                if (!frame || !html) return;
                const scroll = frame.contentWindow?.scrollY || 0;
                frame.onload = () => this.setupCanvas(frame, scroll);
                frame.srcdoc = html;
            },
            () => [this.state.canvasHtml, this.canvasRef.el]
        );
        // Selection changed: only update the highlight, without redrawing.
        useEffect(
            () => this.highlightSelection(),
            () => [this.state.selectedUid]
        );
    }

    // Translated labels of toolbox, margins, alignments and separator styles.
    setLabels(labels) {
        this.labels = labels;
        this.blockLabels = labels.blocks;
        this.blockGroups = BLOCK_GROUPS.map((group) => ({
            label: labels.groups[group.key],
            items: group.items.map((item) => ({ ...item, label: labels.blocks[item.type] })),
        }));
        this.marginSides = MARGIN_SIDES.map((side) => [side, labels.margins[side]]);
        this.alignments = ALIGNMENTS.map(([key, icon]) => [key, labels.aligns[key], icon]);
        this.separatorStyles = SEPARATOR_STYLES.map((key) => [key, labels.separators[key]]);
        this.borderStyles = BORDER_STYLES.map((key) => [key, labels.borders[key]]);
        this.borderWidths = BORDER_WIDTHS;
        this.cssPresets = labels.css_classes;
    }

    // ----- list -----

    // Back to the Saved Layouts list: restore the one we came from (with its
    // search, filters and groupings), otherwise open it from scratch.
    async goToList() {
        const stack = this.env.config?.breadcrumbs || [];
        if (stack.length > 1) {
            try {
                await this.action.restore();
                return;
            } catch {
                // no previous controller: open the list from scratch
            }
        }
        await this.action.doAction("report_studio.action_rs_report_list", { clearBreadcrumbs: true });
    }

    showList() {
        return this.goToList();
    }

    // ----- new report -----

    async openNew() {
        this.state.newName = "";
        this.state.newModel = "";
        this.state.newSource = "";
        this.state.models = await this.orm.call("rs.report", "get_model_options", []);
        this.state.sources = await this.orm.call("rs.report", "get_source_catalog", []);
        this.state.view = "new";
    }

    get nativeSources() {
        return this.state.sources.filter((s) => s.key.startsWith("action:"));
    }

    get studioSources() {
        return this.state.sources.filter((s) => s.key.startsWith("report:"));
    }

    onNewSourceChange(ev) {
        this.state.newSource = ev.target.value;
    }

    onOpenVisualEditor() {
        if (!this.state.newName) {
            this.notification.add(_t("Enter the report name"), { type: "warning" });
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
            this.notification.add(_t("Choose the model"), { type: "warning" });
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
            title: _t("Create Editable Copy"),
            body: _t(
                "An editable copy of the selected document will be created, with its model. The original will not be changed. Do you want to continue?"
            ),
            confirmLabel: _t("Create Copy"),
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

    // Fields of a model, read once and cached.
    async fetchFields(model) {
        if (!this.state.fieldCache[model]) {
            this.state.fieldCache[model] = await this.orm.call("rs.report", "get_model_fields", [model]);
        }
        return this.state.fieldCache[model];
    }

    // Load the fields of the models linked to tables, to suggest the columns.
    async loadTableFields(blocks) {
        for (const block of blocks) {
            if (block.type === "table") {
                await this.loadPath(block.source);
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
                // Reports without base language (created before): the main Odoo one.
                base_lang: parsed.base_lang || this.state.mainLang,
                print_lang: { enabled: false, field: "partner_id", ...(parsed.print_lang || {}) },
                children: (parsed.children || []).map(withUids),
            };
            await this.loadTableFields(this.state.definition.children);
        }
        this.state.selectedUid = null;
        this.state.editLang = this.state.definition.base_lang || this.state.mainLang;
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

    // Redraw the page after a pause in the changes (typing does not call the
    // server for every key).
    scheduleCanvas() {
        clearTimeout(this.canvasTimer);
        this.canvasTimer = setTimeout(() => this.refreshCanvas(), CANVAS_DELAY);
    }

    async refreshCanvas() {
        clearTimeout(this.canvasTimer);
        if (this.state.mode === "qweb" || !this.state.reportId) return;
        if (!this.state.recordId) {
            this.state.canvasError = _t(
                "No %s record to show: create one to see the page.",
                this.state.modelName
            );
            return;
        }
        this.state.canvasLoading = true;
        try {
            const html = await this.orm.call(
                "rs.report", "render_canvas",
                [[this.state.reportId], this.currentDefinitionJson(), this.state.recordId, this.state.editLang]
            );
            this.state.canvasError = "";
            this.state.canvasHtml = html;
        } catch (error) {
            this.state.canvasError = errorMessage(error, _t("Unable to draw the page"));
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

    // Position in the tree ("0.2.1") <-> _uid of the block in the editor.
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

    // ----- blocks and properties -----

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

    // Model reached by a dotted path from the report model, from the cached
    // fields ("" when unknown or not loaded yet).
    relationOf(path) {
        let model = this.state.modelName;
        for (const part of (path || "").split(".").filter(Boolean)) {
            const field = (this.state.fieldCache[model] || []).find((f) => f.name === part);
            if (!field?.relation) return "";
            model = field.relation;
        }
        return path ? model : "";
    }

    // Load the fields of every model along a path (for the column suggestions).
    async loadPath(path) {
        let model = this.state.modelName;
        for (const part of (path || "").split(".").filter(Boolean)) {
            const field = (await this.fetchFields(model).catch(() => [])).find((f) => f.name === part);
            if (!field?.relation) return;
            model = field.relation;
            await this.fetchFields(model).catch(() => {});
        }
    }

    // Path chosen in a field selector.
    setPath(target, key, value) {
        target[key] = value;
        this.markDirty();
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
        if (type === "text") {
            block.content = this.labels.blocks.text;
        }
        let target = this.state.definition.children;
        let index = null;
        const sel = this.selected;
        if (sel && sel.children && sel.type !== "columns") {
            target = sel.children; // inside Section, Condition, Column
        } else if (sel) {
            // after the selected block (a Columns block only accepts columns)
            const found = findNode(this.state.definition.children, sel._uid);
            target = found.list;
            index = found.index + 1;
        }
        if (index === null) target.push(block);
        else target.splice(index, 0, block);
        this.state.selectedUid = block._uid;
        this.markDirty();
    }

    async onTableSource(block, value) {
        block.source = value;
        this.markDirty();
        await this.loadPath(value);
    }

    // Popup with backgrounds, borders and row heights of the table.
    openTableStyle() {
        const block = this.selected;
        if (block?.type !== "table") return;
        this.dialog.add(TableStyleDialog, {
            block,
            labels: this.labels,
            onApply: ({ style, columns }) => {
                block.style = style;
                for (const values of columns) {
                    const column = block.columns.find((c) => c._uid === values._uid);
                    if (column) {
                        column.background = values.background;
                        column.border_left = values.border_left;
                        column.border_right = values.border_right;
                    }
                }
                this.markDirty();
            },
        });
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

    // Width in %: the other free columns are recomputed in proportion.
    onColumnWidth(uid, ev) {
        const sel = this.selected;
        const column = sel?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        setWidth(sel.columns, column, ev.target.value);
        ev.target.value = column.width; // show the actual (limited) value
        this.markDirty();
    }

    // Move a column left (-1) or right (+1): it keeps field, label,
    // translations, width, alignment, background and borders.
    moveColumn(uid, direction) {
        const columns = this.selected?.columns;
        const index = columns?.findIndex((c) => c._uid === uid) ?? -1;
        const target = index + direction;
        if (index < 0 || target < 0 || target >= columns.length) return;
        [columns[index], columns[target]] = [columns[target], columns[index]];
        this.markDirty();
    }

    onColumnLock(uid, ev) {
        const column = this.selected?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        column.locked = ev.target.checked;
        this.markDirty();
    }

    // ----- font controls -----

    onFontSize(font, ev) {
        font.size = ev.target.value ? Number(ev.target.value) : null;
        this.markDirty();
    }

    toggleFont(font, key) {
        font[key] = !font[key];
        this.markDirty();
    }

    // Number of columns: the blocks of removed columns move to the last one left.
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

    // Second click on the active button: back to "as the container".
    setAlign(target, value) {
        target.align = target.align === value ? "" : value;
        this.markDirty();
    }

    // ----- languages -----

    get baseLang() {
        return this.state.definition.base_lang || this.state.mainLang;
    }

    get isTranslating() {
        return this.state.editLang && this.state.editLang !== this.baseLang;
    }

    langName(code) {
        return this.state.langs.find((l) => l.code === code)?.name || code;
    }

    langShort(code) {
        return (code || "").split("_")[0].toUpperCase();
    }

    // Language menu entries: active Odoo languages, main and translated marked.
    get langOptions() {
        const translated = translatedLangs(this.state.definition.children);
        return this.state.langs.map((l) => ({
            code: l.code,
            label:
                `${this.langShort(l.code)} - ${l.name}` +
                (l.code === this.baseLang
                    ? " " + _t("(main)")
                    : translated.has(l.code)
                    ? " ✓"
                    : ""),
        }));
    }

    onEditLang(ev) {
        this.state.editLang = ev.target.value;
        this.refreshCanvas();
    }

    // Translatable text (content / label) in the language being edited.
    trValue(obj, key) {
        if (!this.isTranslating) return obj[key] || "";
        return obj[TRANSLATION_KEY[key]]?.[this.state.editLang] || "";
    }

    trPlaceholder(obj, key, fallback = "") {
        return this.isTranslating ? obj[key] || fallback : fallback;
    }

    setTr(obj, key, ev) {
        if (!this.isTranslating) {
            obj[key] = ev.target.value;
        } else {
            const trKey = TRANSLATION_KEY[key];
            obj[trKey] = { ...(obj[trKey] || {}), [this.state.editLang]: ev.target.value };
        }
        this.markDirty();
    }

    // Contact fields (many2one to res.partner) for the customer language.
    get partnerFields() {
        return this.state.fields.filter((f) => f.type === "many2one" && f.relation === "res.partner");
    }

    onPrintLang(ev) {
        this.state.definition.print_lang.enabled = ev.target.checked;
        this.markDirty();
    }

    onPrintLangField(ev) {
        this.state.definition.print_lang.field = ev.target.value;
        this.markDirty();
    }

    setColumnAlign(uid, value) {
        const column = this.selected?.columns?.find((c) => c._uid === uid);
        if (!column) return;
        column.align = value;
        this.markDirty();
    }

    // Actual alignment inherited by a block: the one of the closest container
    // having one, otherwise the document (left).
    inheritedAlign(uid) {
        const path = this.pathOfUid(uid);
        if (!path) return "left";
        const indexes = path.split(".").map(Number);
        let list = this.state.definition.children;
        let align = "left";
        for (const index of indexes.slice(0, -1)) {
            const node = list[index];
            if (node.align) align = node.align;
            list = node.children;
        }
        return align;
    }

    // Actual alignment of the selected table (for the "as the table" columns).
    get tableAlign() {
        const sel = this.selected;
        return sel ? sel.align || this.inheritedAlign(sel._uid) : "left";
    }

    alignIcon(value) {
        return (this.alignments.find((a) => a[0] === value) || this.alignments[0])[2];
    }

    alignLabel(value) {
        return (this.alignments.find((a) => a[0] === value) || this.alignments[0])[1];
    }

    // Title of the alignment button of a table column.
    columnAlignTitle(column) {
        if (column.align) return this.alignLabel(column.align);
        return _t("As the table (%s)", this.alignLabel(this.tableAlign).toLowerCase());
    }

    // Notice shown while translating.
    get translatingNotice() {
        return _t(
            "Translation in %(lang)s: texts, labels and headers are written in this language. When left empty, the text in %(base)s is printed (in grey).",
            { lang: this.langName(this.state.editLang), base: this.langName(this.baseLang) }
        );
    }

    // Placeholders of the translatable inputs.
    get labelPlaceholder() {
        return _t("e.g. Delivery no.:");
    }

    get sectionLabelPlaceholder() {
        return _t("e.g. Customer data");
    }

    get sourceFirstPlaceholder() {
        return _t("choose the source first");
    }

    get columnFieldPlaceholder() {
        return _t("field");
    }

    get columnLabelPlaceholder() {
        return _t("label");
    }

    // Titles of the font control groups.
    get fontTitles() {
        return {
            font: _t("Font"),
            label: _t("Label Font"),
            value: _t("Value Font"),
            head: _t("Header Font"),
            body: _t("Row Font"),
            sectionLabel: _t("Label Font"),
        };
    }

    // Toolbar buttons not available yet.
    get soonButtons() {
        return this.labels.soon;
    }

    // ----- section: label, borders, CSS classes -----

    // Color of the label (background / text); "" = none.
    onTitleColor(title, key, ev) {
        title[key] = ev.target.value;
        this.markDirty();
    }

    clearTitleColor(title, key) {
        title[key] = "";
        this.markDirty();
    }

    // Borders like in a spreadsheet: all, none, or side by side.
    setBorderSides(border, sides) {
        border.sides = [...sides];
        this.markDirty();
    }

    toggleBorderSide(border, side) {
        border.sides = border.sides.includes(side)
            ? border.sides.filter((s) => s !== side)
            : [...border.sides, side];
        this.markDirty();
    }

    onBorder(border, key, ev) {
        border[key] = key === "width" ? Number(ev.target.value) : ev.target.value;
        this.markDirty();
    }

    // Classes written in the CSS Class field, as a list.
    sectionClasses(block) {
        return (block.class || "").split(/\s+/).filter(Boolean);
    }

    cssPresetLabel(cls) {
        return this.cssPresets.find((p) => p[0] === cls)?.[1] || cls;
    }

    // Presets not used yet, for the "Add" menu.
    availableCssPresets(block) {
        const used = this.sectionClasses(block);
        return this.cssPresets.filter((p) => !used.includes(p[0]));
    }

    addCssClass(block, ev) {
        const cls = ev.target.value;
        ev.target.value = "";
        if (!cls) return;
        block.class = [...this.sectionClasses(block), cls].join(" ");
        this.markDirty();
    }

    removeCssClass(block, cls) {
        block.class = this.sectionClasses(block)
            .filter((c) => c !== cls)
            .join(" ");
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

    // ----- top bar -----

    async onToggleActive(ev) {
        const active = ev.target.checked;
        try {
            await this.orm.write("rs.report", [this.state.reportId], { active });
            this.state.active = active;
            this.notification.add(active ? _t("Report restored") : _t("Report archived"), {
                type: "info",
            });
        } catch (error) {
            ev.target.checked = this.state.active;
            this.notification.add(errorMessage(error, _t("Change failed")), { type: "danger" });
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
            this.notification.add(_t("Version saved"), { type: "success" });
        } catch (error) {
            this.notification.add(errorMessage(error, _t("Save failed")), { type: "danger" });
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

    // ----- versions -----

    async restoreVersion(ev) {
        const versionId = parseInt(ev.currentTarget.dataset.id);
        await this.orm.call("rs.report", "restore_version_by_id", [[this.state.reportId], versionId]);
        await this.selectReport(this.state.reportId);
        this.notification.add(_t("Version restored as a new version"), { type: "success" });
    }

    async copyVersion(ev) {
        const versionId = parseInt(ev.currentTarget.dataset.id);
        const name = this.state.copyName || _t("%s (copy)", this.state.reportName);
        const newId = await this.orm.call(
            "rs.report", "copy_version_by_id", [[this.state.reportId], versionId, name]
        );
        this.state.copyName = "";
        await this.openEditor(newId);
        this.notification.add(_t("New report created from the copy"), { type: "success" });
    }
}

registry.category("actions").add("report_studio.editor", ReportStudioApp);
