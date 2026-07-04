"""cura-stro Mac-Agent — PixInsight-Batch-Trigger (File-Broker-Modus).

Läuft als kleiner HTTP-Service auf dem Mac, auf dem PixInsight installiert ist.
Nimmt Verarbeitungs-Jobs vom cura-stro Backend entgegen — **inklusive der RAW-
Dateien als ZIP-Upload**. PixInsight wird headless (CLI) gestartet, die
Ergebnisse werden als ZIP zurückgeladen.

Alle Dateien werden über HTTP transferiert (kein SMB-Mount nötig):

    Backend liest NAS  →  zip  →  POST /process (multipart)  →  Agent
    Agent entpackt     →  PixInsight  →  zip  →  GET /results/{job_id}
    Backend entpackt   →  schreibt auf NAS (Prepared/)  →  Status: vorbereitet
    Backend ruft DELETE /jobs/{job_id}  →  Agent räumt Input + Output auf

Calibration-Frames (Flats/Darks/Bias) liegen im selben ZIP wie die Lights
(vom Backend per SMB vom NAS geholt). Keine lokalen Mac-Pfade mehr nötig.

Cleanup-Strategie (Platz sparen):
    - Nach PixInsight-Fertigstellung: Input-Verzeichnis (RAW-Frames) löschen
    - Nach erfolgreichem Ergebnis-Download: Output-Verzeichnis löschen
    - DELETE /jobs/{job_id}: räumt alles restlose auf (Fallback)

Endpoints:
    GET  /health              — Health-Check
    POST /process             — Job annehmen (ZIP-Upload) & PixInsight starten
    GET  /status/<job_id>     — Job-Status abfragen
    GET  /results/<job_id>    — Ergebnis-ZIP herunterladen (wenn completed)
    GET  /jobs                — Alle Jobs auflisten
    GET  /logs/<job_id>       — Log-Inhalt eines Jobs
    DELETE /jobs/<job_id>     — Abgeschlossenen Job löschen (inkl. Temp-Dateien)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

# ─── Logging-Setup (Console + Datei) ───
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(message)s"

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))

log = logging.getLogger("cura-stro.agent")
log.setLevel(logging.INFO)
log.handlers = []  # Alle existierenden Handler entfernen (verhindert Doppelung)
log.addHandler(_console_handler)
log.propagate = False  # Verhindert doppelte Ausgabe via uvicorn-Root-Handler

# Uvicorn-Logger an unseren Handler anbinden (kein eigener Handler → keine Doppelung)
for _uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _uv_log = logging.getLogger(_uv_name)
    _uv_log.handlers = []
    _uv_log.addHandler(_console_handler)
    _uv_log.propagate = False
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ─── Konfiguration (Umgebungsvariablen) ───
AGENT_PORT = int(os.environ.get("AGENT_PORT", "7777"))
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
PIXINSIGHT_BIN = os.environ.get(
    "PIXINSIGHT_BIN",
    "/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight",
)
BATCH_SCRIPT = os.environ.get(
    "BATCH_SCRIPT",
    str(Path(__file__).parent / "cura_batch.js"),
)
WORK_DIR = Path(os.environ.get("WORK_DIR", str(Path.home() / "cura-stro-jobs")))
LOG_DIR = Path(os.environ.get("LOG_DIR", str(WORK_DIR / "logs")))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

WORK_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="cura-stro Mac-Agent", version="0.7.0")


# ─── Job-Tracking ───
@dataclass
class Job:
    id: str
    work_input: str        # lokaler Pfad mit entpackten RAW-Dateien
    work_output: str       # lokaler Pfad für PixInsight-Ergebnisse
    result_zip: str        # Pfad zur Ergebnis-ZIP (wenn completed)
    frame_info: dict[str, Any]
    mode: str = "wbpp"     # wbpp · fastbatch · shell_sim
    status: str = "queued"  # queued · running · completed · failed
    started_at: str | None = None
    completed_at: str | None = None
    pid: int | None = None
    return_code: int | None = None
    log_file: str | None = None
    error: str | None = None
    result_files: list[str] = field(default_factory=list)
    result_zip_size: int = 0
    input_cleaned: bool = False   # Input-Verzeichnis wurde gelöscht
    output_cleaned: bool = False  # Output-Verzeichnis wurde gelöscht

    def to_dict(self) -> dict:
        return asdict(self)


_jobs: dict[str, Job] = {}
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ─── Request-Models ───
class StatusResponse(BaseModel):
    job_id: str
    status: str


def _check_token(token: str) -> None:
    if AGENT_TOKEN and token != AGENT_TOKEN:
        log.warning("Token-Prüfung fehlgeschlagen")
        raise HTTPException(403, "Ungültiges Token")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zip_directory(src_dir: Path, zip_path: Path) -> int:
    """Zippt ein gesamtes Verzeichnis (rekursiv) und liefert die Größe."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir)
                zf.write(file_path, arcname)
                file_count += 1
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    log.info("  ZIP erstellt: %s (%d Dateien, %.1f MB)", zip_path.name, file_count, size_mb)
    return zip_path.stat().st_size


def _cleanup_input(job: Job) -> None:
    """Löscht das Input-Verzeichnis (RAW-Frames nicht mehr nötig nach Verarbeitung)."""
    input_path = Path(job.work_input)
    if input_path.exists() and input_path.is_dir():
        try:
            shutil.rmtree(input_path, ignore_errors=True)
            job.input_cleaned = True
            log.info("  Input aufgeräumt: %s", input_path)
        except Exception as e:
            log.warning("  Konnte Input nicht aufräumen: %s — %s", input_path, e)


def _cleanup_output(job: Job) -> None:
    """Löscht das Output-Verzeichnis und die Ergebnis-ZIP (nach erfolgreichem Download)."""
    output_path = Path(job.work_output)
    if output_path.exists() and output_path.is_dir():
        try:
            shutil.rmtree(output_path, ignore_errors=True)
            job.output_cleaned = True
            log.info("  Output aufgeräumt: %s", output_path)
        except Exception as e:
            log.warning("  Konnte Output nicht aufräumen: %s — %s", output_path, e)
    # Ergebnis-ZIP auch löschen
    if job.result_zip:
        zip_path = Path(job.result_zip)
        if zip_path.exists():
            try:
                zip_path.unlink(missing_ok=True)
                log.info("  Ergebnis-ZIP gelöscht: %s", zip_path)
            except Exception as e:
                log.warning("  Konnte Ergebnis-ZIP nicht löschen: %s — %s", zip_path, e)


def _classify_frame(filename: str) -> str:
    """Klassifiziert einen Dateinamen nach Frame-Typ (ASIAir-Konvention)."""
    lower = filename.lower()
    if lower.startswith("darkflat"):
        return "darkflat"
    if lower.startswith("light"):
        return "light"
    if lower.startswith("dark"):
        return "dark"
    if lower.startswith("flat"):
        return "flat"
    if lower.startswith("bias"):
        return "bias"
    return "light"


def _count_frames(input_dir: Path) -> dict[str, int]:
    """Zählt Dateien im Input-Verzeichnis nach Frame-Typ."""
    counts: dict[str, int] = {
        "light": 0, "dark": 0, "flat": 0, "bias": 0, "darkflat": 0, "other": 0,
    }
    for f in input_dir.rglob("*"):
        if f.is_file():
            ftype = _classify_frame(f.name)
            counts[ftype] = counts.get(ftype, 0) + 1
    return counts


async def _run_shell_sim(job: Job) -> None:
    """Shell-Simulation: Kopiert Light-Frames als 'Master' in den Output-Ordner.
    Kein PixInsight nötig — validiert den gesamten HTTP-Flow."""
    async with _semaphore:
        job.status = "running"
        job.started_at = _now_iso()
        log.info("=" * 60)
        log.info("Job %s — Shell-Simulation GESTARTET", job.id[:8])
        log.info("  Input:  %s", job.work_input)
        log.info("  Output: %s", job.work_output)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        try:
            with open(log_file, "w") as flog:
                flog.write(f"=== cura-stro Shell-Simulation (Job {job.id}) ===\n")
                flog.write(f"Input:  {job.work_input}\n")
                flog.write(f"Output: {job.work_output}\n")
                flog.write(f"Frame-Info: {json.dumps(job.frame_info, indent=2)}\n\n")

                input_dir = Path(job.work_input)
                output_dir = Path(job.work_output)
                output_dir.mkdir(parents=True, exist_ok=True)

                all_files = sorted(f for f in input_dir.rglob("*") if f.is_file())
                counts = _count_frames(input_dir)
                log.info("  Gefunden: %d Dateien (Lights: %d, Darks: %d, Flats: %d, Bias: %d, DarkFlats: %d)",
                         len(all_files), counts["light"], counts["dark"],
                         counts["flat"], counts["bias"], counts["darkflat"])
                flog.write(f"Gefunden: {len(all_files)} Dateien\n")
                flog.write(f"  Lights: {counts['light']}, Darks: {counts['dark']}, "
                           f"Flats: {counts['flat']}, Bias: {counts['bias']}, "
                           f"DarkFlats: {counts['darkflat']}\n\n")

                lights = []
                calib_files = []
                for f in all_files:
                    ftype = _classify_frame(f.name)
                    flog.write(f"  {f.name} → {ftype}\n")
                    if ftype == "light":
                        lights.append(f)
                    else:
                        calib_files.append((f, ftype))

                log.info("  Verarbeite %d Light-Frames …", len(lights))
                if lights:
                    master_path = output_dir / "master_light_simulated.xisf"
                    shutil.copy2(lights[0], master_path)
                    log.info("  Master (simuliert): %s", master_path.name)
                    flog.write(f"\nMaster (simuliert): {master_path.name}\n")

                    cal_dir = output_dir / "calibrated"
                    cal_dir.mkdir(exist_ok=True)
                    for i, light in enumerate(lights):
                        dst = cal_dir / f"calibrated_{i:04d}{light.suffix}"
                        shutil.copy2(light, dst)
                    log.info("  Kalibrierte Lights: %d Dateien", len(lights))
                    flog.write(f"Kalibrierte Lights: {len(lights)} Dateien\n")

                if calib_files:
                    calib_out = output_dir / "calibration"
                    calib_out.mkdir(exist_ok=True)
                    for f, ftype in calib_files:
                        dst = calib_out / f.name
                        if not dst.exists():
                            shutil.copy2(f, dst)
                    log.info("  Calibration-Files kopiert: %d Dateien", len(calib_files))
                    flog.write(f"Calibration-Files: {len(calib_files)} Dateien\n")

                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )

                log.info("  Ergebnis: %d Dateien", len(job.result_files))
                flog.write(f"\nErgebnis: {len(job.result_files)} Dateien\n")
                flog.write("Shell-Simulation abgeschlossen.\n")

            job.return_code = 0
            job.status = "completed"
            log.info("Job %s — Shell-Simulation ABGESCHLOSSEN", job.id[:8])

            zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
            if out_path.is_dir() and any(out_path.iterdir()):
                log.info("  Packe Ergebnis-ZIP …")
                job.result_zip_size = _zip_directory(out_path, zip_path)
                job.result_zip = str(zip_path)
            else:
                job.status = "failed"
                job.error = "Shell-Simulation lieferte keine Ergebnis-Dateien"
                log.error("Job %s — FEHLER: keine Ergebnis-Dateien", job.id[:8])

            # Input aufräumen (RAW-Frames nicht mehr nötig)
            if job.status == "completed":
                _cleanup_input(job)

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error("Job %s — FEHLER: %s", job.id[:8], e, exc_info=True)
            with open(log_file, "a") as flog:
                flog.write(f"\nFEHLER: {e}\n")
        finally:
            job.completed_at = _now_iso()
            log.info("=" * 60)


def _print_pi_log(log_file: Path, max_lines: int = 200) -> None:
    """Gibt den PixInsight-Log auf der Agent-Konsole aus (für Debugging)."""
    try:
        content = log_file.read_text(errors="replace").strip()
        if not content:
            log.info("  PixInsight-Log ist leer")
            return
        lines = content.split("\n")
        if len(lines) > max_lines:
            log.info("  --- PixInsight Log (letzte %d von %d Zeilen) ---", max_lines, len(lines))
            lines = lines[-max_lines:]
        else:
            log.info("  --- PixInsight Log (%d Zeilen) ---", len(lines))
        for line in lines:
            log.info("  PI | %s", line)
        log.info("  --- Ende PixInsight Log ---")
    except Exception as e:
        log.warning("  Konnte PixInsight-Log nicht lesen: %s", e)


def _kill_existing_pixinsight() -> None:
    """Killt alle laufenden PixInsight-Prozesse vor einem headless-Batch.
    Verhindert 'Yielded execution to running instance' — das Skript wuerde
    sonst an eine bestehende Instanz delegiert und nie ausgefuehrt."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'PixInsight'],
            capture_output=True, text=True, timeout=5,
        )
        pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
        # Eigene PID ausschliessen (falls der Agent-Pfad 'PixInsight' enthaelt)
        my_pid = os.getpid()
        pids = [p for p in pids if p != str(my_pid)]
        if pids:
            log.info('  Killte %d laufende(n) PixInsight-Prozess(e): %s', len(pids), ', '.join(pids))
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid], timeout=5)
                except Exception:
                    pass
            import time
            time.sleep(2)
    except FileNotFoundError:
        pass  # pgrep nicht verfuegbar (nicht macOS)
    except Exception as e:
        log.warning('  Konnte PixInsight-Prozesse nicht killen: %s', e)


async def _run_pixinsight(job: Job) -> None:
    """Führt PixInsight headless mit dem Batch-Skript aus."""
    async with _semaphore:
        job.status = "running"
        job.started_at = _now_iso()
        log.info("=" * 60)
        log.info("Job %s — PixInsight (%s) GESTARTET", job.id[:8], job.mode)
        log.info("  Input:  %s", job.work_input)
        log.info("  Output: %s", job.work_output)
        log.info("  Mode:   %s", job.mode)
        log.info("  Calib-Frames sind im ZIP enthalten (keine lokalen Pfade nötig)")

        Path(job.work_output).mkdir(parents=True, exist_ok=True)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        batch_script = BATCH_SCRIPT

        # Wrapper-JS generieren: setzt Config als globale JS-Variablen und
        # inkludiert cura_batch.js.  KEIN JSON.parse im PJSR-Skript nötig —
        # PJSR hat kein JSON-Objekt.  Stattdessen werden die Werte direkt
        # als JavaScript-Variablen injiziert.
        wrapper_path = Path(job.work_input).parent / f"{job.id}_wrapper.js"
        batch_source = Path(batch_script).read_text()
        wrapper_js = (
            "var CURA_INPUT_DIR = " + json.dumps(job.work_input) + ";\n"
            + "var CURA_OUTPUT_DIR = " + json.dumps(job.work_output) + ";\n"
            + "var CURA_MODE = " + json.dumps(job.mode) + ";\n"
            + "var CURA_FRAME_INFO = " + json.dumps(job.frame_info) + ";\n"
            + batch_source
        )
        wrapper_path.write_text(wrapper_js)
        log.info("  Wrapper: %s (cura_batch.js inlined, Config als JS-Variablen)", wrapper_path)

        # Laufende PixInsight-Instanzen killen (verhindert Yielding)
        _kill_existing_pixinsight()

        # PixInsight CLI Aufruf: -n erzwingt neue Instanz, --force-exit killt danach
        cmd = [
            PIXINSIGHT_BIN,
            "-n",                       # Neue Instanz erzwingen (kein Yielding)
            f"-r={wrapper_path}",
            "--force-exit",
        ]

        log.info("  PixInsight CLI: %s", " ".join(cmd))
        log.info("  Skript: %s", batch_script)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
            )
            job.pid = proc.pid
            log.info("  PixInsight PID: %d — warte auf Abschluss …", proc.pid)
            rc = await proc.wait()
            job.return_code = rc

            # PixInsight-Log auf Agent-Konsole ausgeben (für Debugging)
            _print_pi_log(log_file)

            if rc == 0:
                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )
                log.info("  Ergebnis: %d Dateien", len(job.result_files))

                if job.result_files:
                    job.status = "completed"
                    log.info("Job %s — PixInsight ABGESCHLOSSEN (exit 0, %d Dateien)",
                             job.id[:8], len(job.result_files))
                    zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
                    log.info("  Packe Ergebnis-ZIP …")
                    job.result_zip_size = _zip_directory(out_path, zip_path)
                    job.result_zip = str(zip_path)

                    # Input aufräumen (RAW-Frames nicht mehr nötig)
                    _cleanup_input(job)
                else:
                    job.status = "failed"
                    job.error = "PixInsight lieferte keine Ergebnis-Dateien"
                    log.error("Job %s — FEHLER: keine Ergebnis-Dateien (exit 0, aber Output leer)",
                              job.id[:8])
            else:
                job.status = "failed"
                job.error = f"PixInsight exit code {rc} — siehe Log: {log_file}"
                log.error("Job %s — FEHLER: PixInsight exit code %d", job.id[:8], rc)
                log.error("  Log: %s", log_file)

        except FileNotFoundError:
            job.status = "failed"
            job.error = f"PixInsight nicht gefunden unter: {PIXINSIGHT_BIN}"
            log.error("Job %s — FEHLER: PixInsight nicht gefunden: %s", job.id[:8], PIXINSIGHT_BIN)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error("Job %s — FEHLER: %s", job.id[:8], e, exc_info=True)
        finally:
            job.completed_at = _now_iso()
            wrapper_path.unlink(missing_ok=True)
            log.info("=" * 60)


# ─── Endpoints ───
@app.on_event("startup")
async def _startup():
    log.info("=" * 60)
    log.info("cura-stro Mac-Agent v0.7.0 — startet")
    log.info("  Port:         %d", AGENT_PORT)
    log.info("  Work-Dir:     %s", WORK_DIR)
    log.info("  Log-Dir:      %s", LOG_DIR)
    log.info("  PixInsight:   %s (%s)",
             PIXINSIGHT_BIN,
             "✓ gefunden" if Path(PIXINSIGHT_BIN).exists() else "✗ NICHT gefunden")
    log.info("  Batch-Script: %s (%s)",
             BATCH_SCRIPT,
             "✓ gefunden" if Path(BATCH_SCRIPT).exists() else "✗ NICHT gefunden")
    log.info("  Max parallel: %d", MAX_CONCURRENT)
    log.info("  Token:        %s", "aktiv" if AGENT_TOKEN else "deaktiviert (offen)")
    log.info("=" * 60)


@app.get("/health")
async def health():
    pixinsight_ok = Path(PIXINSIGHT_BIN).exists()
    script_ok = Path(BATCH_SCRIPT).exists()
    # Pruefen, ob PixInsight bereits laeuft (GUI oder hängengebliebener Prozess)
    pixinsight_running = False
    try:
        result = subprocess.run(
            ["pgrep", "-f", "PixInsight"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        pids = [p for p in pids if p != str(os.getpid())]
        pixinsight_running = len(pids) > 0
    except Exception:
        pass
    return {
        "status": "ok" if pixinsight_ok and script_ok else "degraded",
        "pixinsight_found": pixinsight_ok,
        "pixinsight_running": pixinsight_running,
        "pixinsight_path": PIXINSIGHT_BIN,
        "batch_script_found": script_ok,
        "batch_script_path": BATCH_SCRIPT,
        "work_dir": str(WORK_DIR),
        "active_jobs": sum(1 for j in _jobs.values() if j.status == "running"),
        "total_jobs": len(_jobs),
        "shell_sim_available": True,
    }


@app.post("/process")
async def process(
    file: UploadFile = File(..., description="ZIP mit RAW-Frames (Lights/Darks/Flats/Bias)"),
    frame_info: str = Form(default="{}", description="JSON mit Frame-Metadaten"),
    mode: str = Form(default="wbpp", description="Processing-Modus: wbpp|fastbatch|shell_sim"),
    token: str = Form(default=""),
):
    """Nimmt ein ZIP mit RAW-Frames entgegen, entpackt es lokal und startet
    PixInsight headless (oder die Shell-Simulation). Die Ergebnisse können
    später als ZIP heruntergeladen werden (GET /results/{job_id})."""
    _check_token(token)

    log.info("-" * 60)
    log.info("POST /process — neuer Job empfangen")
    log.info("  Mode:          %s", mode)
    log.info("  Upload:        %s (%s bytes)",
             file.filename, file.size if file.size else "?")

    try:
        info = json.loads(frame_info) if frame_info else {}
    except json.JSONDecodeError:
        info = {}
    if info:
        log.info("  Frame-Info:    %s", json.dumps(info, indent=2))

    if mode not in ("wbpp", "fastbatch", "shell_sim"):
        log.warning("  Unbekannter Mode '%s' → fallback auf wbpp", mode)
        mode = "wbpp"

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("  Job-ID:        %s", job_id)
    log.info("  Job-Dir:       %s", job_dir)

    # ZIP empfangen und speichern
    log.info("  Empfangen ZIP-Upload …")
    zip_path = job_dir / "upload.zip"
    total_bytes = 0
    with open(zip_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
            total_bytes += len(chunk)
    upload_mb = total_bytes / (1024 * 1024)
    log.info("  Upload komplett: %.1f MB", upload_mb)

    # ZIP entpacken
    log.info("  Entpacke ZIP …")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(input_dir)
    except zipfile.BadZipFile:
        log.error("  FEHLER: keine gültige ZIP-Datei")
        raise HTTPException(400, "Hochgeladene Datei ist kein gültiges ZIP")
    except Exception as e:
        log.error("  FEHLER beim Entpacken: %s", e)
        raise HTTPException(400, f"Fehler beim Entpacken: {e}")

    # Upload-ZIP löschen (Platz sparen — entpackte Dateien reichen)
    zip_path.unlink(missing_ok=True)
    log.info("  Upload-ZIP gelöscht (Platz gespart)")

    raw_files = [f for f in input_dir.rglob("*") if f.is_file()]
    if not raw_files:
        log.error("  FEHLER: ZIP enthält keine Dateien")
        raise HTTPException(400, "ZIP enthält keine Dateien")

    counts = _count_frames(input_dir)
    log.info("  Entpackt: %d Dateien (Lights: %d, Darks: %d, Flats: %d, Bias: %d, DarkFlats: %d)",
             len(raw_files), counts["light"], counts["dark"],
             counts["flat"], counts["bias"], counts["darkflat"])

    job = Job(
        id=job_id,
        work_input=str(input_dir),
        work_output=str(output_dir),
        result_zip="",
        frame_info=info,
        mode=mode,
    )
    _jobs[job_id] = job

    if mode == "shell_sim":
        log.info("  Starte Shell-Simulation …")
        asyncio.create_task(_run_shell_sim(job))
    else:
        log.info("  Starte PixInsight (%s) …", mode)
        asyncio.create_task(_run_pixinsight(job))

    log.info("  Job %s queued — Rückmeldung an Backend", job_id[:8])
    log.info("-" * 60)

    return {
        "job_id": job_id,
        "status": "queued",
        "input_files": len(raw_files),
        "mode": mode,
    }


@app.get("/status/{job_id}")
async def job_status(job_id: str, token: str = ""):
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        log.warning("GET /status/%s — Job nicht gefunden", job_id[:8])
        raise HTTPException(404, "Job nicht gefunden")
    return job.to_dict()


@app.get("/results/{job_id}")
async def job_results(job_id: str, token: str = ""):
    """Lädt die Ergebnis-ZIP eines abgeschlossenen Jobs herunter.
    Nach erfolgreichem Download wird das Output-Verzeichnis aufgeräumt."""
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        log.warning("GET /results/%s — Job nicht gefunden", job_id[:8])
        raise HTTPException(404, "Job nicht gefunden")
    if job.status != "completed":
        log.info("GET /results/%s — Job noch '%s' (409)", job_id[:8], job.status)
        raise HTTPException(409, f"Job ist noch '{job.status}' — keine Ergebnisse verfügbar")
    if not job.result_zip or not Path(job.result_zip).exists():
        log.warning("GET /results/%s — ZIP nicht gefunden", job_id[:8])
        raise HTTPException(404, "Ergebnis-ZIP nicht gefunden")
    size_mb = job.result_zip_size / (1024 * 1024)
    log.info("GET /results/%s — sende ZIP (%.1f MB, %d Dateien)",
             job_id[:8], size_mb, len(job.result_files))

    # Ergebnis-ZIP in Memory lesen (vor dem Aufräumen)
    zip_data = Path(job.result_zip).read_bytes()

    # Output aufräumen (Ergebnisse wurden heruntergeladen → nicht mehr nötig)
    _cleanup_output(job)

    # Ergebnis-ZIP aus Memory senden (Datei auf Disk bereits gelöscht)
    return Response(
        content=zip_data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_results.zip"'},
    )


@app.get("/jobs")
async def list_jobs(token: str = ""):
    _check_token(token)
    return {"jobs": [j.to_dict() for j in _jobs.values()]}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str, token: str = ""):
    """Entfernt einen Job und seine Temp-Dateien (restloses Aufräumen)."""
    _check_token(token)
    job = _jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    job_dir = Path(job.work_input).parent
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    log.info("DELETE /jobs/%s — Job gelöscht (Temp-Dateien entfernt)", job_id[:8])
    return {"deleted": job_id}


@app.get("/logs/{job_id}")
async def job_logs(job_id: str, token: str = ""):
    """Liefert den Log-Inhalt eines Jobs."""
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    if not job.log_file or not Path(job.log_file).exists():
        return {"log": "(kein Log vorhanden)"}
    return {"log": Path(job.log_file).read_text()}


if __name__ == "__main__":
    import uvicorn
    # log_config=None: uvicorn rekonfiguriert Logging NICHT — unsere Handler
    # bleiben erhalten, keine Doppelung.
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT, log_config=None)
