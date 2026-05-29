# pdf-filler — GitHub Copilot Skill

Skill per GitHub Copilot Agent che permette di **compilare PDF tramite API HTTP Docker**, partendo da uno schema pdfme o da un PDF con campi rilevati automaticamente.

## Cosa fa

- Avvia un container Docker con un'API HTTP (FastAPI + PyMuPDF)
- L'API carica in memoria una sola volta il template PDF e lo schema dei campi
- Espone `POST /fill` che riceve `{"Campo": "valore"}` e restituisce il PDF compilato
- Rileva automaticamente i campi di un PDF (AcroForm widget, box grafici, pattern label:spazio)
- Accessibile sia in locale che da remoto (binding su `0.0.0.0`)
- Opzionalmente espone tool MCP per integrazione diretta con Copilot

## Struttura

```
pdf-filler/
├── SKILL.md                 ← istruzioni per l'agente Copilot
├── Dockerfile               ← immagine con Python scripts baked-in
├── docker-entrypoint.sh     ← dispatcher: detect | api
├── docker-compose.yml       ← alternativa a start_api.sh
├── mcp_server.py            ← tool MCP (detect, start, fill, stop)
├── vscode-mcp.json          ← config MCP per VS Code
└── scripts/
    ├── pdf_filler_api.py    ← FastAPI server (baked-in nell'immagine)
    ├── detect_fields.py     ← rilevamento campi PDF (baked-in)
    ├── start_api.sh         ← copia file, builda immagine, avvia container
    ├── stop_api.sh          ← ferma il container
    └── fill_pdf.sh          ← chiama POST /fill e salva il PDF
```

## Installazione

```bash
bash install.sh
```

Copia la skill in `~/.agents/skills/pdf-filler/`, rendendola disponibile all'agente Copilot.

Requisiti:
- Docker installato e in esecuzione
- GitHub Copilot Agent con supporto skills

## Uso rapido

### 1. Ottieni lo schema dei campi

**Metodo A — rilevamento automatico** (PDF con AcroForm, box o etichette):
```bash
# build immagine (una volta sola)
docker build -t pdf-filler ~/.agents/skills/pdf-filler/

# rileva campi → scrive schema.json
docker run --rm -v $(pwd):/data pdf-filler detect \
  --pdf /data/modulo.pdf --schema /data/schema.json --verbose
```

**Metodo B — playground pdfme** (massimo controllo):
1. Vai su https://playground.pdfme.com
2. Carica il PDF template
3. Posiziona i campi di testo
4. Esporta `schema.json`

### 2. Avvia l'API

Copia i tre script nella dir del progetto e avvia:
```bash
cp ~/.agents/skills/pdf-filler/scripts/start_api.sh .
cp ~/.agents/skills/pdf-filler/scripts/stop_api.sh  .
cp ~/.agents/skills/pdf-filler/scripts/fill_pdf.sh  .

bash start_api.sh
```

Al primo avvio `start_api.sh`:
- Copia `Dockerfile` e gli script Python nella CWD
- Builda l'immagine Docker `pdf-filler`
- Avvia il container montando la CWD come `/data`
- Genera `fake_data.json` con i valori di default
- Esegue uno smoke test e stampa gli URL di accesso

### 3. Compila il PDF

```bash
# con lo script
bash fill_pdf.sh --data fake_data.json --output compilato.pdf

# oppure con curl
curl -X POST http://127.0.0.1:8765/fill \
  -H "Content-Type: application/json" \
  -d @fake_data.json \
  -o compilato.pdf
```

### 4. Ferma l'API

```bash
bash stop_api.sh
```

## Accesso remoto

Il container espone la porta su `0.0.0.0` — l'API è raggiungibile da qualsiasi macchina sulla stessa rete all'IP mostrato da `start_api.sh`:

```bash
curl -X POST http://192.168.1.50:8765/fill \
  -H "Content-Type: application/json" \
  -d @fake_data.json \
  -o compilato.pdf
```

## Integrazione MCP (opzionale)

Permette all'agente Copilot di chiamare i tool direttamente senza shell.

**Installazione dipendenza host:**
```bash
pip install "mcp[cli]"
```

**Configurazione VS Code** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "pdf-filler": {
      "type": "stdio",
      "command": "python3",
      "args": ["~/.agents/skills/pdf-filler/mcp_server.py"]
    }
  }
}
```

Tool disponibili: `detect_fields`, `start_api`, `stop_api`, `health`, `get_fields`, `get_sample`, `fill_pdf`.

## Endpoint API

| Endpoint | Metodo | Descrizione |
|---|---|---|
| `/health` | GET | Stato server + info schema |
| `/fields` | GET | Dettaglio campi (fontSize, position, alignment…) |
| `/sample` | GET | JSON con valori default pronti per `/fill` |
| `/fill` | POST | Riceve `{"Campo": "valore"}` → restituisce PDF binario |
| `/docs` | GET | Swagger UI interattiva |

## Opzioni start_api.sh

| Opzione | Default | Descrizione |
|---|---|---|
| `--schema` | `schema.json` | Nome file schema nella CWD |
| `--port` | `8765` | Porta esposta |
| `--workers` | `1` | Processi uvicorn |
| `--rebuild` | — | Forza rebuild immagine Docker |
