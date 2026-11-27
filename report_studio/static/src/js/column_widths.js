/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
// Widths of the columns of a table, as integer percentages (total 100).
// Pure functions on column objects {width, locked}: they change the given
// columns and do not depend on the editor, so they can be tested alone.

// Split `total` into integers proportional to the weights (largest remainder
// method), with at least `min` per item when the total allows it.
export function distribute(total, weights, min = 1) {
    const n = weights.length;
    if (!n) return [];
    total = Math.max(0, Math.round(total));
    const floor = total >= n * min ? min : 0;
    const free = total - floor * n;
    let sum = weights.reduce((a, w) => a + Math.max(0, w || 0), 0);
    const base = sum > 0 ? weights.map((w) => Math.max(0, w || 0)) : weights.map(() => 1);
    sum = sum > 0 ? sum : n;
    const exact = base.map((w) => (free * w) / sum);
    const result = exact.map((x) => Math.floor(x));
    let rest = free - result.reduce((a, x) => a + x, 0);
    const order = exact
        .map((x, i) => [x - Math.floor(x), i])
        .sort((a, b) => b[0] - a[0] || a[1] - b[1]);
    for (let k = 0; rest > 0; k = (k + 1) % n, rest--) {
        result[order[k][1]] += 1;
    }
    return result.map((x) => x + floor);
}

const lockedSum = (columns, except) =>
    columns.reduce((a, c) => a + (c !== except && c.locked ? c.width || 0 : 0), 0);

// Columns without width (reports created before this feature): equal parts.
export function ensureWidths(columns) {
    if (columns.length && columns.some((c) => !(c.width > 0))) {
        distribute(100, columns.map(() => 1)).forEach((w, i) => {
            columns[i].width = w;
            columns[i].locked = Boolean(columns[i].locked);
        });
    }
}

// Set the width of a column; the other unlocked ones share the remaining space
// in proportion to their previous values. The value stops at what the locked
// columns leave free (at least 1% for every other free column).
export function setWidth(columns, column, value) {
    const others = columns.filter((c) => c !== column && !c.locked);
    const available = 100 - lockedSum(columns, column);
    if (!others.length) {
        column.width = Math.max(0, available);
        return column.width;
    }
    const wanted = Math.round(Number(value) || 0);
    column.width = Math.min(Math.max(wanted, 1), available - others.length);
    distribute(available - column.width, others.map((c) => c.width)).forEach((w, i) => {
        others[i].width = w;
    });
    return column.width;
}

// New column (unlocked): it gets its share of the free space and the other
// free columns shrink in proportion.
// 1 column 100 -> 2 columns 50/50 -> 3 columns 34/33/33.
export function addColumn(columns, column) {
    const free = columns.filter((c) => !c.locked);
    const available = 100 - lockedSum(columns, null);
    const share = Math.round(available / (free.length + 1));
    column.width = share;
    column.locked = false;
    distribute(available - share, free.map((c) => c.width)).forEach((w, i) => {
        free[i].width = w;
    });
    columns.push(column);
}

// Removed column: its width goes to the free columns, in proportion.
export function removeColumn(columns, column) {
    const index = columns.indexOf(column);
    if (index < 0) return;
    columns.splice(index, 1);
    const free = columns.filter((c) => !c.locked);
    if (!free.length) return;
    distribute(100 - lockedSum(columns, null), free.map((c) => c.width)).forEach((w, i) => {
        free[i].width = w;
    });
}

export const totalWidth = (columns) => columns.reduce((a, c) => a + (c.width || 0), 0);
