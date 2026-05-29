#!/usr/bin/env python3
"""
mcp_server.py — MCP server per pdf-filler.

Espone tool che la skill/Copilot può chiamare direttamente (via stdio MCP).
Internamente usa Docker per isolare le dipendenze Python/pymupdf.

Tool disponibili:
  detect_fields  — analizza un PDF → ritorna campi + scrive schema.json
  start_api      — avvia il container API (monta la dir dei dati)
  stop_api       — ferma il container
  health         — stato container API
  get_fields     — lista campi del template caricato
  get_sample     — JSON campione pronto per /fill
  fill_pdf       — compila il PDF con dati → salva file

Configurazione VS Code (.vscode/mcp.json):
  {
    "servers": {
      "pdf-filler": {
        "type": "stdio",
        "command": "python3",
        "args": ["/home/valerio/.agents/skills/pdf-filler/mcp_server.py"]
      }
    }
  }

Dipendenze host (solo per questo server MCP):
    pip install "mcp[cli]"
Docker image:
    docker build -t pdf-filler /home/valerio/.agents/skills/pdf-filler/
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── costanti ──────────────────────────────────────────────────────────────────
DOCKER_IMAGE    = "pdf-filler"
CONTAINER_NAME  = "pdf-filler-api"
DEFAULT_PORT    = 8765

mcp = FastMCP("pdf-filler")


# ── helpers ───────────────────────────────────────────────────────────────────

def _image_exists() -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE],
        capture_output=True,
    )
    return r.returncode == 0


def _no_image_error() -> str:
    skill_dir = Path(__file__).parent
    return json.dumps({
        "error": f"Immagine Docker '{DOCKER_IMAGE}' non trovata.",
        "fix":   f"docker build -t {DOCKER_IMAGE} {skill_dir}",
    })


def _api_get(path: str, port: int) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read())


def _api_post(path: str, payload: bytes, port: int) -> bytes:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read()


def _network_urls(port: int) -> list[str]:
    """Ritorna gli URL raggiungibili dall'esterno (IP di rete, escluso loopback)."""
    import socket
    urls = []
    try:
        # hostname -I equivalente cross-platform
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                urls.append(f"http://{ip}:{port}")
    except Exception:
        pass
    return urls


# ── tool: detect_fields ───────────────────────────────────────────────────────

@mcp.tool()
def detect_fields(pdf_path: str, schema_path: str = "", verbose: bool = False) -> str:
    """
    Analizza un PDF e rileva automaticamente i campi compilabili.

    Strategie in ordine di priorità:
      0. AcroForm widget (page.widgets()) — moduli ufficiali, PDF governativi
      1. Rettangoli/linee grafiche — form grafici senza AcroForm
      2. Pattern "Etichetta: [spazio]" — PDF di testo semplice

    Scrive schema.json in formato pdfme e ritorna il report JSON dei campi.

    Args:
        pdf_path:    percorso assoluto del PDF da analizzare
        schema_path: dove salvare lo schema.json (default: stessa dir del PDF)
        verbose:     includi dettagli posizione nel report
    """
    pdf_abs  = os.path.abspath(pdf_path)
    if not os.path.isfile(pdf_abs):
        return json.dumps({"error": f"File non trovato: {pdf_abs}"})

    pdf_dir  = str(Path(pdf_abs).parent)
    pdf_name = Path(pdf_abs).name

    schema_abs  = os.path.abspath(schema_path) if schema_path else str(Path(pdf_dir) / "schema.json")
    schema_name = Path(schema_abs).name
    schema_dir  = str(Path(schema_abs).parent)

    if not _image_exists():
        return _no_image_error()

    # monta un volume se pdf e schema sono nella stessa dir, due altrimenti
    if pdf_dir == schema_dir:
        volumes = ["-v", f"{pdf_dir}:/data"]
        pdf_arg    = f"/data/{pdf_name}"
        schema_arg = f"/data/{schema_name}"
    else:
        volumes = [
            "-v", f"{pdf_dir}:/data/pdf:ro",
            "-v", f"{schema_dir}:/data/out",
        ]
        pdf_arg    = f"/data/pdf/{pdf_name}"
        schema_arg = f"/data/out/{schema_name}"

    cmd = ["docker", "run", "--rm", *volumes, DOCKER_IMAGE,
           "detect", "--pdf", pdf_arg, "--schema", schema_arg]
    if verbose:
        cmd.append("--verbose")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout: il container ha impiegato troppo"})

    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip() or "Errore detect_fields"})

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {"raw_output": result.stdout.strip()}

    report["schema_written"] = schema_abs
    return json.dumps(report, ensure_ascii=False, indent=2)


# ── tool: start_api ───────────────────────────────────────────────────────────

@mcp.tool()
def start_api(
    data_dir: str,
    schema: str = "schema.json",
    port: int = DEFAULT_PORT,
    workers: int = 1,
) -> str:
    """
    Avvia il container Docker pdf-filler come API HTTP.
    Monta data_dir come /data — deve contenere schema.json e il PDF template.

    Args:
        data_dir: directory con schema.json e PDF template
        schema:   nome del file schema nella dir (default: schema.json)
        port:     porta da esporre sull'host (default: 8765)
        workers:  numero di processi uvicorn (default: 1)
    """
    data_dir = os.path.abspath(data_dir)
    if not os.path.isdir(data_dir):
        return json.dumps({"error": f"Directory non trovata: {data_dir}"})
    if not _image_exists():
        return _no_image_error()

    # rimuovi eventuale container precedente
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)

    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "-v", f"{data_dir}:/data",
        "-p", f"{port}:{port}",
        DOCKER_IMAGE,
        "--schema", f"/data/{schema}",
        "--port", str(port),
        "--host", "0.0.0.0",
        "--workers", str(workers),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip()})

    container_id = result.stdout.strip()

    # attendi /health (max 20s)
    for _ in range(20):
        try:
            info = _api_get("/health", port)
            # raccoglie gli IP di rete raggiungibili dall'esterno
            network_urls = _network_urls(port)
            return json.dumps({
                "status":        "running",
                "container_id":  container_id[:12],
                "local_url":     f"http://127.0.0.1:{port}",
                "network_urls":  network_urls,
                "docs":          f"http://127.0.0.1:{port}/docs",
                "health":        info,
            }, ensure_ascii=False, indent=2)
        except Exception:
            time.sleep(1)

    return json.dumps({
        "status":       "started_health_timeout",
        "container_id": container_id[:12],
        "port":         port,
        "hint":         f"docker logs {CONTAINER_NAME}",
    })


# ── tool: stop_api ────────────────────────────────────────────────────────────

@mcp.tool()
def stop_api() -> str:
    """Ferma e rimuove il container pdf-filler API."""
    result = subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return json.dumps({"status": "stopped", "container": CONTAINER_NAME})
    return json.dumps({"error": result.stderr.strip() or "Container non trovato"})


# ── tool: health ──────────────────────────────────────────────────────────────

@mcp.tool()
def health(port: int = DEFAULT_PORT) -> str:
    """
    Controlla lo stato del container API.

    Args:
        port: porta dell'API (default: 8765)
    """
    try:
        info = _api_get("/health", port)
        return json.dumps({"status": "ok", "detail": info}, ensure_ascii=False, indent=2)
    except urllib.error.URLError as exc:
        return json.dumps({"status": "unreachable", "error": str(exc)})


# ── tool: get_fields ──────────────────────────────────────────────────────────

@mcp.tool()
def get_fields(port: int = DEFAULT_PORT) -> str:
    """
    Ritorna i dettagli di tutti i campi del template PDF caricato dall'API.
    Ogni campo include: nome, pagina, fontSize, alignment, fontColor, position, width, height.

    Args:
        port: porta dell'API (default: 8765)
    """
    try:
        return json.dumps(_api_get("/fields", port), ensure_ascii=False, indent=2)
    except urllib.error.URLError as exc:
        return json.dumps({"error": f"API non raggiungibile su porta {port}: {exc}"})


# ── tool: get_sample ──────────────────────────────────────────────────────────

@mcp.tool()
def get_sample(port: int = DEFAULT_PORT) -> str:
    """
    Ritorna il JSON campione pronto per POST /fill.
    I valori sono presi dal campo 'content' dello schema (default pdfme).

    Args:
        port: porta dell'API (default: 8765)
    """
    try:
        return json.dumps(_api_get("/sample", port), ensure_ascii=False, indent=2)
    except urllib.error.URLError as exc:
        return json.dumps({"error": f"API non raggiungibile su porta {port}: {exc}"})


# ── tool: fill_pdf ────────────────────────────────────────────────────────────

@mcp.tool()
def fill_pdf(data: dict, output_path: str, port: int = DEFAULT_PORT) -> str:
    """
    Compila il PDF con i dati forniti e salva il file.

    Args:
        data:        dizionario {NomeCampo: valore} da inviare all'API
        output_path: percorso assoluto dove salvare il PDF compilato
        port:        porta dell'API (default: 8765)
    """
    output_path = os.path.abspath(output_path)
    payload     = json.dumps(data).encode("utf-8")

    try:
        pdf_bytes = _api_post("/fill", payload, port)
    except urllib.error.HTTPError as exc:
        return json.dumps({"error": f"HTTP {exc.code}: {exc.read().decode()}"})
    except urllib.error.URLError as exc:
        return json.dumps({"error": f"API non raggiungibile su porta {port}: {exc}"})

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(pdf_bytes)

    return json.dumps({
        "status":     "ok",
        "output":     output_path,
        "size_bytes": len(pdf_bytes),
    })


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
