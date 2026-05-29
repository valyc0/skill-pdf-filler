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

## Come invocare la skill in chat

Basta scrivere in chat Copilot una richiesta che menzioni il PDF da compilare.
L'agente riconosce il contesto e attiva la skill automaticamente.

**Esempi di prompt:**

```
Usa la skill pdf-filler e compila il PDF modulo.pdf con i dati di Mario Rossi
```
```
Compila il PDF fattura.pdf usando la skill pdf-filler:
- Nome: Mario Rossi
- Importo: 1500€
- Data: 29/05/2026
```
```
Ho un PDF con campi AcroForm (SC106.pdf), usa la skill pdf-filler per
rilevare i campi automaticamente e compilarlo con dati fittizi
```
```
Avvia la skill pdf-filler con lo schema che trovi in /home/valerio/progetto/schema.json
e dimmi quali campi ci sono
```

L'agente eseguirà il flusso completo:
1. Rileva i campi (se non c'è già `schema.json`)
2. Copia gli script nella tua dir, builda l'immagine Docker e avvia l'API
3. Genera `fake_data.json` con i valori richiesti
4. Chiama `POST /fill` e salva il PDF compilato
5. Ti mostra il percorso del file generato

---

## Uso rapido (manuale)

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

---

## Come usare la skill con GitHub Copilot

Dopo aver installato la skill con `bash install.sh`, rivolgiti a Copilot in linguaggio naturale descrivendo cosa vuoi fare con il PDF. La skill viene attivata automaticamente quando menzioni PDF, compilazione campi, schema pdfme o form.

### Domande di esempio (chat Copilot)

```
"Usa la skill pdf-filler e compila il PDF modulo.pdf con i dati di Mario Rossi"

"Usa la skill pdf-filler e analizza i campi compilabili di contratto.pdf"

"Ho uno schema.json esportato da pdfme, usa la skill pdf-filler per avviare l'API e compilarmi una fattura"

"Usa la skill pdf-filler per compilare il modulo INPS con nome=Mario, cognome=Rossi, CF=RSSMRA80A01H501Z"

"Usa la skill pdf-filler, avvia l'API sulla porta 9000 e mostrami l'URL di rete"
```

Copilot leggerà la `SKILL.md`, guiderà l'utente nelle fasi (schema → avvio API → compilazione → verifica) e userà i tool MCP se configurati, oppure genererà i comandi shell da eseguire.

---

### Esempio guidato completo (senza MCP, solo comandi shell)

> **"Usa la skill pdf-filler: ho `modulo.pdf` nella cartella corrente. Voglio compilarlo con i miei dati."**

Copilot risponde con i passi da seguire:

**Step 1 — Copia gli script**
```bash
cp ~/.agents/skills/pdf-filler/scripts/start_api.sh .
cp ~/.agents/skills/pdf-filler/scripts/stop_api.sh  .
cp ~/.agents/skills/pdf-filler/scripts/fill_pdf.sh  .
```

**Step 2 — Rileva i campi (se non hai già uno schema)**
```bash
# build immagine (una volta sola)
docker build -t pdf-filler ~/.agents/skills/pdf-filler/

# analisi campi → scrive schema.json
docker run --rm -v $(pwd):/data pdf-filler detect \
  --pdf /data/modulo.pdf --schema /data/schema.json --verbose
```

**Step 3 — Avvia l'API**
```bash
bash start_api.sh
# → genera fake_data.json con i valori default di tutti i campi
```

**Step 4 — Modifica i dati e compila**
```bash
# edita fake_data.json con i tuoi valori, poi:
bash fill_pdf.sh --data fake_data.json --output compilato.pdf
```

**Step 5 — Ferma**
```bash
bash stop_api.sh
```

---

### Esempio 1 — PDF con campi AcroForm (modulo ufficiale, con MCP)

> **"Usa la skill pdf-filler: ho il file `modulo_inps.pdf` nella cartella `/home/valerio/documenti`. Analizza i campi compilabili, avvia l'API e compilalo con i dati di Mario Rossi, codice fiscale RSSMRA80A01H501Z, email mario@esempio.it"**

Copilot eseguirà in sequenza:
1. `detect_fields` sul PDF → rileva i campi AcroForm (COGNOME, NOME, CODICE_FISCALE, EMAIL…)
2. `start_api` → builda Docker, monta la dir, avvia l'API
3. `get_sample` → recupera i campi disponibili
4. `fill_pdf` → compila con i dati forniti e salva `compilato.pdf`

---

### Esempio 2 — Schema da playground pdfme

> **"Usa la skill pdf-filler: ho esportato `schema.json` da playground.pdfme.com per una fattura. La dir è `/home/valerio/fatture`. Avvia l'API e compilami una fattura per il cliente Acme Srl, importo 1500€, data oggi"**

Copilot:
1. `start_api("/home/valerio/fatture")` → avvia il container
2. `get_fields` → legge i campi dello schema (BilledTo, Amount, Date…)
3. `fill_pdf({"BilledTo": "Acme Srl", "Amount": "1500€", "Date": "29/05/2026"}, "fattura.pdf")`

---

### Esempio 3 — Solo rilevamento campi

> **"Usa la skill pdf-filler e analizza `contratto.pdf`: dimmi quali campi ha"**

Copilot chiama `detect_fields("contratto.pdf", verbose=True)` e ti restituisce la lista dei campi rilevati con nome, posizione e strategia usata (AcroForm / drawing / label-gap), senza avviare l'API.

---

### Esempio 4 — Accesso remoto da Java

> **"Usa la skill pdf-filler: avvia l'API sulla porta 9000 con 4 worker e mostrami come chiamarla da Java"**

Copilot:
1. `start_api(data_dir=".", port=9000, workers=4)` → stampa IP di rete
2. Genera il codice `HttpClient` Java con `.version(HTTP_1_1)` e l'URL corretto
