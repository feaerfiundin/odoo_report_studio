"""Test funzionali dell'elenco Saved Layouts con Playwright (Chromium headless).

Prova filtri, raggruppamenti (anche annidati), preferiti salvati e riapplicati
dopo il ricaricamento, ricerca per modello, ordinamento per colonna e i ruoli
non amministratori (editor e visualizzatore). Complementare a ui_smoke.py, che
prova l'editor. Crea da sé i report che servono (attivi e archiviati, a blocchi
e QWeb libero, su sale.order e account.move, nome "FT <ora>") e li elimina alla
fine: non dipende dai report già presenti nel database.

Crea o aggiorna da sé gli utenti di prova rs_ui_editor e rs_ui_viewer con una
password casuale a ogni esecuzione; il preferito di prova viene cancellato.
Esecuzione: vedi tools/README.md. Codice di uscita 0 se tutti i passi riescono.
"""
import argparse
import json
import re
import secrets
import sys
import time

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://stack-odoo:8069")
ap.add_argument("--db", default="report_studio")
ap.add_argument("--login", default="admin")
ap.add_argument("--password", default="admin")
ap.add_argument("--out", default="/out")
args = ap.parse_args()

BASE = args.base
OUT = args.out
TEST_PASSWORD = secrets.token_urlsafe(12)
STAMP = "FT %s" % time.strftime("%H%M%S")
results = []


def step(page, name, fn):
    try:
        info = fn() or ""
        results.append((True, name, info))
    except Exception as exc:  # noqa
        results.append((False, name, str(exc).splitlines()[0][:300]))
    page.screenshot(path=f"{OUT}/{len(results):02d}_{name}.png")
    ok, _, info = results[-1]
    print(f"[{'OK ' if ok else 'KO '}] {name}: {info}", flush=True)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


LIST = ".o_list_view"
ROW = f"{LIST} .o_data_row"


def login(page, user, pwd):
    page.goto(f"{BASE}/web/login?db={args.db}")
    page.fill("input[name=login]", user)
    page.fill("input[name=password]", pwd)
    page.click("button[type=submit]")
    page.wait_for_selector(".o_main_navbar", timeout=30000)
    page.goto(f"{BASE}/odoo/action-report_studio.action_rs_report_list")
    page.wait_for_selector(LIST, timeout=30000)
    page.wait_for_timeout(800)
    # L'elenco si apre col filtro Attivi: questi test partono senza filtri.
    clear_facets(page)


def open_menu(page):
    page.click(".o_searchview_dropdown_toggler")
    page.wait_for_selector(".o_search_bar_menu, .o-dropdown--menu")


def menu_item(page, text):
    page.locator(".o-dropdown--menu .o-dropdown-item, .o-dropdown--menu .dropdown-item", has_text=text).first.click()
    page.wait_for_timeout(900)


def clear_facets(page):
    while page.locator(".o_searchview .o_facet_remove").count():
        page.locator(".o_searchview .o_facet_remove").first.click()
        page.wait_for_timeout(600)


def rpc(page, model, method, rpc_args, kwargs=None):
    """Chiamata ORM con la sessione del browser (utente loggato)."""
    payload = {"jsonrpc": "2.0", "params": {"model": model, "method": method,
                                            "args": rpc_args, "kwargs": kwargs or {}}}
    res = page.evaluate(
        """async (p) => (await (await fetch('/web/dataset/call_kw', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)})).json())""",
        payload,
    )
    if "error" in res:
        raise RuntimeError(json.dumps(res["error"].get("data", {}).get("message", res["error"])))
    return res["result"]


def ensure_test_users(page):
    """Utenti rs_ui_editor / rs_ui_viewer con ruolo e password di questa esecuzione."""
    for login_name, role in (("rs_ui_editor", "editor"), ("rs_ui_viewer", "viewer")):
        ids = rpc(page, "res.users", "search", [[["login", "=", login_name]]],
                  {"context": {"active_test": False}})
        if not ids:
            ids = [rpc(page, "res.users", "create", [{"name": login_name, "login": login_name}])]
        rpc(page, "res.users", "write", [ids, {"active": True, "password": TEST_PASSWORD}])
        rpc(page, "res.users", "write", [ids, {"report_studio_role": role}])


def create_fixtures(page):
    """Report di prova di questo giro; restituisce i loro id."""
    model_id = lambda name: rpc(page, "ir.model", "search", [[["model", "=", name]]])[0]
    ids = []
    for label, model, active in (("ordine", "sale.order", True), ("ordine archiviato", "sale.order", False),
                                 ("fattura", "account.move", True), ("fattura archiviata", "account.move", False)):
        rid = rpc(page, "rs.report", "create", [{"name": f"{STAMP} {label}", "model_id": model_id(model)}])
        if not active:
            rpc(page, "rs.report", "write", [[rid], {"active": False}])
        ids.append(rid)
        time.sleep(1.1)  # date di ultima modifica diverse, per l'ordinamento
    action = rpc(page, "ir.actions.report", "search", [[["report_name", "=", "sale.report_saleorder"]]])
    ids.append(rpc(page, "rs.report", "create_from_source", [f"{STAMP} qweb", f"action:{action[0]}"]))
    return ids


def remove_fixtures(page):
    ids = rpc(page, "rs.report", "search", [[["name", "=like", f"{STAMP}%"]]], {"context": {"active_test": False}})
    if ids:
        rpc(page, "rs.report", "unlink", [ids])
    return len(ids)


def open_print_page(page):
    """Menu Report Studio > Report."""
    page.goto(f"{BASE}/odoo/action-report_studio.action_rs_report_print")
    page.wait_for_selector(LIST, timeout=30000)
    page.wait_for_timeout(800)


def open_print_form(page, name):
    open_print_page(page)
    clear_facets(page)   # anche gli archiviati
    page.locator(f"{ROW} td[name=name]", has_text=name).first.click()
    page.wait_for_selector(".o_form_view")
    page.wait_for_timeout(500)


def print_menu_items(page, model_action, label):
    """Voci del menu Stampa (ingranaggio) nella scheda del primo record."""
    page.goto(f"{BASE}/odoo/action-{model_action}")
    page.wait_for_selector(ROW, timeout=30000)
    page.locator(ROW).first.locator("td.o_data_cell").first.click()
    page.wait_for_selector(".o_form_view")
    page.locator(".o_cp_action_menus button").first.click()
    page.wait_for_timeout(500)
    # Voce "Print" del menu ingranaggio, nella lingua dell'utente.
    printer = page.locator(".o-dropdown--menu .o-dropdown-item, .o-dropdown--menu .dropdown-toggle",
                           has_text=re.compile(r"^\s*(Print|Stampa|Imprimer|Drucken)\s*$"))
    if printer.count():
        printer.first.hover()
        page.wait_for_timeout(500)
    items = page.locator(".o-dropdown--menu .o-dropdown-item").all_inner_texts()
    page.keyboard.press("Escape")
    return [i.strip() for i in items if label in i]


def col(page, name):
    return [t.strip() for t in page.locator(f"{ROW} td[name={name}]").all_inner_texts()]


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---------------- admin
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page, args.login, args.password)
    ensure_test_users(page)
    print(f"Report di prova creati: {len(create_fixtures(page))}")
    login(page, args.login, args.password)   # elenco ricaricato con i report nuovi

    def filtro_blocchi():
        open_menu(page)
        menu_item(page, "QWeb libero")
        page.keyboard.press("Escape")
        modes = col(page, "report_mode")
        expect(modes and set(modes) == {"QWeb libero"}, f"modalità: {set(modes)}")
        n = len(modes)
        clear_facets(page)
        return f"{n} report QWeb libero"

    def filtro_attivi():
        open_menu(page)
        menu_item(page, "Attivi")
        page.keyboard.press("Escape")
        states = [i.is_checked() for i in page.locator(f"{ROW} td[name=active] input").all()]
        expect(states and all(states), "filtro Attivi mostra archiviati")
        clear_facets(page)
        return f"{len(states)} attivi"

    def raggruppa_modello():
        open_menu(page)
        menu_item(page, "Modello")  # voce nel gruppo "Raggruppa per"
        page.keyboard.press("Escape")
        page.wait_for_selector(".o_group_header")
        groups = [g.strip() for g in page.locator(".o_group_header .o_group_name").all_inner_texts()]
        expect(any("sale.order" in g for g in groups), f"gruppi: {groups}")
        return f"gruppi: {groups}"

    def raggruppa_attivo():
        open_menu(page)
        menu_item(page, "Attivo")
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        facets = page.locator(".o_searchview .o_facet_values").all_inner_texts()
        expect(any("Attivo" in f for f in facets), f"faccette: {facets}")
        return f"raggruppamento annidato: {facets}"

    def salva_preferito():
        # filtro Archiviati + raggruppamenti già presenti
        open_menu(page)
        menu_item(page, "Archiviati")
        page.locator("button.o_add_favorite").first.click()
        page.wait_for_selector(".o_accordion input.o_input")
        page.fill(".o_accordion input.o_input", "Prova archiviati per modello")
        page.click(".o_save_favorite")
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        facets = " ".join(page.locator(".o_searchview .o_facet_values").all_inner_texts())
        expect("Prova archiviati per modello" in facets, f"faccette dopo salvataggio: {facets}")
        return "preferito salvato"

    def riapplica_preferito():
        clear_facets(page)
        page.reload()
        page.wait_for_selector(LIST)
        clear_facets(page)
        open_menu(page)
        menu_item(page, "Prova archiviati per modello")
        page.keyboard.press("Escape")
        page.wait_for_selector(".o_group_header")
        page.locator(".o_group_header").first.click()
        page.wait_for_timeout(800)
        sub = [g.strip() for g in page.locator(".o_group_header .o_group_name").all_inner_texts()]
        expect(len(sub) == 3 and sub[1].startswith("No"), f"sottogruppi: {sub}")
        page.locator(".o_group_header").nth(1).click()
        page.wait_for_timeout(800)
        states = [i.is_checked() for i in page.locator(f"{ROW} td[name=active] input").all()]
        expect(states and not any(states), f"il preferito non filtra gli archiviati: {states}")
        return f"riapplicato dopo il ricaricamento: gruppi + {len(states)} archiviati nel primo gruppo"

    def cerca_per_modello():
        clear_facets(page)
        page.fill(".o_searchview_input", "account")
        page.wait_for_selector(".o_searchview_autocomplete")
        page.locator(".o_searchview_autocomplete li", has_text="Modello (nome tecnico)").first.click()
        page.wait_for_timeout(1000)
        models = set(col(page, "model_name"))
        expect(models == {"account.move"}, f"modelli: {models}")
        clear_facets(page)
        return f"modelli trovati: {models}"

    def ordina_ultima_modifica():
        page.locator(f"{LIST} thead th[data-name=write_date]").click()
        page.wait_for_timeout(800)
        a = col(page, "write_date")
        page.locator(f"{LIST} thead th[data-name=write_date]").click()
        page.wait_for_timeout(800)
        b = col(page, "write_date")
        expect(a and b and a[0] != b[0], "l'ordine non cambia")
        return f"primo {a[0]} -> {b[0]}"

    def pagina_report_admin():
        open_print_page(page)
        names = col(page, "name")
        expect(f"{STAMP} ordine" in names, f"pagina Report: {names}")
        expect(page.locator(".o_list_button_add").count() == 0, "Nuovo nella pagina Report")
        open_print_form(page, f"{STAMP} ordine")
        expect(page.locator(".o_rs_add_print_menu").count() == 1, "pulsante Aggiungi al menu Stampa assente")
        page.locator(".o_field_widget[name=print_name] input").fill(f"{STAMP} stampa")
        page.locator(".o_rs_add_print_menu").click()          # salva e aggiunge
        page.wait_for_selector(".o_rs_remove_print_menu")
        expect(page.locator(".o_rs_print_menu_info").count() == 1, "avviso 'nel menu Stampa' assente")
        items = print_menu_items(page, "sale.action_orders", f"{STAMP} stampa")
        expect(items, "la voce non compare nel menu Stampa dell'ordine")
        open_print_form(page, f"{STAMP} ordine")
        page.locator(".o_rs_remove_print_menu").click()
        page.wait_for_selector(".o_rs_add_print_menu")
        gone = print_menu_items(page, "sale.action_orders", f"{STAMP} stampa")
        expect(not gone, f"voce ancora nel menu Stampa: {gone}")
        return f"aggiunto ({items}) e rimosso dal menu Stampa dell'ordine"

    def pagina_report_archiviato():
        open_print_form(page, f"{STAMP} ordine archiviato")
        expect(page.locator(".o_rs_add_print_menu").count() == 0, "Aggiungi visibile su un archiviato")
        expect(page.locator(".o_form_view .alert-warning").count() == 1, "avviso archiviato assente")
        return "archiviato: niente pulsante, avviso presente"

    def elimina_preferito():
        ids = rpc(page, "ir.filters", "search", [[["name", "=", "Prova archiviati per modello"]]])
        rpc(page, "ir.filters", "unlink", [ids])
        return f"preferiti di prova rimossi: {len(ids)}"

    for name, fn in [("filtro_qweb_libero", filtro_blocchi), ("filtro_attivi", filtro_attivi),
                     ("raggruppa_modello", raggruppa_modello), ("raggruppa_annidato_attivo", raggruppa_attivo),
                     ("salva_preferito", salva_preferito), ("riapplica_preferito", riapplica_preferito),
                     ("cerca_per_modello", cerca_per_modello), ("ordina_ultima_modifica", ordina_ultima_modifica),
                     ("pulizia_preferito", elimina_preferito), ("pagina_report_admin", pagina_report_admin),
                     ("pagina_report_archiviato", pagina_report_archiviato)]:
        step(page, name, fn)
    print("errori JS admin:", errors)
    ctx.close()

    # ---------------- editor
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    page.set_default_timeout(15000)

    def editor_elenco():
        login(page, "rs_ui_editor", TEST_PASSWORD)
        expect(page.locator(".o_list_button_add").count() == 1, "Nuovo assente")
        toggles = page.locator(f"{ROW} td[name=active] .o_field_boolean_toggle").count()
        expect(toggles > 0, "interruttore Attivo assente")
        return f"Nuovo presente, {toggles} interruttori"

    def editor_toggle():
        sw = page.locator(f"{ROW} td[name=active] .o_boolean_toggle input").first
        before = page.locator(f"{ROW} td[name=active] input").first.is_checked()
        sw.click()
        page.wait_for_timeout(1200)
        expect(page.locator(".o_rs_topbar").count() == 0, "il clic sull'interruttore ha aperto l'editor")
        after = page.locator(f"{ROW} td[name=active] input").first.is_checked()
        sw.click()
        page.wait_for_timeout(1200)
        expect(before != after, "lo stato non cambia")
        expect(not page.locator(".o_notification.bg-danger, .o_error_dialog").count(), "errore mostrato")
        return f"{before} -> {after} -> ripristinato"

    def editor_apre():
        page.locator(f"{ROW} td[name=name]").first.click()
        page.wait_for_selector(".o_rs_topbar")
        page.locator(".o_rs_app button", has_text="Saved Layouts").first.click()
        page.wait_for_selector(LIST)
        return "editor aperto e ritorno all'elenco"

    def editor_pagina_report():
        open_print_form(page, f"{STAMP} fattura")
        page.locator(".o_rs_add_print_menu").click()
        page.wait_for_selector(".o_rs_remove_print_menu")
        expect(not page.locator(".o_notification.bg-danger, .o_error_dialog").count(), "errore mostrato")
        page.locator(".o_rs_remove_print_menu").click()
        page.wait_for_selector(".o_rs_add_print_menu")
        return "l'editor aggiunge e toglie dal menu Stampa"

    for name, fn in [("editor_elenco", editor_elenco), ("editor_toggle_attivo", editor_toggle),
                     ("editor_apre_report", editor_apre), ("editor_pagina_report", editor_pagina_report)]:
        step(page, name, fn)
    ctx.close()

    # ---------------- visualizzatore
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    page.set_default_timeout(15000)

    def viewer_elenco():
        login(page, "rs_ui_viewer", TEST_PASSWORD)
        expect(page.locator(".o_list_button_add").count() == 0, "Nuovo visibile al visualizzatore")
        toggles = page.locator(f"{ROW} td[name=active] .o_field_boolean_toggle").count()
        boxes = page.locator(f"{ROW} td[name=active] input").all()
        expect(toggles == 0 and boxes, f"interruttori: {toggles}, caselle: {len(boxes)}")
        archived = sum(1 for b in boxes if not b.is_checked())
        return f"niente Nuovo né interruttore; vede {len(boxes)} report, {archived} archiviati"

    def viewer_non_modifica():
        box = page.locator(f"{ROW} td[name=active] input").first
        before = box.is_checked()
        expect(box.is_disabled(), "casella Attivo modificabile")
        return f"casella in sola lettura (valore {before})"

    def viewer_pagina_report():
        open_print_form(page, f"{STAMP} ordine")
        buttons = page.locator(".o_rs_add_print_menu, .o_rs_remove_print_menu").count()
        expect(buttons == 0, f"pulsanti visibili al visualizzatore: {buttons}")
        editable = page.locator(".o_field_widget[name=print_name] input").count()
        expect(editable == 0, "campo modificabile dal visualizzatore")
        return "pagina visibile in sola lettura"

    for name, fn in [("viewer_elenco", viewer_elenco), ("viewer_sola_lettura", viewer_non_modifica),
                     ("viewer_pagina_report", viewer_pagina_report)]:
        step(page, name, fn)
    ctx.close()

    # ---------------- pulizia (non è un passo del test)
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login(page, args.login, args.password)
        print(f"Report di prova eliminati: {remove_fixtures(page)}")
    except Exception as exc:  # noqa
        print(f"Pulizia non riuscita: {exc}")
    browser.close()

failed = [r for r in results if not r[0]]
print(f"\nPassi: {len(results)}, falliti: {len(failed)}")
sys.exit(1 if failed else 0)
