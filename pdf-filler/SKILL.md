---
name: pdf-filler
description: >
  Workflow autonomo per compilare PDF con schema pdfme. Usa questa skill quando l utente vuole:
  creare campi su un PDF tramite https://playground.pdfme.com, generare fake_data.json dai campi
  definiti nel schema.json esportato dal playground, compilare un PDF con dati reali, o creare
  un API HTTP per la compilazione programmatica.
  Triggera anche se l utente dice: "voglio compilare un PDF", "ho un schema.json di pdfme",
  "genera il pdf dai dati", "pdf filler", "usa il playground pdfme", "compila il template pdf".
---

# PDF Filler Skill (pdfme playground)

L agente usa pdfme come formato schema. Non serve nessuna API key esterna.

Tutto viene prodotto nella **CWD** (cartella corrente dove si trova lo schema.json).

Flusso:
1. L utente crea i campi su https://playground.pdfme.com e esporta `schema.json`
2. Trova `schema.json` e il PDF template nella CWD
3. Genera `fake_data.json` dai valori `content` dello schema
4. Review con l utente
5. Copia nella CWD: `pdf_filler_api.py`, `start_api.sh`, `fill_pdf.sh`, `stop_api.sh`
6. `bash start_api.sh` — avvia l API in ascolto
7. `bash fill_pdf.sh --data fake_data.json` — chiama l API HTTP
8. `bash stop_api.sh` — ferma l API
9. Verifica finale obbligatoria

---

## Dipendenze

```bash
python3 -c "import fitz"    2>/dev/null || pip install pymupdf
python3 -c "import fastapi" 2>/dev/null || pip install fastapi "uvicorn[standard]"
```

---

## FASE 1 — Scegli il metodo per creare lo schema.json

Chiedi all utente quale dei due metodi preferisce:

**Metodo A — Automatico** (PDF con spazi vuoti, box o underline): vai a FASE 1-BIS
**Metodo B — Manuale con playground** (controllo totale): vai a FASE 1

---

## FASE 1 — Metodo B: playground.pdfme.com

Spiega all utente:

> 1. Vai su **https://playground.pdfme.com**
> 2. Nella tab **Designer**, clicca l icona upload -> carica il tuo PDF come sfondo (basePdf)
> 3. Usa il pannello a sinistra per aggiungere campi **Text** nelle posizioni desiderate
> 4. Per ogni campo imposta: **Name** (es. `Date`, `BilledTo`, `Total`), fontSize, allineamento, colore
> 5. Clicca **Download Template** (o copia il JSON dal pannello JSON) -> salva come `schema.json` nella CWD
>
> Il JSON ha questo formato:
> ```json
> {
>   "schemas": [[
>     { "type": "text", "name": "Date", "position": {"x":164,"y":20},
>       "width":43, "height":6, "fontSize": 12, "content": "02/02/2020" },
>     { "type": "text", "name": "Total", "position": {"x":150,"y":199},
>       "width":38, "height":9, "fontSize": 15,
>       "alignment": "center", "fontColor": "#09436d", "content": "$700" }
>   ]],
>   "basePdf": "data:application/pdf;base64,<base64_del_tuo_pdf>",
>   "pdfmeVersion": "6.1.2"
> }
> ```
>
> **Nota**: se `basePdf` e `__PDFME_ASSET__:asset_1` (copia interna del playground),
> tieni anche il file PDF originale nella CWD; l API lo trovera automaticamente.

---

## FASE 1-BIS — Metodo A: rilevamento automatico dei campi vuoti

Usa questa fase quando l utente ha un PDF con:
- **Widget AcroForm nativi** (moduli ufficiali, form governativi, PDF/A compilabili) → strategia piu affidabile
- **Box rettangolari o linee** disegnate (form grafici senza AcroForm)
- **Pattern "Etichetta: [spazio]"** sulla stessa riga

### Step 1: esegui detect_fields.py

```bash
python3 /home/valerio/.agents/skills/pdf-filler/scripts/detect_fields.py \
  --pdf /CWD/template.pdf \
  --schema /CWD/schema.json \
  --verbose
```

Strategie applicate in ordine di priorità:
- **Strategia 0 — AcroForm** (`page.widgets()`): campi PDF nativi con nome e posizione ufficiali. Se trovati, le altre strategie vengono saltate. Il nome campo viene preso dal testo label vicino (es. `COGNOME`, `DATA_NASCITA`) oppure dall ultimo segmento del nome XFA.
- **Strategia 1 — Drawing**: rettangoli vuoti e linee orizzontali disegnate nel PDF.
- **Strategia 2 — Label gap**: testo che finisce con `:` seguito da spazio bianco.

Output:
- Scrive `schema.json` con `basePdf` embedded in base64 (no file PDF separato necessario)
- Stampa su stdout il report JSON dei campi rilevati con `name`, `label`, `source`, `position`

### Step 2: analizza il report (sei tu l LLM)

Leggi il JSON stampato su stdout. Per ogni campo hai:
```json
{
  "name":     "nome_automatico",
  "label":    "testo etichetta vicina (es: 'Nome', 'Data di nascita')",
  "source":   "drawing | label_gap",
  "page":     0,
  "position": {"x": 20.5, "y": 45.2},
  "width":    80.0,
  "height":   6.5
}
```

Migliora i `name` se necessario (es. `field_3` → `cognome`, `field_4` → `data_nascita`).
Mostra all utente i campi rilevati e chiedi conferma prima di proseguire.

Se il rilevamento e parziale o impreciso, suggerisci il Metodo B (playground).

### Step 3: genera fake_data.json

Basandoti sulle label e sui nomi dei campi, genera `fake_data.json` con valori congruenti:

```json
{
  "nome":          "Mario",
  "cognome":       "Rossi",
  "data_nascita":  "15/03/1985",
  "codice_fiscale":"RSSMRA85C15H501Z",
  "indirizzo":     "Via Roma 42, Milano",
  "email":         "mario.rossi@example.com"
}
```

Regole per i valori fake:
- **date**: formato italiano GG/MM/AAAA
- **importi**: con simbolo valuta e separatore migliaia (es. `€ 1.250,00`)
- **codici fiscali/P.IVA**: valori plausibili ma inventati
- **nomi**: italiani realistici
- **testi lunghi**: frasi di senso compiuto, non Lorem Ipsum

---

## FASE 2 — Trova schema.json e CWD

Cerca `schema.json` con `file_search`. La CWD di lavoro e la cartella che lo contiene.
Tutti i file generati vanno in questa cartella.

Se non esiste ancora `schema.json`:
- Metodo A (automatico) → esegui FASE 1-BIS
- Metodo B (manuale) → invita l utente a seguire le istruzioni della FASE 1

---

## FASE 3 — Genera fake_data.json (sei tu l LLM)

Leggi `schema.json` ed estrai il `content` di ogni campo come valore di esempio.

### fake_data.json
```json
{
  "Date":          "02/02/2020",
  "No":            "123456789",
  "BilledTo":      "Thynk Unlimited\n23 Anywhere St., Any City, ST 12345",
  "From":          "Howard Ong\nhello@reallygreatsite.com",
  "Item1":         "Consulenza sviluppo",
  "Quantity1":     "2",
  "Price1":        "150",
  "Amount1":       "300",
  "Total":         "300",
  "PaymentMethod": "Banca Esempio\nIBAN: IT12 3456 7890",
  "Note":          "Pagamento entro 30 giorni dalla data fattura."
}
```

Regole:
- Le chiavi sono i `name` dei campi nello schema (case-sensitive, esatte)
- I valori sono il `content` dello schema (gia realistici di default)
- Campi multiriga usano `\n` (come nel content originale)
- Personalizza i valori per renderli piu realistici se il content e generico

---

## FASE 4 — Review

Mostra `fake_data.json`. Chiedi conferma o modifiche.
Non proseguire senza conferma esplicita.

---

## FASE 5 — Copia gli script nella CWD

Copia i tre script di controllo nella dir del progetto:

```bash
SKILL=/home/valerio/.agents/skills/pdf-filler
CWD=/percorso/cartella

cp "$SKILL/scripts/start_api.sh" "$CWD/"
cp "$SKILL/scripts/stop_api.sh"  "$CWD/"
cp "$SKILL/scripts/fill_pdf.sh"  "$CWD/"
chmod +x "$CWD/start_api.sh" "$CWD/stop_api.sh" "$CWD/fill_pdf.sh"
```

> `start_api.sh` copia da solo Dockerfile, docker-entrypoint.sh e scripts/ Python nella CWD al primo avvio — non serve copiarli a mano.

---

## FASE 6 — Avvia l API

```bash
cd /CWD
bash start_api.sh
```

Primo avvio — cosa succede automaticamente:
1. Copia `Dockerfile`, `docker-entrypoint.sh`, `scripts/pdf_filler_api.py`, `scripts/detect_fields.py` nella CWD
2. Builda l immagine `pdf-filler` con gli script Python baked-in
3. Avvia il container montando la CWD come `/data` (legge schema.json + PDF)
4. Attende `/health`
5. Genera `fake_data.json` da `GET /sample`
6. Smoke test `POST /fill` → `compilato_test.pdf`
7. Stampa URL locale + IP di rete per accesso remoto

Avvii successivi — l immagine è già buildata, riparte in secondi.

Opzioni:
```bash
bash start_api.sh --schema mio_schema.json   # schema con nome diverso
bash start_api.sh --port 9000                # porta custom
bash start_api.sh --workers 4               # multi-processo
bash start_api.sh --rebuild                  # forza rebuild immagine
```

---

## FASE 7 — Genera il PDF

```bash
# con curl
curl -X POST http://127.0.0.1:8765/fill \
  -H "Content-Type: application/json" \
  -d @fake_data.json \
  -o compilato.pdf

# oppure con lo script
bash fill_pdf.sh --data fake_data.json --output compilato.pdf
```

Endpoint utili:
- `GET /fields`  → lista campi con nome, fontSize, alignment, posizione
- `GET /sample`  → JSON pronto da usare come corpo POST /fill
- `GET /health`  → stato API + info schema

---

## FASE 8 — Ferma l API

```bash
cd /CWD && bash stop_api.sh
```

---

## FASE 9 — VERIFICA FINALE (OBBLIGATORIA)

```bash
# 1. File presenti
ls -lh /CWD/schema.json /CWD/fake_data.json \
        /CWD/start_api.sh /CWD/fill_pdf.sh \
        /CWD/stop_api.sh /CWD/compilato.pdf

# 2. PDF non vuoto
SIZE=$(wc -c < /CWD/compilato.pdf)
[[ $SIZE -gt 1000 ]] && echo "PDF OK ($SIZE bytes)" || echo "ERRORE: PDF troppo piccolo"

# 3. Campi disponibili
curl -s http://127.0.0.1:8765/fields | python3 -m json.tool | head -30
```

Se la verifica fallisce, diagnostica e correggi prima di dichiarare il completamento.

---

## Tipi di campo supportati

| Tipo pdfme     | Supporto Python API | Note |
|----------------|---------------------|------|
| `text`         | Completo            | fontSize, fontColor, alignment, lineHeight, characterSpacing |
| `image`        | Non supportato      | Ignorato silenziosamente |
| Altri tipi     | Non supportati      | Ignorati silenziosamente |

---

## Uso autonomo futuro (spiega all utente)

Setup completato. Da adesso per generare nuovi PDF:

```bash
cd /CWD

# Avvia API (una volta sola per sessione)
bash start_api.sh

# Genera tanti PDF quanti ne vuoi con dati diversi
bash fill_pdf.sh --data dati_cliente_1.json --output cliente_1.pdf
bash fill_pdf.sh --data dati_cliente_2.json --output cliente_2.pdf

# Oppure via curl direttamente
curl -X POST http://127.0.0.1:8765/fill \
  -H "Content-Type: application/json" \
  -d '{"Date":"15/06/2025","Total":"1200"}' \
  --output fattura.pdf

# Ferma API quando hai finito
bash stop_api.sh
```

---

## MCP server (integrazione diretta con Copilot / CLI)

Il server MCP espone i tool direttamente alla skill — zero comandi shell, zero PID file.
Gira sull'host via stdio; internamente lancia i comandi Docker.

### Installazione

```bash
# unica dipendenza host (il resto è dentro Docker)
pip install "mcp[cli]"

# build immagine Docker (una volta sola)
docker build -t pdf-filler /home/valerio/.agents/skills/pdf-filler/
```

### Configurazione VS Code

Aggiungi a `.vscode/mcp.json` nella workspace (o copia il file dalla skill):

```json
{
  "servers": {
    "pdf-filler": {
      "type": "stdio",
      "command": "python3",
      "args": ["/home/valerio/.agents/skills/pdf-filler/mcp_server.py"]
    }
  }
}
```

```bash
# oppure copia il template già pronto
cp /home/valerio/.agents/skills/pdf-filler/vscode-mcp.json .vscode/mcp.json
```

### Tool disponibili

| Tool | Cosa fa |
|---|---|
| `detect_fields(pdf_path)` | Analizza il PDF → ritorna campi JSON + scrive schema.json |
| `start_api(data_dir)` | Avvia container API, attende /health, ritorna stato |
| `stop_api()` | Ferma e rimuove il container |
| `health()` | Stato container + info template caricato |
| `get_fields()` | Dettagli campi (fontSize, position, alignment…) |
| `get_sample()` | JSON campione pronto per fill |
| `fill_pdf(data, output_path)` | Compila PDF + salva file, ritorna dimensione |

### Flusso tipico con MCP

La skill (o tu in chat) può ora fare:

```
1. detect_fields("/path/modulo.pdf")          → ottieni campi + schema.json
2. start_api("/path/dir-con-schema")           → container su porta 8765
3. get_sample()                                → JSON con valori default
4. fill_pdf({"Nome": "Mario", ...}, "/path/out.pdf")  → PDF compilato
5. stop_api()                                  → container rimosso
```

---

## Docker — API con schema e PDF montati da directory

L'immagine Docker ha i Python scripts **baked-in** (nessuna dipendenza locale).
L'utente monta solo la propria directory con `schema.json` + PDF template.

### Un solo comando — deploy.sh

```bash
bash /home/valerio/.agents/skills/pdf-filler/scripts/deploy.sh
```

Quello che fa in automatico:
1. Builda l'immagine `pdf-filler` (solo la prima volta)
2. Avvia il container montando la dir corrente come `/data`
3. Attende che `/health` risponda
4. Genera `fake_data.json` da `GET /sample` (se non esiste)
5. Smoke test `POST /fill` → `compilato_test.pdf`
6. Stampa URL locale + tutti gli IP di rete

```
╔═══════════════════════════════════════════════════════════════╗
║  pdf-filler API in esecuzione                                 ║
╠═══════════════════════════════════════════════════════════════╣
║  Locale  : http://127.0.0.1:8765/fill                        ║
║  Docs    : http://127.0.0.1:8765/docs                        ║
║  Rete    : http://192.168.1.50:8765/fill                     ║
╠═══════════════════════════════════════════════════════════════╣
║  Compila : curl -X POST http://IP:8765/fill -d @fake_data.json║
║  Ferma   : docker rm -f pdf-filler-api                       ║
╚═══════════════════════════════════════════════════════════════╝
```

### Opzioni

```bash
bash deploy.sh --data-dir /path/mia/dir   # dir diversa dalla CWD
bash deploy.sh --schema modulo.json        # schema con nome diverso
bash deploy.sh --port 9000                 # porta custom
bash deploy.sh --workers 4                 # multi-processo
bash deploy.sh --rebuild                   # forza rebuild immagine
```

### Rilevamento automatico campi (detect_fields.py)

```bash
# run & exit — analizza il PDF e scrive schema.json nella stessa dir
docker run --rm -v $(pwd):/data pdf-filler detect \
  --pdf /data/template.pdf --schema /data/schema.json --verbose
```

### Compilare il PDF

```bash
# da locale
curl -X POST http://127.0.0.1:8765/fill \
  -H "Content-Type: application/json" \
  -d @fake_data.json \
  -o compilato.pdf

# da remoto (stessa rete)
curl -X POST http://192.168.1.50:8765/fill \
  -H "Content-Type: application/json" \
  -d @fake_data.json \
  -o compilato.pdf
```

### Fermare il container

```bash
docker rm -f pdf-filler-api
```

---

## Client Java (esempio pronto)

L API serve **HTTP/1.1** (uvicorn con `http="h11"`).
`java.net.http.HttpClient` tenta HTTP/2 per default: va forzato a `HTTP_1_1`.

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;

public class PdfFillerClient {

    private static final String API_URL = "http://127.0.0.1:8765/fill";

    public static void main(String[] args) throws Exception {
        String inputJson = args.length > 0 ? args[0] : "fake_data.json";
        String outputPdf = args.length > 1 ? args[1] : "output.pdf";

        String jsonBody = Files.readString(Path.of(inputJson));

        // IMPORTANTE: forzare HTTP_1_1 — uvicorn non supporta HTTP/2 di default
        HttpClient client = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .build();

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(API_URL))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();

        HttpResponse<byte[]> response =
                client.send(request, HttpResponse.BodyHandlers.ofByteArray());

        if (response.statusCode() != 200) {
            System.err.println("Errore HTTP " + response.statusCode());
            System.err.println(new String(response.body()));
            System.exit(1);
        }

        Files.write(Path.of(outputPdf), response.body());
        System.out.println("PDF salvato: " + outputPdf + "  (" + response.body().length + " bytes)");
    }
}
```

Compilazione e uso:
```bash
# Ottieni il JSON di esempio
curl -s http://127.0.0.1:8765/sample > fake_data.json

# Compila ed esegui
javac PdfFillerClient.java
java PdfFillerClient fake_data.json output.pdf
```

---

## Gestione errori

| Errore | Causa | Soluzione |
|--------|-------|-----------|
| `ModuleNotFoundError: fitz` | pymupdf mancante | `pip install pymupdf` |
| `ModuleNotFoundError: fastapi` | fastapi mancante | `pip install fastapi uvicorn` |
| `No PDF template found` | basePdf e asset reference, nessun .pdf in CWD | Aggiungi il PDF template nella CWD |
| `API non risponde` | porta occupata o crash | Controlla log, cambia `--port` |
| Testo fuori posizione | coordinate errate nel schema | Riesporta schema dal playground |
| Java `IOException: HTTP/2` o `ProtocolException` | HttpClient tenta HTTP/2 | Aggiungi `.version(HttpClient.Version.HTTP_1_1)` |
