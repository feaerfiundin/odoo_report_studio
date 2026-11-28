"""Smoke test dell'interfaccia di Report Studio con Playwright (Chromium headless).

Non fa parte del modulo Odoo: serve per provare l'editor in un browser vero
dalla VM di test, senza interfaccia grafica. Ogni passo registra esito,
notifiche/dialog Odoo e screenshot; alla fine elenca errori JS e risposte HTTP
>= 400 e scrive report.json nella cartella di output.

Esecuzione con l'immagine locale rs-playwright (vedi tools/README.md):

    docker run --rm --network stack --user "$(id -u):$(id -g)" -e HOME=/tmp \
      -v "$PWD/tools:/tools:ro" -v /percorso/output:/out \
      rs-playwright:local python3 /tools/ui_smoke.py --base http://stack-odoo:8069

Codice di uscita: 0 se tutti i passi riescono e non ci sono errori JS, 1 altrimenti.
I report creati dal test restano nel database (database di prova).
"""
import argparse
import json
import sys
import time

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://stack-odoo:8069")
ap.add_argument("--db", default="report_studio")
ap.add_argument("--login", default="admin")
ap.add_argument("--password", default="admin")
ap.add_argument("--out", default="/out")
ap.add_argument("--model", default="sale.order")
args = ap.parse_args()

STAMP = time.strftime("%H%M%S")
SKIPPED = "saltato: nessun documento Odoo per questo ruolo"
archived = {}
events = []
steps = []
step_no = 0


def log_event(kind, text):
    events.append({"step": step_no, "kind": kind, "text": text[:2000]})


def ui_messages(page):
    out = []
    for sel in (".o_notification", ".o_error_dialog", ".o_dialog .modal-body"):
        for el in page.locator(sel).all():
            try:
                text = el.inner_text(timeout=500).strip()
            except Exception:
                continue
            if text:
                out.append(f"{sel}: {' '.join(text.split())[:400]}")
    return out


def close_notifications(page):
    for btn in page.locator(".o_notification .o_notification_close").all():
        try:
            btn.click(timeout=500)
        except Exception:
            pass


def step(page, name, fn):
    global step_no
    step_no += 1
    t0 = time.time()
    res = {"n": step_no, "name": name, "ok": True}
    try:
        info = fn()
        if info:
            res["info"] = info
    except Exception as exc:
        res["ok"] = False
        res["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:400]}"
    page.wait_for_timeout(400)
    res["ui"] = ui_messages(page)
    res["shot"] = f"{args.out}/{step_no:02d}_{name}.png"
    page.screenshot(path=res["shot"])
    res["sec"] = round(time.time() - t0, 1)
    steps.append(res)
    mark = "OK " if res["ok"] else "ERR"
    print(f"[{mark}] {step_no:02d} {name} ({res['sec']}s) {res.get('info', '')} {res.get('error', '')}", flush=True)
    for msg in res["ui"]:
        print(f"       ui> {msg}", flush=True)
    # Un dialog d'errore aperto bloccherebbe i passi successivi.
    for btn in page.locator(".o_error_dialog .btn-primary, .o_dialog .btn-close").all():
        try:
            btn.click(timeout=500)
        except Exception:
            pass
    close_notifications(page)
    return res["ok"]


def expect(cond, message):
    if not cond:
        raise AssertionError(message)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="it-IT")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("console", lambda m: m.type == "error" and log_event("console.error", m.text))
    page.on("pageerror", lambda e: log_event("pageerror", str(e)))
    page.on("response", lambda r: r.status >= 400 and log_event("http", f"{r.status} {r.request.method} {r.url}"))

    app = ".o_rs_app"
    topbar = ".o_rs_topbar"
    lst = ".o_list_view"
    row = f"{lst} .o_data_row"

    def wait_list_reload(action):
        with page.expect_response(lambda r: "rs.report/search_read" in r.url):
            action()
        page.wait_for_timeout(300)

    def go_list():
        """Torna a Saved Layouts dall'editor o dal form Nuovo, confermando l'eventuale dialog."""
        page.locator(f"{app} button:has-text('Saved Layouts')").first.click()
        page.wait_for_timeout(500)
        modal = page.locator(".o_dialog")
        if modal.count():
            modal.locator("button.btn-primary").click()
        page.wait_for_selector(row)
        page.wait_for_timeout(1000)

    def list_names():
        return [t.strip() for t in page.locator(f"{row} td[name=name]").all_inner_texts()]

    def click_new():
        page.click(".o_control_panel .o_list_button_add")
        page.wait_for_selector("text=Open Visual Editor")

    def notification_text():
        page.wait_for_selector(".o_notification", timeout=15000)
        return " | ".join(page.locator(".o_notification").all_inner_texts())

    canvas = page.frame_locator(".o_rs_canvas_frame")
    block_labels = {"section": "Sezione", "text": "Testo", "field": "Campo", "table": "Tabella", "if": "Condizione",
                    "columns": "Colonne", "separator": "Separatore", "spacer": "Spaziatore",
                    "page_break": "Interruzione di pagina"}

    def wait_canvas():
        """Aspetta che la pagina centrale sia ridisegnata dopo le ultime modifiche."""
        page.wait_for_timeout(700)  # pausa dell'editor prima di ridisegnare
        page.wait_for_selector(".o_rs_canvas_loading", state="detached", timeout=30000)
        page.wait_for_timeout(300)

    def add_block(btype):
        page.click(f".o_rs_toolbox button[data-type={btype}]")
        # Il nuovo blocco è selezionato: pannello Proprietà del tipo giusto.
        page.wait_for_selector(f".o_rs_props_title:text-is('{block_labels[btype]}')")

    def set_field(locator, value):
        """Scelta del campo (autocompletamento in stile Odoo): scrive e conferma con Tab."""
        if isinstance(locator, str):
            locator = page.locator(locator)
        inp = locator.locator("input.o-autocomplete--input")
        inp.fill(value)
        inp.press("Tab")
        page.wait_for_timeout(150)

    def delete_selected():
        """Cestino nella barra del blocco selezionato (pagina centrale)."""
        wait_canvas()
        canvas.locator(".o_rs_cv_toolbar .o_rs_cv_delete").click()
        page.wait_for_timeout(200)

    def drag_in_canvas(target_css, mode, toolbox_type=None, has_text=None):
        """Trascinamento simulato (eventi HTML5): dalla maniglia della barra, o da un
        pulsante della colonna Blocchi, fino a prima/dopo/dentro un blocco della pagina."""
        if toolbox_type:
            page.locator(f".o_rs_toolbox button[data-type={toolbox_type}]").evaluate(
                "el => el.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: new DataTransfer()}))")
        else:
            canvas.locator(".o_rs_cv_toolbar .o_rs_cv_grip").evaluate(
                "el => el.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: new DataTransfer()}))")
        target = canvas.locator(target_css, has_text=has_text) if has_text else canvas.locator(target_css)
        target.first.evaluate("""(el, mode) => {
            const r = el.getBoundingClientRect();
            const y = mode === 'before' ? r.top + 1 : mode === 'after' ? r.bottom - 1 : r.top + r.height / 2;
            const opts = {bubbles: true, cancelable: true, clientX: r.left + 5, clientY: y,
                          dataTransfer: new DataTransfer()};
            el.dispatchEvent(new DragEvent('dragover', opts));
            el.dispatchEvent(new DragEvent('drop', opts));
        }""", mode)
        wait_canvas()

    def select_parent():
        page.click(".o_rs_props button:has-text('Seleziona il contenitore')")

    def canvas_types():
        """Tipi dei blocchi nella pagina centrale, in ordine."""
        wait_canvas()
        return canvas.locator("[data-rs-path]").evaluate_all("els => els.map(e => e.dataset.rsType)")

    # ---------------------------------------------------------------- passi

    def login():
        page.goto(f"{args.base}/web/login?db={args.db}")
        page.fill("input[name=login]", args.login)
        page.fill("input[name=password]", args.password)
        page.click("button[type=submit]")
        page.wait_for_selector(".o_main_navbar", timeout=30000)

    def open_from_menu():
        page.click(".o_navbar_apps_menu button")
        page.locator(".o_app", has_text="Report Studio").first.click()
        page.wait_for_selector(lst, timeout=30000)
        brand = page.locator(".o_menu_brand").inner_text().strip()
        expect(brand == "Report Studio", f"titolo della barra: {brand!r}")
        return f"barra: {brand}, report in elenco: {page.locator(row).count()}"

    def list_layout():
        """Nuovo a sinistra del titolo, barra di ricerca con filtro Attivi, colonna Attivo dopo Ultima modifica."""
        facets = " ".join(page.locator(".o_searchview .o_facet_values").all_inner_texts())
        expect("Attivi" in facets, f"filtro Attivi assente all'apertura: {facets!r}")
        states = [i.is_checked() for i in page.locator(f"{row} td[name=active] input").all()]
        expect(all(states), "con il filtro Attivi compaiono archiviati")
        new_box = page.locator(".o_control_panel .o_list_button_add").bounding_box()
        title_box = page.locator(".o_control_panel .o_breadcrumb").bounding_box()
        expect(new_box["x"] < title_box["x"], "Nuovo non è a sinistra di Saved Layouts")
        expect(page.locator(".o_control_panel .o_searchview").count() == 1, "barra di ricerca assente")
        headers = [h.strip() for h in page.locator(f"{lst} thead th").all_inner_texts() if h.strip()]
        expect("Attivo" in headers and headers.index("Attivo") == headers.index("Ultima modifica") + 1,
               f"intestazioni: {headers}")
        return f"colonne: {headers}"

    def sort_by_name():
        page.locator(f"{lst} thead th[data-name=name]").click()
        page.wait_for_timeout(800)
        names = list_names()
        expect(names == sorted(names, key=str.casefold) or names == sorted(names, key=str.lower),
               f"non ordinato: {names[:5]}")
        page.locator(f"{lst} thead th[data-name=name]").click()
        page.wait_for_timeout(800)
        desc = list_names()
        expect(desc[0] == names[-1] or desc != names, "secondo clic non inverte l'ordine")
        return f"primo: {names[0]!r}, dopo il secondo clic: {desc[0]!r}"

    def search_by_name():
        page.fill(".o_searchview_input", f"Copia {STAMP}")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        names = list_names()
        expect(names == [f"Copia {STAMP}"], f"ricerca: {names}")
        page.locator(".o_searchview .o_facet_remove").last.click()
        page.wait_for_timeout(1000)
        return "trovato solo il report cercato"

    def new_blank_report():
        click_new()
        page.fill(f"{app} input[placeholder='Nome del report']", f"Smoke {STAMP}")
        page.select_option(f"{app} select.form-select >> nth=0", args.model)
        page.click("button:has-text('Open Visual Editor')")
        page.wait_for_selector(topbar, timeout=20000)
        recs = page.locator(f"{topbar} select option").count()
        expect(recs > 0, "nessun record per l'anteprima")
        return f"record per l'anteprima: {recs}"

    def build_blocks():
        add_block("section")
        add_block("text")                      # dentro la sezione selezionata
        page.fill(".o_rs_props textarea", "Riga 1\nRiga 2")
        select_parent()                        # torna alla sezione
        page.wait_for_selector(".o_rs_props_title:text-is('Sezione')")
        add_block("field")                     # nella sezione
        set_field(".o_rs_props .o_rs_path_field", "name")
        add_block("table")                     # accanto al campo
        set_field(".o_rs_props .o_rs_path_source", "order_line")
        set_field(page.locator(".o_rs_props .o_rs_column").nth(0).locator(".o_rs_path_column"), "name")
        page.fill(".o_rs_props input[placeholder=etichetta] >> nth=0", "Descrizione")
        add_block("if")
        set_field(".o_rs_props .o_rs_path_if", "amount_total")
        page.select_option(".o_rs_props select", ">")
        page.fill(".o_rs_props label:has-text('Valore') + input", "0")
        add_block("text")
        page.fill(".o_rs_props textarea", "Totale positivo")
        types = canvas_types()
        expect(types == ["section", "text", "field", "table", "if", "text"], f"blocchi nella pagina: {types}")
        # La pagina mostra i dati reali e il testo appena digitato.
        expect(canvas.locator(".page").locator("text=Totale positivo").count() == 1, "testo non aggiornato nella pagina")
        expect(canvas.locator("th:has-text('Descrizione')").count() == 1, "tabella senza intestazione")
        # L'ultimo blocco aggiunto è evidenziato come selezionato.
        selected = canvas.locator(".o_rs_cv_selected")
        expect(selected.count() == 1, "nessun blocco evidenziato come selezionato")
        outline = selected.evaluate("el => getComputedStyle(el).outlineWidth + ' ' + getComputedStyle(el).outlineStyle")
        expect(outline == "2px solid", f"stile di selezione assente (contorno: {outline})")
        # Clic su un blocco della pagina: lo seleziona e mostra le sue proprietà.
        canvas.locator("[data-rs-type=table]").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Tabella')")
        return f"pagina: {types}"

    def width_logic():
        """Funzioni di column_widths.js, eseguite nel browser dal caricatore di Odoo."""
        res = page.evaluate("""() => {
            const m = odoo.loader.modules.get("@report_studio/js/column_widths");
            const cols = (ws, locked = []) => ws.map((w, i) => ({ width: w, locked: locked.includes(i) }));
            const ws = (cs) => cs.map((c) => c.width);
            const out = {};
            let c = cols([0, 0, 0]); m.ensureWidths(c); out.ensure3 = ws(c);
            m.setWidth(c, c[0], 50); out.set50 = ws(c);
            c[1].locked = true; m.setWidth(c, c[0], 60); out.lockedSet60 = ws(c);
            m.setWidth(c, c[0], 99); out.clamp = ws(c);
            c = cols([100]); m.addColumn(c, {}); out.add2 = ws(c);
            m.addColumn(c, {}); out.add3 = ws(c);
            c = cols([70, 30]); m.addColumn(c, {}); out.addKeepsRatio = ws(c);
            c = cols([50, 25, 25]); m.removeColumn(c, c[2]); out.remove = ws(c);
            c = cols([50, 25, 25], [0]); m.setWidth(c, c[2], 10); out.lockedFirst = ws(c);
            return out;
        }""")
        expect(res["ensure3"] == [34, 33, 33], res)
        expect(res["set50"] == [50, 25, 25], res)
        expect(res["lockedSet60"] == [60, 25, 15], res)
        expect(res["clamp"] == [74, 25, 1], res)
        expect(res["add2"] == [50, 50] and res["add3"] == [34, 33, 33], res)
        expect(res["addKeepsRatio"] == [47, 20, 33], res)
        expect(res["remove"] == [66, 34], res)
        expect(res["lockedFirst"] == [50, 40, 10], res)
        return json.dumps(res)

    def fonts_and_label():
        # Testo: 14 pt grassetto.
        canvas.locator("[data-rs-type=text]", has_text="Totale positivo").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Testo')")
        font = ".o_rs_props .o_rs_font[data-font='Carattere']"
        page.select_option(f"{font} select", "14")
        page.click(f"{font} button[data-style=bold]")
        # Campo: etichetta in corsivo, valore sottolineato.
        canvas.locator("[data-rs-type=field]").first.click()
        page.wait_for_selector(".o_rs_props_title:text-is('Campo')")
        page.fill(".o_rs_props .o_rs_field_label", "Ordine n.")
        page.click(".o_rs_props .o_rs_font[data-font='Carattere etichetta'] button[data-style=italic]")
        page.click(".o_rs_props .o_rs_font[data-font='Carattere valore'] button[data-style=underline]")
        # Tabella: intestazione grassetto, righe 9 pt.
        canvas.locator("[data-rs-type=table]").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Tabella')")
        page.click(".o_rs_props .o_rs_font[data-font='Carattere intestazione'] button[data-style=bold]")
        page.select_option(".o_rs_props .o_rs_font[data-font='Carattere righe'] select", "9")
        wait_canvas()
        style = lambda loc: loc.first.get_attribute("style") or ""
        text_style = style(canvas.locator("p", has_text="Totale positivo"))
        expect("font-size: 14pt" in text_style and "bold" in text_style, f"testo: {text_style!r}")
        label = canvas.locator(".o_rs_label", has_text="Ordine n.")
        expect(label.count() == 1 and "italic" in style(label), f"etichetta: {style(label)!r}")
        value_style = style(canvas.locator("[data-rs-type=field] span[style*=underline]"))
        expect("underline" in value_style, "valore del campo non sottolineato")
        expect("bold" in style(canvas.locator("th")), f"intestazione: {style(canvas.locator('th'))!r}")
        expect("9pt" in style(canvas.locator("tbody td")), "righe della tabella senza 9 pt")
        # Il pulsante attivo resta evidenziato nel pannello.
        expect(page.locator(".o_rs_props .o_rs_font[data-font='Carattere intestazione'] button[data-style=bold].active").count() == 1,
               "pulsante grassetto non evidenziato")
        return "testo 14pt grassetto, etichetta corsivo, valore sottolineato, tabella grassetto/9pt"

    def column_widths():
        page.click(".o_rs_props button:has-text('+ colonna')")
        page.click(".o_rs_props button:has-text('+ colonna')")
        paths = ["name", "product_uom_qty", "price_unit"]
        for i, path in enumerate(paths):
            set_field(page.locator(".o_rs_props .o_rs_column").nth(i).locator(".o_rs_path_column"), path)
        widths = lambda: [int(v) for v in page.locator(".o_rs_props .o_rs_width_input").evaluate_all("els => els.map(e => e.value)")]
        expect(widths() == [34, 33, 33], f"dopo 3 colonne: {widths()}")
        first = page.locator(".o_rs_props .o_rs_width_input").nth(0)
        first.fill("50")
        first.press("Tab")
        page.wait_for_timeout(300)  # ridisegno del pannello
        expect(widths() == [50, 25, 25], f"dopo 50%: {widths()}")
        page.locator(".o_rs_props .o_rs_width_lock").nth(1).check()
        page.wait_for_timeout(300)
        expect(page.locator(".o_rs_props .o_rs_width_input").nth(1).is_disabled(), "colonna bloccata modificabile")
        first.fill("60")
        first.press("Tab")
        page.wait_for_timeout(300)  # ridisegno del pannello
        expect(widths() == [60, 25, 15], f"con la seconda bloccata: {widths()}")
        total = page.locator(".o_rs_props .o_rs_width_total").inner_text()
        expect("100%" in total, total)
        wait_canvas()
        th = canvas.locator("[data-rs-type=table] th").evaluate_all("els => els.map(e => e.style.width)")
        expect(th == ["60%", "25%", "15%"], f"larghezze nella pagina: {th}")
        # Ogni colonna su una sola riga: tutti i controlli alla stessa altezza.
        tops = page.locator(".o_rs_props .o_rs_column").first.evaluate(
            "row => [...row.children].map(c => Math.round(c.getBoundingClientRect().top + c.offsetHeight / 2))")
        expect(max(tops) - min(tops) <= 4, f"controlli della colonna su più righe: {tops}")
        # Margini della tabella.
        page.locator(".o_rs_props .o_rs_margins input[data-side=left]").fill("6")
        page.locator(".o_rs_props .o_rs_margins input[data-side=left]").press("Tab")
        wait_canvas()
        pad = canvas.locator("[data-rs-type=table] > div").first.get_attribute("style") or ""
        expect("6mm" in pad, f"margine della tabella: {pad!r}")
        # Pannello proprietà con scorrimento verticale.
        scroll = page.locator(".o_rs_props").evaluate(
            "el => [getComputedStyle(el).overflowY, el.scrollHeight > el.clientHeight, el.clientHeight <= window.innerHeight]")
        expect(scroll[0] == "auto" and scroll[2], f"scorrimento proprietà: {scroll}")
        if scroll[1]:
            page.locator(".o_rs_props").evaluate("el => el.scrollTop = el.scrollHeight")
            expect(page.locator(".o_rs_props").evaluate("el => el.scrollTop") > 0, "il pannello non scorre")
        return f"34/33/33 -> 50/25/25 -> blocco 2a -> 60/25/15; pagina {th}; riga unica; margine {pad}; scorre {scroll[1]}"

    def move_columns():
        """Avviso "scegli prima la sorgente" e spostamento delle colonne con ▲▼."""
        heads = lambda: [t.strip() for t in canvas.locator("[data-rs-type=table] th").all_inner_texts()]
        th_widths = lambda: canvas.locator("[data-rs-type=table] th").evaluate_all("els => els.map(e => e.style.width)")
        before = heads()
        # La prima colonna scende di una posizione: porta con sé larghezza ed etichetta.
        page.locator(".o_rs_props .o_rs_column").nth(0).locator(".o_rs_col_down").click()
        wait_canvas()
        page.wait_for_timeout(600)
        after = heads()
        expect(after[:2] == [before[1], before[0]] and after[2:] == before[2:], f"ordine: {before} -> {after}")
        expect(th_widths() == ["25%", "60%", "15%"], f"larghezze dopo lo spostamento: {th_widths()}")
        expect(page.locator(".o_rs_props .o_rs_column").nth(0).locator(".o_rs_col_up").is_disabled(),
               "▲ attivo sulla prima colonna")
        expect(page.locator(".o_rs_props .o_rs_column").nth(2).locator(".o_rs_col_down").is_disabled(),
               "▼ attivo sull'ultima colonna")
        page.locator(".o_rs_props .o_rs_column").nth(1).locator(".o_rs_col_up").click()  # rimette a posto
        wait_canvas()
        page.wait_for_timeout(600)
        expect(heads() == before, f"ripristino dell'ordine: {heads()}")
        # Tabella nuova senza sorgente: la colonna chiede prima la sorgente.
        add_block("table")
        hint = page.locator(".o_rs_props .o_rs_source_first").count()
        placeholder = page.locator(".o_rs_props .o_rs_path_column input").first.get_attribute("placeholder")
        expect(hint == 1 and "sorgente" in (placeholder or ""), f"avviso: {hint}, segnaposto {placeholder!r}")
        set_field(".o_rs_props .o_rs_path_source", "order_line")
        page.wait_for_selector(".o_rs_props .o_rs_source_first", state="detached")
        placeholder2 = page.locator(".o_rs_props .o_rs_path_column input").first.get_attribute("placeholder")
        delete_selected()
        return f"{before} -> {after} -> ripristinato; segnaposto {placeholder!r} -> {placeholder2!r}"

    def layout_blocks():
        # Nessuna selezione: clic su una zona della pagina fuori dai blocchi.
        canvas.locator("body").click(position={"x": 3, "y": 3})
        page.wait_for_selector(".o_rs_props :text('Seleziona un blocco')")
        add_block("columns")
        page.select_option(".o_rs_props .o_rs_columns_count", "3")
        page.check(".o_rs_props .o_rs_columns_divider")
        page.fill(".o_rs_props .o_rs_margins input[data-side=top]", "5")
        page.locator(".o_rs_props .o_rs_margins input[data-side=top]").press("Tab")
        wait_canvas()
        cols = canvas.locator("td[data-rs-type=column]")
        expect(cols.count() == 3, f"colonne nella pagina: {cols.count()}")
        # Testo nella terza colonna, con margine sinistro della colonna.
        cols.nth(2).click()
        page.wait_for_selector(".o_rs_props_title:text-is('Colonna')")
        wait_canvas()
        expect(not canvas.locator(".o_rs_cv_toolbar .o_rs_cv_delete").is_visible(), "una colonna si può eliminare")
        page.fill(".o_rs_props .o_rs_margins input[data-side=left]", "4")
        page.locator(".o_rs_props .o_rs_margins input[data-side=left]").press("Tab")
        add_block("text")
        page.fill(".o_rs_props textarea", "In colonna")
        # Da 3 a 2 colonne: il testo passa nell'ultima colonna rimasta.
        select_parent()
        page.wait_for_selector(".o_rs_props_title:text-is('Colonna')")
        select_parent()
        page.wait_for_selector(".o_rs_props_title:text-is('Colonne')")
        page.select_option(".o_rs_props .o_rs_columns_count", "2")
        # Dopo il blocco Colonne: separatore, spaziatore, interruzione di pagina.
        add_block("separator")
        page.select_option(".o_rs_props .o_rs_separator_style", "dashed")
        page.select_option(".o_rs_props .o_rs_separator_thickness", "3")
        add_block("spacer")
        page.fill(".o_rs_props .o_rs_spacer_height", "15")
        page.locator(".o_rs_props .o_rs_spacer_height").press("Tab")
        add_block("page_break")
        types = canvas_types()
        tail = types[types.index("columns"):]
        expect(tail == ["columns", "column", "column", "text", "separator", "spacer", "page_break"], f"pagina: {tail}")
        cols = canvas.locator("td[data-rs-type=column]")
        expect(cols.nth(1).locator("text=In colonna").count() == 1, "il testo non è passato nell'ultima colonna")
        expect("border-left: 1px solid" in (cols.nth(1).get_attribute("style") or ""), "riga verticale assente")
        expect("padding: 5mm" in (canvas.locator("[data-rs-type=columns] > div").first.get_attribute("style") or ""),
               "margine del blocco Colonne assente")
        sep = canvas.locator("[data-rs-type=separator] > div").first.get_attribute("style") or ""
        expect("3px dashed" in sep, f"separatore: {sep!r}")
        spacer = canvas.locator("[data-rs-type=spacer] > div").first.get_attribute("style") or ""
        expect("15mm" in spacer, f"spaziatore: {spacer!r}")
        expect(canvas.locator(".page").locator("text=Interruzione di pagina").count() == 1, "interruzione di pagina non visibile")
        return f"pagina: {tail}"

    def alignment():
        """Sezione a destra, testo centrato: il figlio vince, il resto segue la sezione."""
        # Allineamento del blocco (non quello dell'etichetta della sezione).
        align = lambda target: page.click(f".o_rs_props > .o_rs_align button[data-align={target}]")
        computed = lambda loc: loc.first.evaluate("el => getComputedStyle(el).textAlign")
        canvas.locator("[data-rs-type=text]", has_text="Riga 1").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Testo')")
        align("center")
        select_parent()
        page.wait_for_selector(".o_rs_props_title:text-is('Sezione')")
        align("right")
        page.wait_for_selector(".o_rs_props .o_rs_align button.active[data-align=right]", timeout=3000)
        # Tabella centrata, prima colonna a sinistra.
        canvas.locator("[data-rs-type=table]").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Tabella')")
        align("center")
        # Colonne non impostate: simbolo della tabella (centro), attenuato.
        second = page.locator(".o_rs_props .o_rs_col_align").nth(1)
        expect("o_rs_inherited" in second.get_attribute("class")
               and second.locator("i.fa-align-center").count() == 1, "colonna senza simbolo della tabella")
        page.locator(".o_rs_props .o_rs_col_align").nth(0).click()
        page.locator(".o_rs_col_align_menu [data-align=left]").click()
        page.wait_for_selector(".o_rs_props .o_rs_col_align[data-align=left] i.fa-align-left", timeout=3000)
        # Prima colonna del blocco Colonne giustificata.
        canvas.locator("td[data-rs-type=column]").first.click()
        page.wait_for_selector(".o_rs_props_title:text-is('Colonna')")
        align("justify")
        wait_canvas()
        text = computed(canvas.locator("p", has_text="Riga 1"))
        field = computed(canvas.locator("[data-rs-type=field]").locator("xpath=.."))
        head = canvas.locator("[data-rs-type=table] th").evaluate_all("els => els.map(e => getComputedStyle(e).textAlign)")
        column = computed(canvas.locator("td[data-rs-type=column]"))
        outside = computed(canvas.locator("[data-rs-type=columns]"))
        expect(text == "center", f"testo: {text}")
        breaks = canvas.locator("p", has_text="Riga 1").locator("br").count()
        expect(breaks == 1, f"a capo del testo non riportato nella pagina: {breaks} <br>")
        expect(field == "right", f"campo nella sezione: {field}")
        expect(head[0] == "left" and set(head[1:]) == {"center"}, f"intestazioni: {head}")
        expect(column == "justify", f"colonna: {column}")
        expect(outside in ("left", "start"), f"fuori dalla sezione: {outside}")
        # Secondo clic sul pulsante attivo: torna a "come il contenitore".
        align("justify")
        page.wait_for_selector(".o_rs_props .o_rs_align :text('come il contenitore')", timeout=3000)
        # Campo con allineamento proprio: vince sulla sezione a destra.
        canvas.locator("[data-rs-type=field]").first.click()
        page.wait_for_selector(".o_rs_props_title:text-is('Campo')")
        align("center")
        wait_canvas()
        own = computed(canvas.locator("div[data-rs-type=field] > div"))
        expect(own == "center", f"campo con allineamento proprio: {own}")
        return f"testo {text}, campo {field} -> {own}, intestazioni {head}, colonna {column}, resto {outside}"

    def save_version():
        page.fill(".o_rs_versions input[placeholder='Commento versione']", "smoke")
        page.click(f"{topbar} .o_rs_btn_save")
        text = notification_text()
        expect("Versione salvata" in text, text)
        versions = page.locator("button:has-text('Ripristina')").count()
        return f"versioni: {versions}"

    def preview_pdf():
        with page.expect_response(lambda r: "/report_studio/preview" in r.url, timeout=90000) as info:
            page.click(f"{topbar} .o_rs_btn_preview")
        resp = info.value
        ctype = resp.headers.get("content-type", "")
        expect(resp.status == 200 and "pdf" in ctype, f"HTTP {resp.status} {ctype}")
        page.wait_for_selector(".o_dialog .o_rs_preview_frame")
        page.click(".o_dialog button:has-text('Chiudi')")
        page.wait_for_selector(".o_dialog", state="detached")
        return f"popup, HTTP {resp.status} {ctype}"

    def invalid_save_shows_server_message():
        add_block("field")
        set_field(".o_rs_props .o_rs_path_field", "campo_che_non_esiste")
        page.click(f"{topbar} .o_rs_btn_save")
        text = notification_text()
        expect("campo_che_non_esiste" in text, f"messaggio generico: {text}")
        delete_selected()
        return text

    def restore(nth_from_end):
        """Ripristina la versione n-esima dal fondo (1 = v1) e aspetta la nuova versione."""
        buttons = page.locator("button:has-text('Ripristina')")
        before = buttons.count()
        buttons.nth(before - nth_from_end).click()
        page.wait_for_timeout(300)
        modal = page.locator(".o_dialog")
        if modal.count():
            modal.locator("button.btn-primary").click()
        page.wait_for_function(
            "[...document.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Ripristina').length > %d" % before,
            timeout=15000,
        )
        page.wait_for_timeout(300)
        return before

    def restore_versions():
        before = restore(1)                    # v1: report vuoto
        empty = canvas_types()
        expect(empty == [], f"dopo il ripristino della v1: {empty}")
        restore(2)                             # v2: i blocchi salvati
        labels = canvas_types()
        expect(len(labels) >= 6, f"dopo il ripristino della v2: {labels}")
        return f"versioni: {before} -> {before + 2}, blocchi ripristinati: {len(labels)}"

    def copy_version():
        page.fill("input[placeholder='Nome della copia']", f"Copia {STAMP}")
        page.locator("button:has-text('Copia')").first.click()
        page.wait_for_function(
            f"document.querySelector('.o_rs_topbar') && "
            f"document.querySelector('.o_rs_topbar').textContent.includes('Copia {STAMP}')",
            timeout=15000,
        )
        return "aperta la copia"

    def back_to_list():
        go_list()
        names = list_names()
        expect(f"Copia {STAMP}" in names and f"Smoke {STAMP}" in names, f"elenco: {names}")
        return f"report in elenco: {len(names)}"

    def new_from_studio_report():
        click_new()
        page.fill(f"{app} input[placeholder='Nome del report']", f"Da studio {STAMP}")
        source = page.locator(f"{app} select.form-select >> nth=1")
        value = source.locator("optgroup[label='Report Studio'] option", has_text=f"Smoke {STAMP}").first.get_attribute("value")
        source.select_option(value)
        page.click("button:has-text('Open Visual Editor')")
        page.locator(".o_dialog button.btn-primary").click()
        page.wait_for_function(
            f"document.querySelector('.o_rs_topbar') && "
            f"document.querySelector('.o_rs_topbar').textContent.includes('Da studio {STAMP}')",
            timeout=20000,
        )
        labels = canvas_types()
        expect(len(labels) >= 6, f"blocchi copiati: {labels}")
        return f"blocchi copiati: {len(labels)}"

    def new_from_odoo_document():
        go_list()
        click_new()
        page.fill(f"{app} input[placeholder='Nome del report']", f"Da Odoo {STAMP}")
        source = page.locator(f"{app} select.form-select >> nth=1")
        if not source.locator("optgroup[label='Documenti Odoo']").count():
            # Solo chi può modificare il QWeb libero vede i documenti Odoo.
            page.click(f"{app} button:has-text('Abbandona')")
            return SKIPPED
        option = source.locator("optgroup[label='Documenti Odoo'] option", has_text=f"({args.model})").first
        label = option.inner_text()
        source.select_option(option.get_attribute("value"))
        page.click("button:has-text('Open Visual Editor')")
        page.locator(".o_dialog button.btn-primary").click()
        page.wait_for_selector(f"{topbar} .badge:has-text('QWeb libero')", timeout=20000)
        expect("t-name" in page.locator("textarea.font-monospace").input_value(), "template QWeb vuoto")
        return f"copiato: {label}"

    def preview_qweb():
        return preview_pdf()

    def open_from_list(name):
        page.locator(f"{row} td[name=name]", has_text=name).first.click()
        page.wait_for_selector(topbar)

    def archive():
        """Interruttore Attivo nella barra dell'editor, poi ritorno all'elenco."""
        expect(page.locator(f"{topbar} button:has-text('Archivia')").count() == 0, "pulsante Archivia ancora presente")
        toggle = page.locator(f"{topbar} #o_rs_active")
        expect(toggle.is_checked(), "il report aperto risulta già archiviato")
        toggle.click()
        text = notification_text()
        expect("Report archiviato" in text, text)
        go_list()
        # Filtro Attivi di default: l'archiviato non compare.
        facets = " ".join(page.locator(".o_searchview .o_facet_values").all_inner_texts())
        expect("Attivi" in facets, f"filtro Attivi non attivo di default: {facets!r}")
        expect(archived["name"] not in list_names(), "archiviato visibile con il filtro Attivi")
        return "archiviato, nascosto dal filtro Attivi di default"

    def filter_archived():
        page.click(".o_searchview_dropdown_toggler")
        page.locator(".o_filter_menu .o-dropdown-item", has_text="Attivi").click()       # toglie Attivi
        page.wait_for_timeout(600)
        page.locator(".o_filter_menu .o-dropdown-item", has_text="Archiviati").click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        names = list_names()
        expect(archived["name"] in names, f"filtro Archiviati: {names}")
        states = [i.is_checked() for i in page.locator(f"{row} td[name=active] input").all()]
        expect(states and not any(states), f"il filtro Archiviati mostra attivi: {states}")
        # Senza filtri si vedono tutti, archiviati compresi, con Attivo spento.
        page.locator(".o_searchview .o_facet_remove").last.click()
        page.wait_for_timeout(800)
        cell = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] input")
        expect(cell.count() == 1 and not cell.is_checked(), "archiviato non visibile senza filtri")
        return f"archiviati: {len(names)}; senza filtri visibile con Attivo spento"

    def reactivate_toggle():
        cell = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] .o_field_boolean_toggle label, td[name=active] input").first
        cell.click()
        page.wait_for_timeout(1200)
        inp = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] input")
        expect(inp.is_checked(), "toggle Attivo non riattiva")
        return "riattivato dall'elenco"

    def rpc(model, method, rpc_args, kwargs=None):
        res = page.evaluate("""async (p) => (await (await fetch('/web/dataset/call_kw', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)})).json())""",
            {"jsonrpc": "2.0", "params": {"model": model, "method": method, "args": rpc_args,
                                          "kwargs": kwargs or {}}})
        if "error" in res:
            raise RuntimeError(res["error"].get("data", {}).get("message", res["error"]))
        return res["result"]

    # Per la prova delle traduzioni servono due lingue attive: se l'italiano non
    # è attivo lo attiva (senza caricare le traduzioni di Odoo) e alla fine lo
    # disattiva. La prova traduce in una lingua diversa dalla principale.
    lang_state = {"activated": []}

    def ensure_second_lang():
        ids = rpc("res.lang", "search", [[["code", "=", "it_IT"]]], {"context": {"active_test": False}})
        active = rpc("res.lang", "read", [ids, ["active"]])[0]["active"]
        if not active:
            rpc("res.lang", "write", [ids, {"active": True}])
            lang_state["activated"] = ids
        return "italiano attivato per la prova" if not active else "italiano già attivo"

    def field_suggestions():
        """Campo in stile Odoo: 4 suggerimenti + "Cerca ancora...", popup con ricerca e relazioni."""
        canvas.locator("[data-rs-type=field]").first.click()
        page.wait_for_selector(".o_rs_props_title:text-is('Campo')")
        inp = page.locator(".o_rs_props .o_rs_path_field input.o-autocomplete--input")
        inp.fill("")
        inp.type("p", delay=30)
        page.wait_for_selector(".o-autocomplete--dropdown-menu li")
        items = page.locator(".o-autocomplete--dropdown-menu li").all_inner_texts()
        expect(len(items) == 5 and "Cerca ancora" in items[-1], f"suggerimenti: {items}")
        page.locator(".o-autocomplete--dropdown-menu li", has_text="Cerca ancora").click()
        page.wait_for_selector(".o_rs_field_search")
        rows = page.locator(".o_rs_field_search .o_rs_field_row").count()
        page.fill(".o_rs_field_search_input", "cliente")
        page.wait_for_timeout(300)
        filtered = page.locator(".o_rs_field_search .o_rs_field_row").count()
        expect(0 < filtered < rows, f"ricerca: {rows} -> {filtered}")
        # Dentro la relazione partner_id, poi il campo "name".
        page.locator(".o_rs_field_search .o_rs_field_row[data-name=partner_id] .o_rs_field_open").click()
        page.wait_for_selector(".o_rs_field_search .o_rs_field_path li:nth-child(2)")
        page.fill(".o_rs_field_search_input", "")
        page.locator(".o_rs_field_search .o_rs_field_row[data-name=name]").click()
        page.wait_for_selector(".o_rs_field_search", state="detached")
        value = inp.input_value()
        expect(value == "partner_id.name", f"percorso scelto: {value!r}")
        # Nessuna creazione: niente "Crea" nel menu.
        inp.fill("zzz_nessuno")
        page.wait_for_timeout(500)
        texts = " ".join(page.locator(".o-autocomplete--dropdown-menu li").all_inner_texts())
        expect("Crea" not in texts and "Create" not in texts, f"opzione di creazione: {texts}")
        inp.fill("name")
        inp.press("Tab")
        return f"5 voci, popup {rows} -> {filtered} campi, scelto {value}"

    def table_style():
        """Popup Stile tabella: intestazione, righe alterne, bordi, sfondo e bordi di colonna."""
        canvas.locator("[data-rs-type=table]").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Tabella')")
        page.click(".o_rs_props .o_rs_table_style_btn")
        page.wait_for_selector(".o_rs_table_style")
        dlg = ".o_rs_table_style"
        set_color = lambda sel, color: page.locator(sel).evaluate(
            "(el, c) => { el.value = c; el.dispatchEvent(new Event('input', {bubbles: true})); }", color)
        set_color(f"{dlg} .col-md-6 >> nth=0 >> .o_rs_color[data-key=background] input[type=color]", "#000080")
        set_color(f"{dlg} .col-md-6 >> nth=0 >> .o_rs_color[data-key=color] input[type=color]", "#ffffff")
        set_color(f"{dlg} .col-md-6 >> nth=1 >> .o_rs_color[data-key=alt_background] input[type=color]", "#eeeeee")
        page.fill(f"{dlg} .o_rs_rows_height", "7")
        page.locator(f"{dlg} .o_rs_rows_height").press("Tab")
        page.select_option(f"{dlg} .o_rs_rows_valign", "middle")
        page.click(f"{dlg} .o_rs_preset[data-preset=horizontal]")
        page.select_option(f"{dlg} .o_rs_table_border_width", "2")
        set_color(f"{dlg} .o_rs_style_column >> nth=1 >> input[type=color]", "#ffff00")
        page.check(f"{dlg} .o_rs_style_column >> nth=0 >> .o_rs_col_border_right")
        page.click(".o_rs_style_apply")
        page.wait_for_selector(dlg, state="detached")
        wait_canvas()
        page.wait_for_timeout(600)
        th = canvas.locator("[data-rs-type=table] th").first.evaluate(
            "el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color, getComputedStyle(el).borderTopWidth]")
        expect(th[0] == "rgb(0, 0, 128)" and th[1] == "rgb(255, 255, 255)" and th[2] == "2px", f"intestazione: {th}")
        cells = canvas.locator("[data-rs-type=table] tbody tr").evaluate_all(
            "trs => trs.slice(0, 2).map(tr => [...tr.cells].map(td => getComputedStyle(td).backgroundColor))")
        expect(len(cells) == 2, f"righe: {cells}")
        expect(cells[1][0] == "rgb(238, 238, 238)", f"riga alterna: {cells}")
        expect(all(row[1] == "rgb(255, 255, 0)" for row in cells), f"colonna gialla (vince sulla riga): {cells}")
        right = canvas.locator("[data-rs-type=table] tbody td").first.evaluate("el => getComputedStyle(el).borderRightStyle")
        height = canvas.locator("[data-rs-type=table] tbody td").first.evaluate("el => el.getBoundingClientRect().height")
        expect(right == "solid" and height > 20, f"bordo destro {right}, altezza {height}")
        return f"intestazione {th}, righe {cells}, altezza {height:.0f}px"

    def drag_and_drop():
        """Barra del blocco selezionato (nome · etichetta, ↑↓, cestino) e trascinamento."""
        total = "[data-rs-type=text]"
        canvas.locator(total, has_text="Totale positivo").click()
        wait_canvas()
        caption = canvas.locator(".o_rs_cv_toolbar .o_rs_cv_caption").inner_text()
        expect(caption.startswith("Testo") and "Totale positivo" in caption, f"barra: {caption!r}")
        path = lambda: canvas.locator(total, has_text="Totale positivo").get_attribute("data-rs-path")
        inside_if = path()
        # Fuori dalla condizione, prima di tutto il resto della pagina.
        drag_in_canvas("[data-rs-path='0']", "before")
        expect(path() == "0", f"dopo il trascinamento in cima: {path()}")
        # Freccia giù: diventa il secondo blocco della pagina.
        canvas.locator(".o_rs_cv_toolbar .o_rs_cv_down").click()
        wait_canvas()
        expect(path() == "1", f"dopo la freccia giù: {path()}")
        # Di nuovo dentro la condizione (al centro del blocco Condizione).
        drag_in_canvas("[data-rs-type=if]", "inside")
        expect(path() == inside_if, f"di nuovo nella condizione: {path()} invece di {inside_if}")
        # Blocco nuovo trascinato dalla colonna Blocchi dopo il primo blocco della pagina.
        drag_in_canvas("[data-rs-path='0']", "after", toolbox_type="spacer")
        new_type = canvas.locator("[data-rs-path='1']").get_attribute("data-rs-type")
        expect(new_type == "spacer", f"blocco nuovo in posizione 1: {new_type}")
        delete_selected()
        wait_canvas()
        expect(canvas.locator("[data-rs-path='1']").get_attribute("data-rs-type") != "spacer", "spaziatore non eliminato")
        # Al passaggio del mouse su un altro blocco compare solo il nome.
        canvas.locator("[data-rs-type=table]").hover()
        page.wait_for_timeout(200)
        hover = canvas.locator(".o_rs_cv_hover").inner_text()
        expect(hover.startswith("Tabella"), f"nome al passaggio: {hover!r}")
        return f"barra {caption!r}; trascinato in cima, ↓, rientrato in {inside_if}; spaziatore dalla colonna Blocchi"

    def section_label_borders():
        """Sezione: etichetta con sfondo, bordi come nei fogli di calcolo, classi dal menu."""
        canvas.locator("[data-rs-type=text]", has_text="Riga 1").click()
        select_parent()
        page.wait_for_selector(".o_rs_props .o_rs_section_title_text")
        page.fill(".o_rs_props .o_rs_section_title_text", "Dati ordine")
        page.click(".o_rs_props .o_rs_border_all")
        page.select_option(".o_rs_props .o_rs_border_style", "double")
        page.select_option(".o_rs_props .o_rs_border_width", "3")
        page.select_option(".o_rs_props .o_rs_css_add", "o_rs_keep_together")
        page.wait_for_selector(".o_rs_props .o_rs_css_chip[data-class=o_rs_keep_together]", timeout=3000)
        chips = page.locator(".o_rs_props .o_rs_css_chip").all_inner_texts()
        expect(any("pagine" in c or "pages" in c for c in chips), f"classe dal menu: {chips}")
        wait_canvas()
        page.wait_for_timeout(600)
        title = canvas.locator(".o_rs_section_title", has_text="Dati ordine")
        expect(title.count() == 1, "etichetta della sezione assente nella pagina")
        bg = title.evaluate("el => getComputedStyle(el).backgroundColor")
        expect(bg not in ("rgba(0, 0, 0, 0)", "transparent"), f"sfondo dell'etichetta: {bg}")
        section = canvas.locator("[data-rs-type=section] > div").first
        css = section.evaluate("el => [getComputedStyle(el).borderTopStyle, getComputedStyle(el).borderTopWidth,"
                               " el.className]")
        expect(css[0] == "double" and css[1] == "3px" and "o_rs_keep_together" in css[2], f"bordo/classe: {css}")
        # Il testo libero mostra le classi scelte dal menu.
        free = page.locator(".o_rs_props .o_rs_css_text").input_value()
        expect("o_rs_keep_together" in free, f"campo classi: {free!r}")
        return f"etichetta con sfondo {bg}, bordo {css[0]} {css[1]}, classi {css[2]!r}"

    def translations():
        """Menu lingua: traduzione IT di un testo; pagina centrale nella lingua scelta."""
        select = page.locator(f"{topbar} .o_rs_lang_select")
        base = select.input_value()
        options = select.locator("option").all_inner_texts()
        codes = select.locator("option").evaluate_all("els => els.map(e => e.value)")
        other = next((c for c in codes if c != base), None)
        expect(other and any("(principale)" in o for o in options), f"menu lingua: {options}")
        short = other.split("_")[0].upper()
        canvas.locator("[data-rs-type=text]", has_text="Riga 1").click()
        page.wait_for_selector(".o_rs_props_title:text-is('Testo')")
        page.select_option(f"{topbar} .o_rs_lang_select", other)
        page.wait_for_selector(".o_rs_props .o_rs_translating")
        area = page.locator(".o_rs_props textarea.o_rs_text_content")
        expect(area.input_value() == "" and "Riga 1" in (area.get_attribute("placeholder") or ""),
               "in traduzione la casella deve essere vuota con il testo base come suggerimento")
        area.fill("Linea uno\nLinea due")
        wait_canvas()
        page.wait_for_timeout(600)
        expect(canvas.locator(".page").locator("text=Linea uno").count() == 1, "la pagina non mostra la traduzione")
        expect(canvas.locator(".page").locator("text=Riga 1").count() == 0, f"in {other} la pagina mostra ancora il testo base")
        label = [o for o in select.locator("option").all_inner_texts() if o.startswith(short)]
        expect(label and "✓" in label[0], f"lingua tradotta non marcata: {label}")
        page.select_option(f"{topbar} .o_rs_lang_select", base)
        wait_canvas()
        page.wait_for_timeout(600)
        expect(area.input_value().startswith("Riga 1"), f"testo base cambiato: {area.input_value()!r}")
        expect(canvas.locator(".page").locator("text=Riga 1").count() == 1, "torna alla lingua principale: testo base assente")
        # Opzione della pagina: stampa nella lingua del cliente.
        canvas.locator("body").click(position={"x": 3, "y": 3})
        page.wait_for_selector(".o_rs_props :text('Seleziona un blocco')")
        page.check(".o_rs_props .o_rs_print_lang")
        field = page.locator(".o_rs_props .o_rs_print_lang_field").input_value()
        expect(field == "partner_id", f"campo contatto: {field}")
        return f"base {base}, {other} tradotto, opzione lingua cliente su {field}"

    def open_by_url():
        page.goto(f"{args.base}/odoo/action-report_studio.action_rs_report_list")
        page.wait_for_selector(lst, timeout=30000)

    ok = step(page, "login", login)
    if ok:
        step(page, "seconda_lingua", ensure_second_lang)
    if ok and not step(page, "menu_report_studio", open_from_menu):
        ok = step(page, "apri_da_url", open_by_url)
    if ok:
        step(page, "layout_elenco", list_layout)
    if ok and step(page, "nuovo_report_vuoto", new_blank_report):
        step(page, "blocchi", build_blocks)
        step(page, "larghezze_logica", width_logic)
        step(page, "carattere_ed_etichetta", fonts_and_label)
        step(page, "larghezze_colonne", column_widths)
        step(page, "sposta_colonne", move_columns)
        step(page, "blocchi_impaginazione", layout_blocks)
        step(page, "allineamento", alignment)
        step(page, "campo_suggerimenti", field_suggestions)
        step(page, "stile_tabella", table_style)
        step(page, "trascina_blocchi", drag_and_drop)
        step(page, "sezione_etichetta_bordi", section_label_borders)
        step(page, "traduzioni", translations)
        step(page, "salva_versione", save_version)
        step(page, "anteprima_pdf", preview_pdf)
        step(page, "errore_server_leggibile", invalid_save_shows_server_message)
        step(page, "ripristina_versioni", restore_versions)
        step(page, "copia_versione", copy_version)
        step(page, "torna_elenco", back_to_list)
        step(page, "ordina_per_nome", sort_by_name)   # qui l'elenco ha almeno due report
        step(page, "ricerca", search_by_name)
        step(page, "nuovo_da_report_studio", new_from_studio_report)
        archived["name"] = f"Da Odoo {STAMP}"
        if step(page, "nuovo_da_documento_odoo", new_from_odoo_document):
            if steps[-1].get("info") == SKIPPED:
                archived["name"] = f"Da studio {STAMP}"
                step(page, "apri_da_elenco", lambda: open_from_list(archived["name"]))
            else:
                step(page, "anteprima_qweb", preview_qweb)
            if step(page, "archivia", archive):
                step(page, "filtro_archiviati", filter_archived)
                step(page, "riattiva_da_elenco", reactivate_toggle)

    # Pulizia: i report creati da questo giro (nome con STAMP) vengono eliminati,
    # così l'elenco non cresce a ogni esecuzione. Non è un passo del test.
    try:
        removed = page.evaluate("""async (stamp) => {
            const call = (method, args) => fetch(`/web/dataset/call_kw/rs.report/${method}`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jsonrpc: '2.0', params: {model: 'rs.report', method, args,
                    kwargs: {context: {active_test: false}}}})}).then((r) => r.json());
            const ids = (await call('search', [[['name', 'like', stamp]]])).result || [];
            if (ids.length) await call('unlink', [ids]);
            return ids.length; }""", STAMP)
        print(f"Report di prova eliminati: {removed}")
    except Exception as exc:  # noqa
        print(f"Pulizia non riuscita: {exc}")
    if lang_state["activated"]:
        try:
            rpc("res.lang", "write", [lang_state["activated"], {"active": False}])
            print("Italiano disattivato di nuovo")
        except Exception as exc:  # noqa
            print(f"Disattivazione dell'italiano non riuscita: {exc}")

    browser.close()

with open(f"{args.out}/report.json", "w") as fh:
    json.dump({"steps": steps, "events": events}, fh, indent=2, ensure_ascii=False)

failed = [s for s in steps if not s["ok"]]
js_errors = [e for e in events if e["kind"] != "http"]
print(f"\nPassi: {len(steps)}, falliti: {len(failed)}; errori JS: {len(js_errors)}; HTTP >= 400: {len(events) - len(js_errors)}")
for e in events:
    print(f"  [passo {e['step']:02d}] {e['kind']}: {e['text'][:300]}")
sys.exit(1 if failed or js_errors else 0)
