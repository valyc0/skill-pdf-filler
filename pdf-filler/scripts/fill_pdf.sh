#!/usr/bin/env bash
# fill_pdf.sh — Chiama l'API HTTP passando solo i data JSON.
#
# PREREQUISITO: l'API deve essere già in esecuzione.
#   Avviala con:  bash start_api.sh
#   Fermala con:  bash stop_api.sh
#
# Uso:
#   bash fill_pdf.sh --data data.json [--output compilato.pdf] [opzioni]
#
# Opzioni:
#   --data       FILE    JSON con i valori da iniettare (obbligatorio)
#   --output     FILE    PDF di output (default: compilato.pdf)
#   --port       NUM     Porta API     (default: 8765)
#   --host       STR     Host API      (default: 127.0.0.1)
#   --api-url    URL     URL base API  (override --host e --port)

set -euo pipefail

DATA_FILE=""
OUTPUT="compilato.pdf"
PORT=8765
HOST="127.0.0.1"
API_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data)    DATA_FILE="$2"; shift 2 ;;
    --output)  OUTPUT="$2";    shift 2 ;;
    --port)    PORT="$2";      shift 2 ;;
    --host)    HOST="$2";      shift 2 ;;
    --api-url) API_URL="$2";   shift 2 ;;
    *) echo "Opzione sconosciuta: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$API_URL" ]] && API_URL="http://${HOST}:${PORT}"

# ── validazione ───────────────────────────────────────────────────────────────
if [[ -z "$DATA_FILE" ]]; then
  echo "Errore: --data <file.json> è obbligatorio" >&2
  echo "Uso: bash fill_pdf.sh --data fake_data.json --output compilato.pdf" >&2
  exit 1
fi
if [[ ! -f "$DATA_FILE" ]]; then
  echo "Errore: file non trovato: $DATA_FILE" >&2
  exit 1
fi

# ── verifica che l'API sia attiva ─────────────────────────────────────────────
if ! curl -sf "${API_URL}/health" > /dev/null 2>&1; then
  echo "Errore: l'API non risponde su ${API_URL}" >&2
  echo "Avviala prima con:  bash start_api.sh" >&2
  exit 1
fi

# ── chiamata POST /fill ───────────────────────────────────────────────────────
echo "[fill_pdf.sh] POST ${API_URL}/fill  (data: ${DATA_FILE})"

HTTP_CODE=$(curl -s -o "$OUTPUT" -w "%{http_code}" \
  -X POST "${API_URL}/fill" \
  -H "Content-Type: application/json" \
  --data-binary "@${DATA_FILE}")

if [[ "$HTTP_CODE" == "200" ]]; then
  SIZE=$(wc -c < "$OUTPUT")
  echo "[fill_pdf.sh] PDF salvato: ${OUTPUT}  (${SIZE} bytes)"
else
  echo "Errore: API ha risposto HTTP ${HTTP_CODE}" >&2
  cat "$OUTPUT" >&2
  rm -f "$OUTPUT"
  exit 1
fi
