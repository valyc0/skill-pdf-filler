#!/usr/bin/env python3
"""
detect_fields.py — Analizza un PDF e rileva i campi compilabili.

Strategie di rilevamento (in ordine di priorità):
  0. Widget AcroForm nativi  (page.widgets())            → campi PDF ufficiali
  1. Rettangoli/linee grafiche disegnate                 → box e underline di form
  2. Pattern "Etichetta: [spazio vuoto]" sulla stessa riga

Output:
  - stdout : report JSON con i campi rilevati
  - file   : schema.json in formato pdfme (pronto per pdf_filler_api.py)

Uso:
    python3 detect_fields.py --pdf template.pdf
    python3 detect_fields.py --pdf template.pdf --schema schema.json --verbose

Dipendenze: pip install pymupdf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("Dipendenza mancante. Installa con:\n  pip install pymupdf")

# ── Costanti ──────────────────────────────────────────────────────────────────

PT2MM          = 0.352778
MIN_FIELD_W_MM = 10.0
MIN_FIELD_H_MM = 3.0
LABEL_SEARCH_LEFT_PT = 170.0   # quanti pt a sinistra cerco la label
Y_TOLERANCE_PT = 6.0
EMPTY_GAP_PT   = 8.0


def _pt2mm(v: float) -> float:
    return round(v * PT2MM, 2)


def _snake(text: str) -> str:
    t = text.strip().rstrip(":").strip()
    t = re.sub(r"[^a-zA-Z0-9\s_]", "", t)
    t = re.sub(r"\s+", "_", t.strip())
    return t[:40] or "field"


def _short_name(xfa_name: str) -> str:
    """
    Da 'principal[0].master[0].cognome[0]' → 'cognome'
    Da semplice 'COGNOME' → 'COGNOME'
    """
    parts = re.split(r"[.\[\]]+", xfa_name)
    parts = [p for p in parts if p and not p.isdigit()]
    return parts[-1] if parts else xfa_name


def _nearby_label(page_spans: list[dict], rect: fitz.Rect,
                  y_tol: float, search_left: float) -> str:
    cy = (rect.y0 + rect.y1) / 2
    best_text, best_dist = "", float("inf")
    for sp in page_spans:
        sr = fitz.Rect(sp["bbox"])
        sc_y = (sr.y0 + sr.y1) / 2
        if abs(sc_y - cy) <= y_tol and sr.x1 <= rect.x0 + 2 and sr.x1 >= rect.x0 - search_left:
            dist = rect.x0 - sr.x1
            if 0 <= dist < best_dist:
                best_dist = dist
                best_text = sp["text"].strip()
    return best_text


# ── Strategia 0: AcroForm widget nativi ──────────────────────────────────────

def _detect_acroform(page: fitz.Page, page_spans: list[dict], verbose: bool) -> list[dict]:
    """
    Legge i widget AcroForm (Text e CheckBox). E' la strategia piu' affidabile
    perche' usa i metadati ufficiali del PDF.
    Per PDF con nomi XFA lunghi cerca il testo label vicino al campo.
    """
    results = []
    SUPPORTED = {fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX,
                 fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX}

    for w in page.widgets():
        if w.field_type not in SUPPORTED:
            continue
        if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            continue  # skip checkbox, non compilabili come testo

        rect = fitz.Rect(w.rect)
        raw  = w.field_name or ""

        # Prova prima il testo label vicino
        label = _nearby_label(page_spans, rect, Y_TOLERANCE_PT, LABEL_SEARCH_LEFT_PT)

        # Nome campo: label vicina, oppure ultima parte del nome XFA
        if label:
            name = _snake(label)
        else:
            name = _snake(_short_name(raw))

        entry = {
            "source":   "acroform",
            "label":    label or _short_name(raw),
            "name":     name,
            "position": {"x": _pt2mm(rect.x0), "y": _pt2mm(rect.y0)},
            "width":    _pt2mm(rect.width),
            "height":   _pt2mm(rect.height),
        }
        results.append(entry)

        if verbose:
            print(f"  [acroform] {entry['name']!r:30s}  "
                  f"pos=({entry['position']['x']},{entry['position']['y']})  "
                  f"label={label!r}", file=sys.stderr)

    return results


# ── Strategia 1: elementi grafici disegnati ───────────────────────────────────

def _detect_drawings(page: fitz.Page, page_spans: list[dict], verbose: bool) -> list[dict]:
    results = []
    min_w = MIN_FIELD_W_MM / PT2MM
    min_h = MIN_FIELD_H_MM / PT2MM

    for path in page.get_drawings():
        rect = path.get("rect")
        if rect is None:
            continue
        rect = fitz.Rect(rect)
        w, h = rect.width, rect.height

        is_underline = (h < 3.0 and w >= min_w)
        fill = path.get("fill")
        is_box = (w >= min_w and h >= min_h and
                  (fill is None or fill == (1, 1, 1) or fill == [1, 1, 1]))

        if not (is_underline or is_box):
            continue

        # Salta se contiene gia' testo (non e' un campo vuoto)
        expanded = fitz.Rect(rect.x0-2, rect.y0-2, rect.x1+2, rect.y1+2)
        if any(fitz.Rect(sp["bbox"]).intersects(expanded) and sp["text"].strip()
               for sp in page_spans):
            continue

        label = _nearby_label(page_spans, rect, Y_TOLERANCE_PT, LABEL_SEARCH_LEFT_PT / PT2MM)

        if is_underline:
            field_rect = fitz.Rect(rect.x0, rect.y0 - 12, rect.x1, rect.y1)
        else:
            field_rect = rect

        entry = {
            "source":   "drawing",
            "label":    label,
            "name":     _snake(label) if label else f"field_{len(results)+1}",
            "position": {"x": _pt2mm(field_rect.x0), "y": _pt2mm(field_rect.y0)},
            "width":    _pt2mm(field_rect.width),
            "height":   _pt2mm(field_rect.height),
        }
        results.append(entry)

        if verbose:
            print(f"  [drawing]  {entry['name']!r:30s}  "
                  f"pos=({entry['position']['x']},{entry['position']['y']})  "
                  f"label={label!r}", file=sys.stderr)

    return results


# ── Strategia 2: pattern "Label: [spazio]" ───────────────────────────────────

def _detect_label_gaps(page: fitz.Page, page_spans: list[dict], verbose: bool) -> list[dict]:
    results = []
    page_w = page.rect.width
    min_w  = MIN_FIELD_W_MM / PT2MM

    rows: dict[int, list[dict]] = {}
    for sp in page_spans:
        if not sp["text"].strip():
            continue
        sr    = fitz.Rect(sp["bbox"])
        y_key = int((sr.y0 + sr.y1) / 2 / Y_TOLERANCE_PT)
        rows.setdefault(y_key, []).append(sp)

    for spans in rows.values():
        spans.sort(key=lambda s: fitz.Rect(s["bbox"]).x0)
        for i, sp in enumerate(spans):
            txt = sp["text"].strip()
            if not (txt.endswith(":") or txt.endswith("：")):
                continue
            sr = fitz.Rect(sp["bbox"])
            next_x0 = page_w
            for j in range(i + 1, len(spans)):
                nsr = fitz.Rect(spans[j]["bbox"])
                if abs((nsr.y0+nsr.y1)/2 - (sr.y0+sr.y1)/2) <= Y_TOLERANCE_PT:
                    next_x0 = nsr.x0
                    break
            gap = next_x0 - sr.x1
            if gap < EMPTY_GAP_PT + min_w:
                continue
            field_x0 = sr.x1 + 2
            field_x1 = next_x0 - 2 if next_x0 < page_w else min(sr.x1 + 80, page_w - 5)
            if (field_x1 - field_x0) < min_w:
                continue
            label = txt.rstrip(":").strip()
            entry = {
                "source":   "label_gap",
                "label":    label,
                "name":     _snake(label),
                "position": {"x": _pt2mm(field_x0), "y": _pt2mm(sr.y0)},
                "width":    _pt2mm(field_x1 - field_x0),
                "height":   _pt2mm(sr.y1 - sr.y0) or 5.0,
            }
            results.append(entry)
            if verbose:
                print(f"  [label_gap]{entry['name']!r:30s}  "
                      f"gap={gap:.0f}pt  label={label!r}", file=sys.stderr)

    return results


# ── Deduplicazione ────────────────────────────────────────────────────────────

def _deduplicate(fields: list[dict]) -> list[dict]:
    priority = {"acroform": 0, "drawing": 1, "label_gap": 2}
    fields_s  = sorted(fields, key=lambda f: priority.get(f["source"], 9))
    kept: list[dict] = []
    for f in fields_s:
        fr = fitz.Rect(
            f["position"]["x"] / PT2MM, f["position"]["y"] / PT2MM,
            (f["position"]["x"] + f["width"]) / PT2MM,
            (f["position"]["y"] + f["height"]) / PT2MM,
        )
        if not any(
            (fr & fitz.Rect(
                k["position"]["x"] / PT2MM, k["position"]["y"] / PT2MM,
                (k["position"]["x"] + k["width"]) / PT2MM,
                (k["position"]["y"] + k["height"]) / PT2MM,
            )).width > 5
            for k in kept
        ):
            kept.append(f)
    return kept


# ── Numerazione nomi duplicati ─────────────────────────────────────────────────

def _unique_names(fields: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for f in fields:
        n = f["name"]
        cnt = seen.get(n, 0)
        seen[n] = cnt + 1
        if cnt > 0:
            f["name"] = f"{n}_{cnt + 1}"
    return fields


# ── Entry point ───────────────────────────────────────────────────────────────

def detect(pdf_path: Path, verbose: bool = False) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    all_fields: list[dict] = []

    for page_idx, page in enumerate(doc):
        if verbose:
            print(f"\n[detect] Pagina {page_idx + 1}", file=sys.stderr)

        text_dict  = page.get_text("dict")
        page_spans = [
            sp
            for block in text_dict.get("blocks", [])
            if block.get("type") == 0
            for line in block.get("lines", [])
            for sp in line.get("spans", [])
            if sp.get("text", "").strip()
        ]

        page_fields: list[dict] = []

        acroform = _detect_acroform(page, page_spans, verbose)
        if acroform:
            # Se ci sono widget AcroForm, salto le strategie piu' deboli
            page_fields = acroform
        else:
            page_fields += _detect_drawings(page, page_spans, verbose)
            page_fields += _detect_label_gaps(page, page_spans, verbose)
            page_fields  = _deduplicate(page_fields)

        page_fields = _unique_names(page_fields)
        for f in page_fields:
            f["page"] = page_idx

        all_fields.extend(page_fields)

    doc.close()
    return all_fields


def build_schema(pdf_path: Path, fields: list[dict]) -> dict:
    import base64
    b64 = base64.b64encode(pdf_path.read_bytes()).decode()

    pages: dict[int, list] = {}
    for f in fields:
        pages.setdefault(f.get("page", 0), []).append(f)

    schema_pages = []
    for p in sorted(pages.keys()):
        schema_pages.append([
            {
                "type":     "text",
                "name":     f["name"],
                "position": f["position"],
                "width":    f["width"],
                "height":   max(f["height"], 5.0),
                "fontSize": 12,
                "content":  "",
            }
            for f in pages[p]
        ])

    return {
        "schemas":      schema_pages,
        "basePdf":      f"data:application/pdf;base64,{b64}",
        "pdfmeVersion": "6.1.2",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rileva campi compilabili in un PDF (AcroForm, box, label:gap)."
    )
    parser.add_argument("--pdf",     required=True,         help="PDF da analizzare")
    parser.add_argument("--schema",  default="schema.json", help="Output schema.json")
    parser.add_argument("--verbose", action="store_true",   help="Log dettagliato")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"File non trovato: {pdf_path}")

    print(f"[detect_fields] Analisi: {pdf_path}", file=sys.stderr)
    fields = detect(pdf_path, verbose=args.verbose)

    if not fields:
        print("[detect_fields] Nessun campo rilevato automaticamente.", file=sys.stderr)
        print("[detect_fields] Usa https://playground.pdfme.com per mappare i campi manualmente.", file=sys.stderr)
        sys.exit(1)

    # Statistiche per strategia
    by_src: dict[str, int] = {}
    for f in fields:
        by_src[f["source"]] = by_src.get(f["source"], 0) + 1
    print(f"[detect_fields] Campi rilevati: {len(fields)}", file=sys.stderr)
    for src, cnt in sorted(by_src.items()):
        print(f"  {src:12s}: {cnt}", file=sys.stderr)

    # Report JSON su stdout (letto dall LLM per generare fake_data.json)
    report = [
        {
            "name":     f["name"],
            "label":    f["label"],
            "source":   f["source"],
            "page":     f.get("page", 0),
            "position": f["position"],
            "width":    f["width"],
            "height":   f["height"],
        }
        for f in fields
    ]
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Scrivi schema.json
    schema      = build_schema(pdf_path, fields)
    schema_path = pdf_path.parent / args.schema
    schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[detect_fields] schema.json: {schema_path}", file=sys.stderr)
    print(f"[detect_fields] basePdf embedded ({len(schema['basePdf'])} chars)", file=sys.stderr)


if __name__ == "__main__":
    main()
