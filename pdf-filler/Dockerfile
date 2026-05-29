# ── pdf-filler ─────────────────────────────────────────────────────────────────
# Immagine leggera Python con FastAPI + PyMuPDF per compilare PDF via schema pdfme.
#
# Build:
#   docker build -t pdf-filler .
#
# API (monta la dir con schema.json e il PDF template):
#   docker run --rm -v $(pwd):/data -p 8765:8765 pdf-filler
#
# Rilevamento automatico campi (AcroForm / box / label gap):
#   docker run --rm -v $(pwd):/data pdf-filler detect \
#     --pdf /data/template.pdf --schema /data/schema.json --verbose
#
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# dipendenze di sistema minime per PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmupdf-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# dipendenze Python
RUN pip install --no-cache-dir \
        pymupdf \
        fastapi \
        "uvicorn[standard]"

# copia gli script nell'immagine
COPY scripts/ /app/

# directory dati montata dall'utente (-v ./:/data)
WORKDIR /data

EXPOSE 8765

# Healthcheck: verifica che l'API risponda entro 30s
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8765/health || exit 1

# entrypoint wrapper: "detect" → detect_fields.py, altrimenti → pdf_filler_api.py
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["--schema", "/data/schema.json", "--port", "8765", "--host", "0.0.0.0"]
