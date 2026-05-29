#!/usr/bin/env bash
# stop_api.sh — Ferma il container Docker pdf-filler-api.
#
# Uso:
#   bash stop_api.sh

set -euo pipefail

CONTAINER="pdf-filler-api"

if docker inspect "$CONTAINER" &>/dev/null 2>&1; then
  docker rm -f "$CONTAINER" >/dev/null
  echo "[stop_api.sh] Container '${CONTAINER}' fermato e rimosso."
else
  echo "[stop_api.sh] Container '${CONTAINER}' non trovato (già fermato?)."
fi
