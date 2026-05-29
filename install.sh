#!/usr/bin/env bash
# install.sh — Installa la skill pdf-filler sotto ~/.agents/skills/
#
# Uso:
#   bash install.sh
#
# Installa in: ~/.agents/skills/pdf-filler/

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${REPO_DIR}/pdf-filler"
DEST="${HOME}/.agents/skills/pdf-filler"

echo ">>> Installazione pdf-filler skill"
echo "    Sorgente : ${SOURCE}"
echo "    Destinazione : ${DEST}"
echo ""

# crea la dir di destinazione se non esiste
mkdir -p "$DEST"

# copia tutto (sovrascrive i file esistenti, esclude __pycache__)
rsync -av --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "${SOURCE}/" "${DEST}/"

# rendi eseguibili gli script shell
chmod +x "${DEST}/scripts/start_api.sh" \
         "${DEST}/scripts/stop_api.sh" \
         "${DEST}/scripts/fill_pdf.sh" \
         "${DEST}/docker-entrypoint.sh"

echo ""
echo ">>> Installazione completata."
echo ""
echo "Come usarla:"
echo "  1. Copia gli script nella dir del tuo progetto:"
echo "     cp ${DEST}/scripts/start_api.sh ."
echo "     cp ${DEST}/scripts/stop_api.sh  ."
echo "     cp ${DEST}/scripts/fill_pdf.sh  ."
echo ""
echo "  2. Avvia l'API (richiede schema.json nella dir corrente):"
echo "     bash start_api.sh"
echo ""
echo "  3. Compila il PDF:"
echo "     bash fill_pdf.sh --data fake_data.json --output compilato.pdf"
