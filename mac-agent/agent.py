"""cura-stro Mac-Agent — PixInsight-Batch-Trigger (File-Broker-Modus).

Läuft als kleiner HTTP-Service auf dem Mac, auf dem PixInsight installiert ist.
Nimmt Verarbeitungs-Jobs vom cura-stro-Backend entgegen — **inklusive der RAW-
Dateien als ZIP-Upload**. PixInsight wird headless (CLI) gestartet, die
Ergebnisse werden als ZIP zurückgeladen.

Im Gegensatz zur ersten Version benötigt dieser Agent **keinen SMB-Mount**.
Alle Dateien werden über HTTP transferiert:

    Backend liest NAS  →  zip  →  POST /process (multipart)  →  Agent
    Agent entpackt     →  PixInsight/WBPP  →  zip  →  GET /results/{job_id}
    Backend entpackt   →  schreibt auf NAS (Prepared/)  →  Status: vorbereitet

Setup:
    pip install -r requirements.txt
    python agent.py                      # Development
    # Als launchd-Daemon: siehe com.cura-stro.agent.plist

Processing-Modi (via Form-Feld "mode"):
    wbpp       — WeightedBatchPreProcessing (vollständig, langsam)
    fastbatch  — FastBatchProcessing (schneller, weniger Optionen)
    shell_sim  — Shell-Simulation: kopiert Lights als "Master" (Test-Modus,
                 kein PixInsight nötig — validiert den gesamten HTTP-Flow)

Calibration-Frames:
    Das Backend kann im Form-Feld "calibration_dir" einen Pfad auf dem Mac
    schicken, wo Flats/Darks/Bias für das jeweilige Setup liegen. Diese werden
    dem PixInsight-Skript als zusätzliches Argument --calib=<dir> übergeben.
    Im shell_sim-Modus werden sie einfach mit in den Output-Ordner kopiert.

Endpoints:
    GET  /health              — Health-Check
    POST /process             — Job annehmen (ZIP-Upload) & PixInsight starten
    GET  /status/<job_id>     — Job-Status abfragen
    GET  /results/<job_id>   — Ergebnis-ZIP herunterladen ( wenn completed)
    GET  /jobs                — Alle Jobs auflisten
    GET  /logs/<job_id>       — Log-Inhalt eines Jobs
    DELETE /jobs/<job_id>     — Abgeschlossenen Job löschen (inkl. Temp-Dateien)
"""

from __future__ import annotations

import asyncio
import json
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
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ─── Konfiguration (Umgebungsvariablen) ───
AGENT_PORT = int(os.environ.get("AGENT_PORT", "7777"))
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")  # Shared-Secret mit Backend
PIXINSIGHT_BIN = os.environ.get(
    "PIXINSIGHT_BIN",
    "/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight",
)
BATCH_SCRIPT = os.environ.get(
    "BATCH_SCRIPT",
    str(Path(__file__.parent / "cura_batch.js")),
)
WORK_DIR = Path(os.environ.get("WORK_DIR", str(Path.home() / "cura-stro-jobs")))
LOG_DIR = Path(os.environ.get("LOG_DIR", str(WORK_DIR / "logs")))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
# WBPP-Skript-Pfad (falls abweichend von der Standard-Installation).
WBPP_SCRIPT = os.environ.get(
    "WBPP_SCRIPT",
    "/Applications/PixInsight/src/scripts/BatchProcessing/WeightedBatchPreProcessing.js",
)
# FastBatchProcessing-Skript-Pfad.
FASTBATCH_SCRIPT = os.environ.get(
    "FASTBATCH_SCRIPT",
    "/Applications/PixInsight/src/scripts/BatchProcessing/FastBatchProcessing.js",
)

WORK_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="cura-stro Mac-Agent", version="0.3.0")


# ─── Job-Tracking ───
@dataclass
class Job:
    id: str
    work_input: str        # lokaler Pfad mit entpackten RAW-Dateien
    work_output: str       # lokaler Pfad für PixInsight-Ergebnisse
    result_zip: str        # Pfad zur Ergebnis-ZIP (wenn completed)
    frame_info: dict[str, Any]
    mode: str = "wbpp"     # wbpp · fastbatch · shell_sim
    calibration_dir: str = ""  # Pfad zu Flats/Darks/Bias auf dem Mac
    status: str = "queued"  # queued · running · completed · failed
    started_at: str | None = None
    completed_at: str | None = None
    pid: int | None = None
    return_code: int | None = None
    log_file: str | None = None
    error: str | None = None
    result_files: list[str] = field(default_factory=list)
    result_zip_size: int = 0

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
        raise HTTPException(403, "Ungültiges Token")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zip_directory(src_dir: Path, zip_path: Path) -> int:
    """Zippt ein gesamtes Verzeichnis (rekursiv) und liefert die Größe."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir)
                zf.write(file_path, arcname)
    return zip_path.stat().st_size


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


async def _run_shell_sim(job: Job) -> None:
    """Shell-Simulation: Kopiert Light-Frames als 'Master' in den Output-Ordner.
    Kein PixInsight nötig — validiert den gesamten HTTP-Flow."""
    async with _semaphore:
        job.status = "running"
        job.started_at = _now_iso()

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        try:
            with open(log_file, "w") as log:
                log.write(f"=== cura-stro Shell-Simulation (Job {job.id}) ===\n")
                log.write(f"Input:  {job.work_input}\n")
                log.write(f"Output: {job.work_output}\n")
                log.write(f"Mode:   {job.mode}\n")
                log.write(f"Calib:  {job.calibration_dir or '(keine)'}\n")
                log.write(f"Frame-Info: {json.dumps(job.frame_info, indent=2)}\n\n")

                input_dir = Path(job.work_input)
                output_dir = Path(job.work_output)
                output_dir.mkdir(parents=True, exist_ok=True)

                # Alle Dateien im Input-Verzeichnis listen
                all_files = sorted(f for f in input_dir.rglob("*") if f.is_file())
                log.write(f"Gefunden: {len(all_files)} Dateien\n")

                lights = []
                calib_files = []
                for f in all_files:
                    ftype = _classify_frame(f.name)
                    log.write(f"  {f.name} → {ftype}\n")
                    if ftype == "light":
                        lights.append(f)
                    else:
                        calib_files.append((f, ftype))

                # Calibration-Frames aus calibration_dir kopieren (falls angegeben)
                if job.calibration_dir:
                    calib_dir = Path(job.calibration_dir)
                    if calib_dir.is_dir():
                        log.write(f"\nCalibration-Verzeichnis: {calib_dir}\n")
                        for f in sorted(calib_dir.rglob("*")):
                            if f.is_file():
                                ftype = _classify_frame(f.name)
                                log.write(f"  {f.name} → {ftype} (aus calib_dir)\n")
                                calib_files.append((f, ftype))
                    else:
                        log.write(f"\nWARNUNG: Calibration-Verzeichnis nicht gefunden: {calib_dir}\n")

                # Simuliere "Master" — kopiere erste Light-Datei als master_light.xisf
                # (Namen enden auf .fit/.fits — wir kopieren sie 1:1)
                if lights:
                    # "Master" = erste Light kopieren (Simulation)
                    master_path = output_dir / "master_light_simulated.xisf"
                    shutil.copy2(lights[0], master_path)
                    log.write(f"\nMaster (simuliert): {master_path.name}\n")

                    # Kalibrierte Lights (simuliert = einfach kopieren)
                    cal_dir = output_dir / "calibrated"
                    cal_dir.mkdir(exist_ok=True)
                    for i, light in enumerate(lights):
                        dst = cal_dir / f"calibrated_{i:04d}{light.suffix}"
                        shutil.copy2(light, dst)
                    log.write(f"Kalibrierte Lights: {len(lights)} Dateien\n")

                # Calibration-Files in Output kopieren (für Referenz)
                if calib_files:
                    calib_out = output_dir / "calibration"
                    calib_out.mkdir(exist_ok=True)
                    for f, ftype in calib_files:
                        dst = calib_out / f.name
                        if not dst.exists():
                            shutil.copy2(f, dst)
                    log.write(f"Calibration-Files: {len(calib_files)} Dateien\n")

                # Ergebnis-Dateien listen
                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )

                log.write(f"\nErgebnis: {len(job.result_files)} Dateien\n")
                log.write("Shell-Simulation abgeschlossen.\n")

            job.return_code = 0
            job.status = "completed"

            # Ergebnis als ZIP packen
            zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
            if out_path.is_dir() and any(out_path.iterdir()):
                job.result_zip_size = _zip_directory(out_path, zip_path)
                job.result_zip = str(zip_path)
            else:
                job.status = "failed"
                job.error = "Shell-Simulation lieferte keine Ergebnis-Dateien"

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            with open(log_file, "a") as log:
                log.write(f"\nFEHLER: {e}\n")
        finally:
            job.completed_at = _now_iso()


async def _run_pixinsight(job: Job) -> None:
    """Führt PixInsight headless mit dem Batch-Skript aus."""
    async with _semaphore:
        job.status = "running"
        job.started_at = _now_iso()

        # Output-Verzeichnis sicherstellen
        Path(job.work_output).mkdir(parents=True, exist_ok=True)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        # Frame-Info als JSON-Datei für das Skript
        info_file = Path(job.work_input).parent / f"{job.id}_info.json"
        info_file.write_text(json.dumps(job.frame_info, indent=2))

        # Skript-Pfad je nach Modus
        if job.mode == "fastbatch":
            batch_script = BATCH_SCRIPT  # cura_batch.js unterstützt --mode
            wbpp_path = os.environ.get("FASTBATCH_SCRIPT", FASTBATCH_SCRIPT)
        else:
            batch_script = BATCH_SCRIPT
            wbpp_path = WBPP_SCRIPT

        # PixInsight CLI Aufruf
        cmd = [
            PIXINSIGHT_BIN,
            f"-run={batch_script}",
            f"--input={job.work_input}",
            f"--output={job.work_output}",
            f"--info={info_file}",
            f"--wbpp={wbpp_path}",
            f"--mode={job.mode}",
        ]
        if job.calibration_dir:
            cmd.append(f"--calib={job.calibration_dir}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
            )
            job.pid = proc.pid
            rc = await proc.wait()
            job.return_code = rc

            if rc == 0:
                job.status = "completed"
                # Ergebnis-Dateien listen
                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )
                # Ergebnis als ZIP packen
                zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
                if out_path.is_dir() and any(out_path.iterdir()):
                    job.result_zip_size = _zip_directory(out_path, zip_path)
                    job.result_zip = str(zip_path)
                else:
                    job.status = "failed"
                    job.error = "PixInsight lieferte keine Ergebnis-Dateien"
            else:
                job.status = "failed"
                job.error = f"PixInsight exit code {rc} — siehe Log: {log_file}"

        except FileNotFoundError:
            job.status = "failed"
            job.error = f"PixInsight nicht gefunden unter: {PIXINSIGHT_BIN}"
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
        finally:
            job.completed_at = _now_iso()
            # Temp-Info-Datei aufräumen
            info_file.unlink(missing_ok=True)


# ─── Endpoints ───
@app.get("/health")
async def health():
    pixinsight_ok = Path(PIXINSIGHT_BIN).exists()
    script_ok = Path(BATCH_SCRIPT).exists()
    wbpp_ok = Path(WBPP_SCRIPT).exists() if WBPP_SCRIPT else False
    fastbatch_ok = Path(FASTBATCH_SCRIPT).exists() if FASTBATCH_SCRIPT else False
    return {
        "status": "ok" if pixinsight_ok and script_ok else "degraded",
        "pixinsight_found": pixinsight_ok,
        "pixinsight_path": PIXINSIGHT_BIN,
        "batch_script_found": script_ok,
        "batch_script_path": BATCH_SCRIPT,
        "wbpp_script_found": wbpp_ok,
        "wbpp_script_path": WBPP_SCRIPT,
        "fastbatch_script_found": fastbatch_ok,
        "fastbatch_script_path": FASTBATCH_SCRIPT,
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
    calibration_dir: str = Form(default="", description="Pfad zu Flats/Darks/Bias auf dem Mac"),
    token: str = Form(default=""),
):
    """Nimmt ein ZIP mit RAW-Frames entgegen, entpackt es lokal und startet
    PixInsight headless (oder die Shell-Simulation). Die Ergebnisse können
    später als ZIP heruntergeladen werden (GET /results/{job_id})."""
    _check_token(token)

    # Frame-Info parsen
    try:
        info = json.loads(frame_info) if frame_info else {}
    except json.JSONDecodeError:
        info = {}

    # Mode validieren
    if mode not in ("wbpp", "fastbatch", "shell_sim"):
        mode = "wbpp"

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ZIP entpacken
    zip_path = job_dir / "upload.zip"
    with open(zip_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(input_dir)
    except zipfile.BadZipFile:
        raise HTTPException(400, "Hochgeladene Datei ist kein gültiges ZIP")
    except Exception as e:
        raise HTTPException(400, f"Fehler beim Entpacken: {e}")

    # Prüfen, dass Dateien vorhanden sind
    raw_files = [f for f in input_dir.rglob("*") if f.is_file()]
    if not raw_files:
        raise HTTPException(400, "ZIP enthält keine Dateien")

    job = Job(
        id=job_id,
        work_input=str(input_dir),
        work_output=str(output_dir),
        result_zip="",
        frame_info=info,
        mode=mode,
        calibration_dir=calibration_dir,
    )
    _jobs[job_id] = job

    # Asynchron starten (nicht-blockierend)
    if mode == "shell_sim":
        asyncio.create_task(_run_shell_sim(job))
    else:
        asyncio.create_task(_run_pixinsight(job))

    return {
        "job_id": job_id,
        "status": "queued",
        "input_files": len(raw_files),
        "mode": mode,
        "calibration_dir": calibration_dir or None,
    }


@app.get("/status/{job_id}")
async def job_status(job_id: str, token: str = ""):
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    return job.to_dict()


@app.get("/results/{job_id}")
async def job_results(job_id: str, token: str = ""):
    """Lädt die Ergebnis-ZIP eines abgeschlossenen Jobs herunter."""
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    if job.status != "completed":
        raise HTTPException(409, f"Job ist noch '{job.status}' — keine Ergebnisse verfügbar")
    if not job.result_zip or not Path(job.result_zip).exists():
        raise HTTPException(404, "Ergebnis-ZIP nicht gefunden")
    return FileResponse(
        job.result_zip,
        media_type="application/zip",
        filename=f"{job_id}_results.zip",
    )


@app.get("/jobs")
async def list_jobs(token: str = ""):
    _check_token(token)
    return {"jobs": [j.to_dict() for j in _jobs.values()]}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str, token: str = ""):
    """Entfernt einen Job und seine Temp-Dateien."""
    _check_token(token)
    job = _jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    job_dir = Path(job.work_input).parent
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
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
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
