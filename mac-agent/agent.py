"""cura-stro Mac-Agent — PixInsight-Batch-Trigger.

Läuft als kleiner HTTP-Service auf dem Mac, auf dem PixInsight installiert ist.
Nimmt Verarbeitungs-Jobs vom cura-stro-Backend entgegen, startet PixInsight
headless (CLI) und meldet Status zurück.

Setup:
    pip install -r requirements.txt
    python agent.py                      # Development
    # Als launchd-Daemon: siehe com.cura-stro.agent.plist

Endpoints:
    GET  /health              — Health-Check
    POST /process             — Job annehmen & PixInsight starten
    GET  /status/<job_id>     — Job-Status abfragen
    GET  /jobs                — Alle Jobs auflisten
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ─── Konfiguration (Umgebungsvariablen) ───
AGENT_PORT = int(os.environ.get("AGENT_PORT", "7777"))
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")  # Shared-Secret mit Backend
PIXINSIGHT_BIN = os.environ.get(
    "PIXINSIGHT_BIN",
    "/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight",
)
BATCH_SCRIPT = os.environ.get(
    "BATCH_SCRIPT",
    str(Path(__file__).parent / "cura_batch.js"),
)
WORK_DIR = Path(os.environ.get("WORK_DIR", Path.home() / "cura-stro-jobs"))
LOG_DIR = Path(os.environ.get("LOG_DIR", str(WORK_DIR / "logs")))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

WORK_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="cura-stro Mac-Agent", version="0.1.0")


# ─── Job-Tracking ───
@dataclass
class Job:
    id: str
    input_dir: str
    output_dir: str
    frame_info: dict[str, Any]
    status: str = "queued"  # queued · running · completed · failed
    started_at: str | None = None
    completed_at: str | None = None
    pid: int | None = None
    return_code: int | None = None
    log_file: str | None = None
    error: str | None = None
    result_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_jobs: dict[str, Job] = {}
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ─── Request-Models ───
class ProcessRequest(BaseModel):
    input_dir: str = Field(..., description="Pfad zu RAW/<Objekt>/<Gerät>/ auf dem Mac (NAS-Mount)")
    output_dir: str = Field(..., description="Pfad zu Developer/<Objekt>/<Gerät>/ auf dem Mac")
    frame_info: dict[str, Any] = Field(default_factory=dict, description="Zusammenfassung: Filter, Belichtungen, etc.")
    token: str = Field(default="")


def _check_token(token: str) -> None:
    if AGENT_TOKEN and token != AGENT_TOKEN:
        raise HTTPException(403, "Ungültiger Token")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_pixinsight(job: Job) -> None:
    """Führt PixInsight headless mit dem Batch-Skript aus."""
    async with _semaphore:
        job.status = "running"
        job.started_at = _now_iso()

        # Output-Verzeichnis sicherstellen
        Path(job.output_dir).mkdir(parents=True, exist_ok=True)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        # PixInsight CLI Aufruf
        # -run=<script>  führt das Skript aus
        # Argumente werden als Environment-Variablen oder Kommandozeilen-Args übergeben
        cmd = [
            PIXINSIGHT_BIN,
            f"-run={BATCH_SCRIPT}",
            f"--input={job.input_dir}",
            f"--output={job.output_dir}",
            "--no-gui",
        ]

        # Frame-Info als JSON-Datei für das Skript
        info_file = WORK_DIR / f"{job.id}_info.json"
        info_file.write_text(json.dumps(job.frame_info, indent=2))
        cmd.append(f"--info={info_file}")

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
                # Ergebnis-Dateien im Output-Verzeichnis listen
                out_path = Path(job.output_dir)
                if out_path.is_dir():
                    job.result_files = sorted(
                        f.name for f in out_path.iterdir()
                        if f.is_file() and f.suffix.lower() in {".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts"}
                    )
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
    return {
        "status": "ok" if pixinsight_ok and script_ok else "degraded",
        "pixinsight_found": pixinsight_ok,
        "pixinsight_path": PIXINSIGHT_BIN,
        "batch_script_found": script_ok,
        "batch_script_path": BATCH_SCRIPT,
        "work_dir": str(WORK_DIR),
        "active_jobs": sum(1 for j in _jobs.values() if j.status == "running"),
        "total_jobs": len(_jobs),
    }


@app.post("/process")
async def process(req: ProcessRequest):
    _check_token(req.token)

    # Input-Verzeichnis prüfen
    if not Path(req.input_dir).is_dir():
        raise HTTPException(400, f"Input-Verzeichnis nicht gefunden: {req.input_dir}")

    job = Job(
        id=str(uuid.uuid4()),
        input_dir=req.input_dir,
        output_dir=req.output_dir,
        frame_info=req.frame_info,
    )
    _jobs[job.id] = job

    # Asynchron starten (nicht-blockierend)
    asyncio.create_task(_run_pixinsight(job))

    return {"job_id": job.id, "status": "queued"}


@app.get("/status/{job_id}")
async def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    return job.to_dict()


@app.get("/jobs")
async def list_jobs():
    return {"jobs": [j.to_dict() for j in _jobs.values()]}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Entfernt einen abgeschlossenen Job aus dem Tracking."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    if job.status in ("running", "queued"):
        raise HTTPException(409, "Laufende Jobs können nicht gelöscht werden")
    del _jobs[job_id]
    return {"deleted": job_id}


@app.get("/logs/{job_id}")
async def job_logs(job_id: str):
    """Gibt den Log-Inhalt eines Jobs zurück."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    if not job.log_file or not Path(job.log_file).exists():
        return {"logs": ""}
    return {"logs": Path(job.log_file).read_text(errors="replace")}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
