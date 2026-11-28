/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import { Component, useState, onWillStart } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Number of suggestions before "Search More...", as in Odoo many2one fields.
const SUGGESTIONS = 4;

// Fields matching a search term: name or label, those starting with it first.
function matchFields(fields, term) {
    const needle = (term || "").toLowerCase();
    const scored = [];
    for (const field of fields) {
        const name = field.name.toLowerCase();
        const label = (field.string || "").toLowerCase();
        if (!needle) {
            scored.push([2, field]);
        } else if (name.startsWith(needle) || label.startsWith(needle)) {
            scored.push([0, field]);
        } else if (name.includes(needle) || label.includes(needle)) {
            scored.push([1, field]);
        }
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].string.localeCompare(b[1].string));
    return scored.map(([, field]) => field);
}

// Model and prefix of a dotted path: "partner_id.na" -> res.partner, "partner_id.", "na".
async function resolvePath(rootModel, text, loadFields) {
    const parts = (text || "").split(".");
    const term = parts.pop();
    let model = rootModel;
    for (const part of parts) {
        const field = (await loadFields(model)).find((f) => f.name === part);
        if (!field || !field.relation) {
            return null;
        }
        model = field.relation;
    }
    return { model, prefix: parts.length ? parts.join(".") + "." : "", term };
}

// Search dialog of "Search More...": list of fields with a search bar, the
// relational ones can be opened to choose one of their fields. Read only:
// fields are never created or changed here.
export class FieldSearchDialog extends Component {
    static template = "report_studio.FieldSearchDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        model: String,
        loadFields: Function,
        onSelect: Function,
        filter: { type: Function, optional: true },
        prefix: { type: String, optional: true },
        search: { type: String, optional: true },
    };

    setup() {
        this.state = useState({
            // Path walked so far: [{model, label, prefix}]
            stack: [{ model: this.props.model, label: this.props.model, prefix: "" }],
            search: this.props.search || "",
            fields: [],
        });
        onWillStart(async () => {
            if (this.props.prefix) {
                await this.walkPrefix(this.props.prefix);
            }
            await this.loadLevel();
        });
    }

    get level() {
        return this.state.stack[this.state.stack.length - 1];
    }

    // Open the levels of an initial prefix ("partner_id.").
    async walkPrefix(prefix) {
        let model = this.props.model;
        let path = "";
        for (const part of prefix.split(".").filter(Boolean)) {
            const field = (await this.props.loadFields(model)).find((f) => f.name === part);
            if (!field?.relation) {
                return;
            }
            path += part + ".";
            model = field.relation;
            this.state.stack.push({ model, label: field.string, prefix: path });
        }
    }

    async loadLevel() {
        this.state.fields = await this.props.loadFields(this.level.model);
    }

    get rows() {
        return matchFields(this.state.fields, this.state.search);
    }

    selectable(field) {
        return !this.props.filter || this.props.filter(field);
    }

    async openRelation(field) {
        this.state.stack.push({
            model: field.relation,
            label: field.string,
            prefix: this.level.prefix + field.name + ".",
        });
        this.state.search = "";
        await this.loadLevel();
    }

    async goTo(index) {
        this.state.stack.splice(index + 1);
        this.state.search = "";
        await this.loadLevel();
    }

    choose(field) {
        if (!this.selectable(field)) {
            return;
        }
        this.props.onSelect(this.level.prefix + field.name);
        this.props.close();
    }
}

// Field path input in Odoo style: a few suggestions while typing, then
// "Search More..." opening the search dialog. Dotted paths are allowed
// (partner_id.name); typed text is kept as it is when leaving the input.
export class FieldSelector extends Component {
    static template = "report_studio.FieldSelector";
    static components = { AutoComplete };
    static props = {
        value: { type: String, optional: true },
        model: { type: String, optional: true },
        loadFields: Function,
        onChange: Function,
        filter: { type: Function, optional: true },
        placeholder: { type: String, optional: true },
        class: { type: String, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
    }

    get sources() {
        return [{ options: (request) => this.loadOptions(request) }];
    }

    async loadOptions(request) {
        if (!this.props.model) {
            return [];
        }
        const ctx = await resolvePath(this.props.model, request, this.props.loadFields);
        if (!ctx) {
            return [];
        }
        let fields = matchFields(await this.props.loadFields(ctx.model), ctx.term);
        if (this.props.filter) {
            fields = fields.filter(this.props.filter);
        }
        const options = fields.slice(0, SUGGESTIONS).map((field) => ({
            label: `${field.string} (${field.name})`,
            path: ctx.prefix + field.name,
        }));
        if (fields.length > SUGGESTIONS || !fields.length) {
            options.push({
                label: _t("Search More..."),
                classList: "o_m2o_dropdown_option o_m2o_dropdown_option_search_more",
                searchMore: true,
                ctx,
            });
        }
        return options;
    }

    onSelect(option) {
        if (option.searchMore) {
            this.dialog.add(FieldSearchDialog, {
                model: this.props.model,
                loadFields: this.props.loadFields,
                filter: this.props.filter,
                prefix: option.ctx.prefix,
                search: option.ctx.term,
                onSelect: (path) => this.props.onChange(path),
            });
            return;
        }
        this.props.onChange(option.path);
    }

    onChange({ inputValue }) {
        this.props.onChange((inputValue || "").trim());
    }
}
