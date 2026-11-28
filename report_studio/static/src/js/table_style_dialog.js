/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

const BORDER_STYLES = ["solid", "double", "dashed", "dotted"];
const PRESETS = ["all", "none", "outer", "horizontal", "vertical", "header"];
const VALIGNS = ["top", "middle", "bottom"];

// Editable copy of the table style, complete with every key.
export function tableStyleState(block) {
    const style = block.style || {};
    return {
        head: { background: "", color: "", height: null, ...(style.head || {}) },
        rows: { background: "", alt_background: "", height: null, valign: "", ...(style.rows || {}) },
        borders: { preset: "", style: "solid", width: 1, color: "#333333", ...(style.borders || {}) },
    };
}

// Table style without the empty values; undefined when nothing is set.
// keepLine: keep the border line even without scheme (used by column borders).
export function cleanTableStyle(style, keepLine = false) {
    if (!style) {
        return undefined;
    }
    const out = {};
    for (const part of ["head", "rows"]) {
        const values = Object.fromEntries(
            Object.entries(style[part] || {}).filter(
                ([, value]) => value !== "" && value !== null && value !== undefined && value !== 0
            )
        );
        if (Object.keys(values).length) {
            out[part] = values;
        }
    }
    if (style.borders?.preset) {
        out.borders = { ...style.borders };
    } else if (style.borders && keepLine) {
        // Only the line, used by the column borders.
        const { preset: _p, ...line } = style.borders;
        out.borders = line;
    }
    return Object.keys(out).length ? out : undefined;
}

// Popup "Table Style": backgrounds of header, rows and columns, borders by
// scheme and per column, row heights. Changes are applied on "Apply".
export class TableStyleDialog extends Component {
    static template = "report_studio.TableStyleDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        block: Object,
        labels: Object,
        onApply: Function,
    };

    setup() {
        const block = this.props.block;
        this.state = useState({
            ...tableStyleState(block),
            columns: block.columns.map((col) => ({
                _uid: col._uid,
                title: col.label || col.path || "—",
                background: col.background || "",
                border_left: Boolean(col.border_left),
                border_right: Boolean(col.border_right),
            })),
        });
        const labels = this.props.labels;
        this.presets = PRESETS.map((key) => [key, labels.border_presets[key]]);
        this.borderStyles = BORDER_STYLES.map((key) => [key, labels.borders[key]]);
        this.valigns = VALIGNS.map((key) => [key, labels.valigns[key]]);
        this.labels = {
            background: _t("Background"),
            textColor: _t("Text color"),
            altBackground: _t("Alternate rows"),
        };
    }

    onNumber(target, key, ev) {
        const value = Number(ev.target.value);
        target[key] = value > 0 ? Math.min(value, 100) : null;
        ev.target.value = target[key] || "";
    }

    apply() {
        const { head, rows, borders, columns } = this.state;
        this.props.onApply({
            style: { head: { ...head }, rows: { ...rows }, borders: { ...borders } },
            columns: columns.map((col) => ({ ...col })),
        });
        this.props.close();
    }
}
