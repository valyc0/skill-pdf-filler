#!/usr/bin/env bash
# start_api.sh — Copia i file Docker, builda l'immagine e avvia l'API.
#
# Uso:
#   bash start_api.sh [--schema schema.json] [--port 8765] [--workers 1] [--rebuild]
#
# Cosa fa:
#   1. Copia Dockerfile, docker-entrypoint.sh e scripts/ nella CWD (se non ci sono)
#   2. Builda l'immagine Docker pdf-filler da CWD (scripts Python baked-in)
#   3. Avvia container montando CWD come /data  (legge schema.json + PDF)
#   4. Attende /health
#   5. Genera fake_data.json da GET /sample (se non esiste)
#   6. Smoke test POST /fill → compilato_test.pdf
#   7. Stampa URL locale + IP di rete

set -euo pipefail

SKILL_DIR="/home/valerio/.agents/skills/pdf-filler"
SCHEMA="schema.json"
PORT=8765
WORKERS=1
REBUILD=false
CONTAINER="pdf-filler-api"
IMAGE="pdf-filler"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --schema)  SCHEMA="$2";  shift 2 ;;
    --port)    PORT="$2";    shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --rebuild) REBUILD=true; shift ;;
    *) echo "Opzione sconosciuta: $1" >&2; exit 1 ;;
  esac
done

# ── 1. Copia file Docker nella CWD ───────────────────────────────────────────
echo ">>> Copio file Docker dalla skill nella dir corrente..."
cp -n "${SKILL_DIR}/Dockerfile"             . 2>/dev/null && echo "    + Dockerfile"             || echo "    = Dockerfile (già presente)"
cp -n "${SKILL_DIR}/docker-entrypoint.sh"   . 2>/dev/null && echo "    + docker-entrypoint.sh"   || echo "    = docker-entrypoint.sh (già presente)"
mkdir -p scripts
cp -n "${SKILL_DIR}/scripts/pdf_filler_api.py" scripts/ 2>/dev/null && echo "    + scripts/pdf_filler_api.py" || echo "    = scripts/pdf_filler_api.py (già presente)"
cp -n "${SKILL_DIR}/scripts/detect_fields.py"  scripts/ 2>/dev/null && echo "    + scripts/detect_fields.py"  || echo "    = scripts/detect_fields.py (già presente)"

# ── 2. Prerequisiti ───────────────────────────────────────────────────────────
if [[ ! -f "$SCHEMA" ]]; then
  echo ""
  echo "ERRORE: $SCHEMA non trovato nella dir corrente." >&2
  echo "  • Esporta lo schema da https://playground.pdfme.com → Template → Export" >&2
  echo "  • Oppure rileva i campi automaticamente:" >&2
  echo "    docker run --rm -v \$(pwd):/data ${IMAGE} detect --pdf /data/template.pdf --schema /data/schema.json" >&2
  exit 1
fi

if ! command -v docker &>/dev/null; then
  echo "ERRORE: Docker non trovato." >&2; exit 1
fi

# ── 3. Build immagine ─────────────────────────────────────────────────────────
IMAGE_EXISTS=$(docker image inspect "$IMAGE" &>/dev/null 2>&1 && echo yes || echo no)
if [[ "$REBUILD" == true ]] || [[ "$IMAGE_EXISTS" == "no" ]]; then
  echo ""
  echo ">>> Build immagine '${IMAGE}' (scripts baked-in)..."
  docker build -t "$IMAGE" .
  echo ">>> Build completato."
else
  echo ">>> Immagine '${IMAGE}' già presente (usa --rebuild per rifarla)."
fi

# ── 4. Rimuovi container precedente ──────────────────────────────────────────
if docker inspect "$CONTAINER" &>/dev/null 2>&1; then
  echo ">>> Rimuovo container precedente..."
  docker rm -f "$CONTAINER" >/dev/null
fi

# ── 5. Avvia container (monta CWD come /data) ─────────────────────────────────
echo ""
echo ">>> Avvio container '${CONTAINER}'..."
echo "    Dati  : $(pwd) → /data"
echo "    Schema: /data/${SCHEMA}"
echo "    Porta : ${PORT}"

docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -v "$(pwd):/data" \
  -p "0.0.0.0:${PORT}:${PORT}" \
  "$IMAGE" \
  --schema  "/data/${SCHEMA}" \
  --port    "$PORT" \
  --host    "0.0.0.0" \
  --workers "$WORKERS" \
  > /dev/null

# ── 6. Attendi /health ────────────────────────────────────────────────────────
echo -n ">>> Attendo avvio API"
for i in $(seq 1 60); do
  sleep 0.5
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo " OK"
    break
  fi
  echo -n "."
  if [[ $i -eq 60 ]]; then
    echo ""
    echo "ERRORE: API non risponde dopo 30s." >&2
    docker logs "$CONTAINER" --tail 30 >&2
    exit 1
  fi
done

# ── 7. Genera fake_data.json ──────────────────────────────────────────────────
if [[ ! -f "fake_data.json" ]]; then
  echo ">>> Genero fake_data.json da GET /sample..."
  curl -sf "http://127.0.0.1:${PORT}/sample" -o fake_data.json
  echo "    Campi disponibili:"
  python3 -c "import json; [print(f'    • {k}') for k in json.load(open('fake_data.json'))]" 2>/dev/null \
    || cat fake_data.json
fi

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
echo ""
echo ">>> Smoke test POST /fill..."
HTTP=$(curl -sf \
  -X POST "http://127.0.0.1:${PORT}/fill" \
  -H "Content-Type: application/json" \
  -d "@fake_data.json" \
  -o "compilato_test.pdf" \
  -w "%{http_code}" 2>/dev/null || echo "000")

if [[ "$HTTP" == "200" ]]; then
  SIZE=$(wc -c < compilato_test.pdf)
  echo "    OK — compilato_test.pdf generato (${SIZE} byte)"
else
  echo "    ATTENZIONE: HTTP ${HTTP}" >&2
fi

# ── 9. URL di accesso ─────────────────────────────────────────────────────────
NETWORK_IPS=$(ip -4 addr show scope global 2>/dev/null \
  | awk '/inet / {sub("/.*","",$2); print $2}' \
  || hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$')

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  pdf-filler API in esecuzione                                    ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
printf "║  Locale  : http://127.0.0.1:%-36s║\n" "${PORT}/fill"
printf "║  Docs    : http://127.0.0.1:%-36s║\n" "${PORT}/docs"
for IP in $NETWORK_IPS; do
  printf "║  Rete    : http://%-47s║\n" "${IP}:${PORT}/fill"
done
echo "╠══════════════════════════════════════════════════════════════════╣"
printf "║  Compila : %-53s║\n" "bash fill_pdf.sh --data fake_data.json --output out.pdf"
printf "║  Ferma   : %-53s║\n" "bash stop_api.sh"
echo "╚══════════════════════════════════════════════════════════════════╝"
