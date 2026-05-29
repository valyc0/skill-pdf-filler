#!/usr/bin/env python3
"""
pdf_filler_api.py — API HTTP locale per compilare PDF con schema pdfme.

Carica in memoria UNA SOLA VOLTA allo startup:
  - schema.json   (esportato da https://playground.pdfme.com)
  - PDF template  (base64 nel basePdf, oppure file .pdf nella CWD)

Endpoints:
  GET  /health   → stato server + info schema
  GET  /fields   → campi con dettagli (tipo, fontSize, alignment, ...)
  GET  /sample   → JSON pronto da usare come corpo POST /fill
  POST /fill     → accetta {"FieldName": "valore", ...} → ritorna PDF binario

Avvio:
    python3 pdf_filler_api.py
    python3 pdf_filler_api.py --schema schema.json --port 8765

Per carico massivo (multi-processo, ognuno con la propria cache in RAM):
    python3 pdf_filler_api.py --workers 4 --port 8765

Dipendenze:
    pip install pymupdf fastapi "uvicorn[standard]"
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

for _pkg, _install in [
    ("fitz",    "pymupdf"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn[standard]"),
]:
    try:
        __import__(_pkg)
    except ImportError:
        sys.exit(f"Pacchetto mancante. Installa con:\n  pip install {_install}")

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
import uvicorn

# ── Costanti ──────────────────────────────────────────────────────────────────

MM2PT = 2.8346

_ALIGN = {"left": 0, "center": 1, "right": 2, "justify": 3}

_FONT_MAP: list[tuple[tuple[str, ...], str]] = [
    (("arial", "helvetica", "helv", "sans"),  "helv"),
    (("times", "tiro", "roman", "serif"),      "tiro"),
    (("courier", "cour", "mono", "consolas"), "cour"),
    (("bold",),                                "tibo"),
]
_FONT_MAP_BOLD: list[tuple[tuple[str, ...], str]] = [
    (("arial", "helvetica", "helv", "sans"),  "hebo"),
    (("times", "tiro", "roman", "serif"),      "tibo"),
    (("courier", "cour", "mono", "consolas"), "cobo"),
]


# ── Cache (popolata una volta sola nel lifespan) ───────────────────────────────

@dataclass
class _TemplateCache:
    pdf_bytes:    bytes
    schema_pages: list[list[dict]]
    schema_raw:   dict
    source_info:  str
    # sample JSON pre-calcolato: {"FieldName": "default_content", ...}
    sample:       dict[str, str]


_CACHE: _TemplateCache | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _resolve_font(font_raw: str, bold: bool) -> str:
    name = font_raw.lower().split("+")[-1]
    mapping = _FONT_MAP_BOLD if bold else _FONT_MAP
    for keywords, builtin in mapping:
        if any(kw in name for kw in keywords):
            return builtin
    return "helv"


def _build_sample(schema_pages: list[list[dict]]) -> dict[str, str]:
    """Costruisce {"FieldName": "content_default"} da ogni campo text dello schema."""
    sample: dict[str, str] = {}
    for page in schema_pages:
        for field in page:
            if field.get("type") == "text":
                name = field.get("name", "")
                if name:
                    sample[name] = field.get("content", "")
    return sample


def _load_once(schema_path: Path) -> _TemplateCache:
    """Eseguita UNA SOLA VOLTA allo startup."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_pages: list[list[dict]] = schema.get("schemas", [[]])
    base_pdf: str = schema.get("basePdf", "")

    if isinstance(base_pdf, str) and base_pdf.startswith("data:"):
        _, b64 = base_pdf.split(",", 1)
        pdf_bytes   = base64.b64decode(b64)
        source_info = "base64 embedded in schema.json"
    else:
        cwd = schema_path.parent
        candidates = sorted(
            p for p in cwd.glob("*.pdf")
            if not p.stem.lower().startswith(("compilato", "output", "filled", "test"))
        )
        if not candidates:
            raise FileNotFoundError(
                f"Nessun PDF template trovato in {cwd}. "
                "Aggiungi il file .pdf oppure riesporta schema.json con il basePdf incluso."
            )
        pdf_bytes   = candidates[0].read_bytes()
        source_info = str(candidates[0])

    sample = _build_sample(schema_pages)
    n_text = len(sample)

    print(f"[pdf-filler-api] Template : {source_info}")
    print(f"[pdf-filler-api] PDF size : {len(pdf_bytes):,} bytes")
    print(f"[pdf-filler-api] Campi    : {n_text}")

    return _TemplateCache(
        pdf_bytes=pdf_bytes,
        schema_pages=schema_pages,
        schema_raw=schema,
        source_info=source_info,
        sample=sample,
    )


# ── PDF engine — CPU-bound, gira in thread pool ───────────────────────────────

def _fill_sync(pdf_bytes: bytes, schema_pages: list[list[dict]], data: dict) -> bytes:
    """
    Thread-safe: ogni chiamata apre una copia indipendente del documento
    dai bytes immutabili del template.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page_idx, fields in enumerate(schema_pages):
        if page_idx >= len(doc):
            doc.insert_page(page_idx)
        page = doc[page_idx]

        for field in fields:
            if field.get("type") != "text":
                continue

            name: str  = field.get("name", "")
            value: str = str(data.get(name, field.get("content", "") or ""))

            pos = field.get("position", {})
            x   = float(pos.get("x", 0)) * MM2PT
            y   = float(pos.get("y", 0)) * MM2PT
            w   = float(field.get("width",  40)) * MM2PT
            h   = float(field.get("height", 10)) * MM2PT

            rect        = fitz.Rect(x, y, x + w, y + h)
            font_size   = float(field.get("fontSize", 12))
            align       = _ALIGN.get(field.get("alignment", "left"), 0)
            color       = _hex_to_rgb(field.get("fontColor", "#000000"))
            line_height = float(field.get("lineHeight", 1.0))
            bold        = bool(field.get("bold", False))
            font_name   = _resolve_font(field.get("fontName", "helv"), bold)

            page.draw_rect(rect, color=None, fill=(1, 1, 1))

            if value:
                rc = page.insert_textbox(
                    rect, value,
                    fontsize=font_size,
                    fontname=font_name,
                    color=color,
                    align=align,
                    lineheight=line_height,
                )
                if rc < 0:
                    page.insert_textbox(
                        rect, value,
                        fontsize=max(6.0, font_size * 0.80),
                        fontname=font_name,
                        color=color,
                        align=align,
                        lineheight=line_height,
                    )

    result = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return result


# ── FastAPI app ───────────────────────────────────────────────────────────────

def create_app(schema_path: Path) -> FastAPI:
    global _CACHE

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        global _CACHE
        _CACHE = _load_once(schema_path)
        yield
        _CACHE = None

    app = FastAPI(
        title="PDF Filler API (pdfme)",
        description=(
            "Schema pdfme e PDF template caricati **una sola volta** allo startup. "
            "Ogni `POST /fill` riceve solo i valori dei campi e ritorna il PDF compilato. "
            "Usa `GET /sample` per ottenere un JSON di esempio pronto all uso."
        ),
        lifespan=lifespan,
    )

    def _get() -> _TemplateCache:
        if _CACHE is None:
            raise HTTPException(503, "Cache non pronta.")
        return _CACHE

    # ── GET /health ──────────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        c = _get()
        return {
            "status":       "ok",
            "schema":       str(schema_path),
            "text_fields":  len(c.sample),
            "pdf_bytes":    len(c.pdf_bytes),
            "template_src": c.source_info,
            "pdfmeVersion": c.schema_raw.get("pdfmeVersion", "unknown"),
        }

    # ── GET /fields ──────────────────────────────────────────────────────────

    @app.get(
        "/fields",
        summary="Dettagli di ogni campo (fontSize, alignment, fontColor, ...)",
    )
    def fields():
        c = _get()
        result = {}
        for page_idx, page in enumerate(c.schema_pages):
            for field in page:
                if field.get("type") == "text":
                    name = field.get("name", "")
                    result[name] = {
                        "page":      page_idx,
                        "default":   field.get("content", ""),
                        "fontSize":  field.get("fontSize", 12),
                        "alignment": field.get("alignment", "left"),
                        "fontColor": field.get("fontColor", "#000000"),
                        "position":  field.get("position", {}),
                        "width":     field.get("width"),
                        "height":    field.get("height"),
                    }
        return result

    # ── GET /sample ──────────────────────────────────────────────────────────

    @app.get(
        "/sample",
        summary="JSON di esempio pronto da usare come corpo di POST /fill",
        response_description='{"FieldName": "valore_default", ...}',
    )
    def sample():
        """
        Ritorna un JSON `{NomeCampo: valoreDefault}` con tutti i campi text
        dello schema e i rispettivi valori di default (campo `content`).

        Copialo, modifica i valori, e usalo direttamente come body di POST /fill.

        Utile per:
        - generare `fake_data.json` con `curl http://host:port/sample > fake_data.json`
        - scoprire i campi disponibili da un client Java/Go/etc.
        """
        return JSONResponse(_get().sample)

    # ── POST /fill ───────────────────────────────────────────────────────────

    @app.post(
        "/fill",
        summary="Compila il PDF con i dati forniti",
        responses={200: {"content": {"application/pdf": {}}, "description": "PDF compilato"}},
    )
    async def fill(data: dict):
        """
        Body: `{"FieldName": "valore", ...}`

        - I campi **non presenti** nel body usano il valore `content` dello schema.
        - I campi **non esistenti** nello schema vengono ignorati silenziosamente.
        - I valori multiriga usano `\\n`.

        Esempio minimo (solo i campi che vuoi sovrascrivere):
        ```json
        {"Date": "15/06/2025", "Total": "1.200,00", "BilledTo": "Mario Rossi"}
        ```

        La generazione gira in thread pool → l event loop rimane libero.
        """
        c = _get()
        try:
            filled = await asyncio.to_thread(_fill_sync, c.pdf_bytes, c.schema_pages, data)
        except Exception as exc:
            raise HTTPException(500, f"Errore compilazione: {exc}") from exc

        out_name = "compilato.pdf"
        return Response(
            content=filled,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
        )

    return app


# ── Variabile modulo (necessaria per uvicorn --workers) ───────────────────────
app: FastAPI | None = None


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global app

    parser = argparse.ArgumentParser(
        description="PDF Filler API — schema pdfme + PDF template caricati UNA VOLTA."
    )
    parser.add_argument("--schema",  default="schema.json", help="schema.json pdfme (default: schema.json)")
    parser.add_argument("--host",    default="127.0.0.1",   help="Host (default: 127.0.0.1)")
    parser.add_argument("--port",    default=8765, type=int, help="Porta (default: 8765)")
    parser.add_argument("--workers", default=1,   type=int, help="Worker uvicorn (>1 per carico massivo)")
    args = parser.parse_args()

    cwd         = Path.cwd()
    schema_path = cwd / args.schema

    print(f"[pdf-filler-api] CWD      : {cwd}")
    print(f"[pdf-filler-api] Schema   : {schema_path}  ({'OK' if schema_path.exists() else 'MANCANTE'})")
    print(f"[pdf-filler-api] Workers  : {args.workers}")
    print(f"[pdf-filler-api] Docs     : http://{args.host}:{args.port}/docs")
    print(f"[pdf-filler-api] Sample   : http://{args.host}:{args.port}/sample")
    print(f"[pdf-filler-api] Fill     : POST http://{args.host}:{args.port}/fill")

    app = create_app(schema_path)

    if args.workers > 1:
        uvicorn.run(
            "pdf_filler_api:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            http="h11",          # HTTP/1.1 esplicito — Java HttpClient default tenta HTTP/2
            log_level="warning",
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, http="h11", log_level="warning")


if __name__ == "__main__":
    main()
