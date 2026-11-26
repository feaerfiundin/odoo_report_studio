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
    block_labels = {"section": "Sezione", "text": "Testo", "field": "Campo", "table": "Tabella", "if": "Condizione"}

    def wait_canvas():
        """Aspetta che la pagina centrale sia ridisegnata dopo le ultime modifiche."""
        page.wait_for_timeout(700)  # pausa dell'editor prima di ridisegnare
        page.wait_for_selector(".o_rs_canvas_loading", state="detached", timeout=30000)
        page.wait_for_timeout(300)

    def add_block(btype):
        page.click(f".o_rs_toolbox button[data-type={btype}]")
        # Il nuovo blocco è selezionato: pannello Proprietà del tipo giusto.
        page.wait_for_selector(f".o_rs_props_title:text-is('{block_labels[btype]}')")

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
        """Nuovo a sinistra del titolo, barra di ricerca, colonna Attivo dopo Ultima modifica."""
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
        page.fill(".o_rs_props input[list=rs_fields]", "name")
        add_block("table")                     # accanto al campo
        page.fill(".o_rs_props input[list=rs_fields] >> nth=0", "order_line")
        page.locator(".o_rs_props input[list=rs_fields] >> nth=0").dispatch_event("input")
        page.fill(".o_rs_props input[placeholder=campo] >> nth=0", "name")
        page.fill(".o_rs_props input[placeholder=etichetta] >> nth=0", "Descrizione")
        add_block("if")
        page.fill(".o_rs_props input[list=rs_fields]", "amount_total")
        page.select_option(".o_rs_props select", ">")
        page.fill(".o_rs_props label:has-text('Valore') + input", "0")
        add_block("text")
        page.fill(".o_rs_props textarea", "Totale positivo")
        types = canvas_types()
        expect(types == ["section", "text", "field", "table", "if", "text"], f"blocchi nella pagina: {types}")
        # La pagina mostra i dati reali e il testo appena digitato.
        expect(canvas.locator("text=Totale positivo").count() == 1, "testo non aggiornato nella pagina")
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
        page.fill(".o_rs_props input[list=rs_fields]", "campo_che_non_esiste")
        page.click(f"{topbar} .o_rs_btn_save")
        text = notification_text()
        expect("campo_che_non_esiste" in text, f"messaggio generico: {text}")
        page.click(".o_rs_props button:has-text('Elimina blocco')")
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
        # Gli archiviati restano in elenco con Attivo spento.
        cell = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] input")
        expect(cell.count() == 1 and not cell.is_checked(), "archiviato non visibile o ancora attivo")
        return "archiviato, visibile con Attivo spento"

    def filter_archived():
        page.click(".o_searchview_dropdown_toggler")
        page.locator(".o_filter_menu .o-dropdown-item", has_text="Archiviati").click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        names = list_names()
        expect(archived["name"] in names, f"filtro Archiviati: {names}")
        page.locator(".o_searchview .o_facet_remove").last.click()
        page.wait_for_timeout(800)
        return f"archiviati: {len(names)}"

    def reactivate_toggle():
        cell = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] .o_field_boolean_toggle label, td[name=active] input").first
        cell.click()
        page.wait_for_timeout(1200)
        inp = page.locator(row, has_text=archived["name"]).first.locator("td[name=active] input")
        expect(inp.is_checked(), "toggle Attivo non riattiva")
        return "riattivato dall'elenco"

    def open_by_url():
        page.goto(f"{args.base}/odoo/action-report_studio.action_rs_report_list")
        page.wait_for_selector(lst, timeout=30000)

    ok = step(page, "login", login)
    if ok and not step(page, "menu_report_studio", open_from_menu):
        ok = step(page, "apri_da_url", open_by_url)
    if ok:
        step(page, "layout_elenco", list_layout)
        step(page, "ordina_per_nome", sort_by_name)
    if ok and step(page, "nuovo_report_vuoto", new_blank_report):
        step(page, "blocchi", build_blocks)
        step(page, "salva_versione", save_version)
        step(page, "anteprima_pdf", preview_pdf)
        step(page, "errore_server_leggibile", invalid_save_shows_server_message)
        step(page, "ripristina_versioni", restore_versions)
        step(page, "copia_versione", copy_version)
        step(page, "torna_elenco", back_to_list)
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

    browser.close()

with open(f"{args.out}/report.json", "w") as fh:
    json.dump({"steps": steps, "events": events}, fh, indent=2, ensure_ascii=False)

failed = [s for s in steps if not s["ok"]]
js_errors = [e for e in events if e["kind"] != "http"]
print(f"\nPassi: {len(steps)}, falliti: {len(failed)}; errori JS: {len(js_errors)}; HTTP >= 400: {len(events) - len(js_errors)}")
for e in events:
    print(f"  [passo {e['step']:02d}] {e['kind']}: {e['text'][:300]}")
sys.exit(1 if failed or js_errors else 0)
