# tools

Strumenti di sviluppo, **non** fanno parte del modulo Odoo.

## ui_smoke.py — smoke test dell'interfaccia

Apre l'editor di Report Studio in Chromium headless (Playwright) e percorre il
flusso principale: login, menu, nuovo report, blocchi, salvataggio versione,
anteprima PDF, errore leggibile, ripristino e copia di versioni, nuovo report da
report Studio e da documento Odoo, anteprima QWeb, archiviazione.

Per ogni passo stampa esito e notifiche Odoo e salva uno screenshot; alla fine
elenca errori JS e risposte HTTP >= 400 e scrive `report.json` nella cartella di
output. Codice di uscita 0 se tutto riesce, 1 altrimenti.

I report creati dal test restano nel database: usalo solo su un DB di prova.

### Immagine Docker (una volta sola)

```
cat > /tmp/Dockerfile.rs-playwright <<'DOCKER'
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy
RUN pip install --no-cache-dir playwright==1.46.0
DOCKER
docker build -t rs-playwright:local -f /tmp/Dockerfile.rs-playwright /tmp
```

### Esecuzione

Dalla radice del repository, con il container sulla rete Docker dello stack
(`stack`), così raggiunge Odoo per nome:

```
mkdir -p /tmp/rs-ui
docker run --rm --network stack --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/tools:/tools:ro" -v /tmp/rs-ui:/out \
  rs-playwright:local python3 /tools/ui_smoke.py --base http://stack-odoo:8069
```

Opzioni: `--base` (URL di Odoo), `--db` (default `report_studio`), `--login`,
`--password`, `--out` (cartella di output nel container, default `/out`),
`--model` (default `sale.order`). Login e password di default sono quelli del
DB di prova; per altri ambienti passali da riga di comando.

## feature_test.py — elenco Saved Layouts e ruoli

Prova l'elenco standard dei report: filtri (Attivi, Archiviati, QWeb libero),
raggruppamenti anche annidati, salvataggio di un preferito e sua riapplicazione
dopo il ricaricamento della pagina, ricerca per modello, ordinamento per
colonna. Poi entra come editor (interruttore Attivo, apertura dell'editor) e
come visualizzatore (niente "Nuovo", Attivo in sola lettura).

Va lanciato dopo `ui_smoke.py`, così in elenco ci sono report attivi e
archiviati di più modelli. Con l'utente admin crea o aggiorna gli utenti di
prova `rs_ui_editor` e `rs_ui_viewer`, con una password casuale diversa a ogni
esecuzione; il preferito creato dal test viene cancellato alla fine.

```
mkdir -p /tmp/rs-feat
docker run --rm --network stack --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/tools:/tools:ro" -v /tmp/rs-feat:/out \
  rs-playwright:local python3 /tools/feature_test.py --base http://stack-odoo:8069
```

Opzioni: `--base`, `--db`, `--login`, `--password`, `--out`, come per `ui_smoke.py`.
Codice di uscita 0 se tutti i passi riescono, 1 altrimenti.
