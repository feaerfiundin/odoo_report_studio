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
