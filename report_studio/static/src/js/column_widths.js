/** @odoo-module **/
// Larghezze delle colonne di una tabella, in percentuale intera (totale 100).
// Funzioni pure sugli oggetti colonna {width, locked}: modificano le colonne
// passate e non dipendono dall'editor, così si possono provare da sole.

// Divide `total` in interi proporzionali ai pesi (metodo dei resti più grandi),
// con almeno `min` per elemento quando il totale lo permette.
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

// Colonne senza larghezza (report creati prima di questa funzione): parti uguali.
export function ensureWidths(columns) {
    if (columns.length && columns.some((c) => !(c.width > 0))) {
        distribute(100, columns.map(() => 1)).forEach((w, i) => {
            columns[i].width = w;
            columns[i].locked = Boolean(columns[i].locked);
        });
    }
}

// Imposta la larghezza di una colonna; le altre non bloccate si dividono lo
// spazio rimasto in proporzione ai valori che avevano. Il valore si ferma a
// quanto lasciano libero le colonne bloccate (almeno 1% per ogni altra libera).
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

// Nuova colonna (non bloccata): riceve la sua parte dello spazio libero e le
// altre colonne libere si restringono in proporzione.
// 1 colonna 100 -> 2 colonne 50/50 -> 3 colonne 34/33/33.
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

// Colonna rimossa: la sua larghezza va alle colonne libere, in proporzione.
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
