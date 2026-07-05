"""PixInsight-Batch-API — triggert die Verarbeitung auf dem Mac-Agent.

Endpoints:
    GET    /api/observations/{obs_id}/precheck  — Pre-Flight-Check
    POST   /api/observations/{obs_id}/process   — PixInsight-Batch starten
    POST   /api/observations/{obs_id}/poll       — Job-Ergebnisse abholen
    GET    /api/pixinsight/status/{job_id}       — Job-Status abfragen
    GET    /api/pixinsight/health                — Agent-Health-Check
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.observation import Observation
from app.models.user import User
from app.services import pixinsight

router = APIRouter(tags=["pixinsight"])


async def _owned_obs(db: AsyncSession, user: User, obs_id: str) -> Observation:
    try:
        o = await db.scalar(
            select(Observation).where(
                Observation.id == uuid.UUID(obs_id),
                Observation.user_id == user.id,
            )
        )
    except ValueError:
        o = None
    if not o:
        raise HTTPException(404, "Aufnahme nicht gefunden")
    return o


class ProcessRequest(BaseModel):
    mode: str = "wbpp"  # wbpp · fastbatch · shell_sim
    agent: str = "1"    # 1 = primärer Agent, 2 = zweiter (z. B. Windows)


class PollRequest(BaseModel):
    job_id: str


@router.get("/api/observations/{obs_id}/precheck")
async def precheck(
    obs_id: str,
    agent: str = "1",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pre-Flight-Check vor dem PixInsight-Batch.

    Prüft Sub-Frames (Lights/Darks/Flats/Bias), Calibration-Dir,
    Erreichbarkeit des GEWÄHLTEN Agents und liefert Warnungen/Errors
    sowie ein ``can_start`` Flag.
    """
    obs = await _owned_obs(db, user, obs_id)
    return await pixinsight.precheck(db, user, obs, agent=agent)


@router.post("/api/observations/{obs_id}/process")
async def trigger_processing(
    obs_id: str,
    body: ProcessRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Startet den PixInsight-Batch für diese Aufnahme über den Mac-Agent.

    Liest die RAW-Dateien vom NAS, zippt sie und lädt sie per HTTP an den
    Mac-Agent hoch. Der Agent verarbeitet sie mit PixInsight/WBPP (oder
    Shell-Simulation im Test-Modus).

    Parameter (JSON body, optional):
        mode — "wbpp" (Standard), "fastbatch" oder "shell_sim" (Test-Modus)

    Setzt den Status auf 'in_bearbeitung'. Die Ergebnisse müssen später per
    POST /api/observations/{obs_id}/poll abgeholt werden (Status → 'vorbereitet').
    """
    obs = await _owned_obs(db, user, obs_id)
    mode = body.mode if body else "wbpp"
    agent = body.agent if body else "1"
    try:
        result = await pixinsight.trigger_batch(db, user, obs, mode=mode, agent=agent)
        await db.commit()
        return result
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"Unerwarteter Fehler: {e}")


@router.post("/api/observations/{obs_id}/poll")
async def poll_results(
    obs_id: str,
    req: PollRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Holt die Ergebnisse eines PixInsight-Jobs vom Mac-Agent ab.

    Wenn der Job abgeschlossen ist, wird die Ergebnis-ZIP heruntergeladen,
    entpackt und ins Prepared-Verzeichnis auf dem NAS geschrieben.
    Der Status wechselt auf 'vorbereitet'.

    Wenn der Job noch läuft, wird der aktuelle Status zurückgegeben
    (keine Änderung am Observation-Status).
    """
    obs = await _owned_obs(db, user, obs_id)
    try:
        result = await pixinsight.poll_job_results(db, user, obs, req.job_id)
        await db.commit()
        return result
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"Unerwarteter Fehler: {e}")


@router.get("/api/pixinsight/status/{job_id}")
async def get_job_status(job_id: str, user: User = Depends(get_current_user)):
    """Fragt den Status eines PixInsight-Jobs vom Mac-Agent ab."""
    return await pixinsight.check_job_status(job_id)


@router.get("/api/pixinsight/agents")
async def list_agents(user: User = Depends(get_current_user)):
    """Konfigurierte PixInsight-Agents (für die Auswahl im Batch-Dialog)."""
    return {"agents": [
        {"id": a["id"], "name": a["name"]} for a in pixinsight.list_agents()
    ]}


@router.get("/api/pixinsight/jobs")
async def list_jobs(user: User = Depends(get_current_user)):
    """Alle PixInsight-Jobs dieses Backends (Warteschlange, neueste zuerst)."""
    jobs = [j for j in pixinsight.list_backend_jobs() if j.get("user_id") == str(user.id)]
    return {"jobs": jobs}


@router.delete("/api/pixinsight/jobs/{job_id}")
async def remove_job(job_id: str, user: User = Depends(get_current_user)):
    """Entfernt einen abgeschlossenen/fehlgeschlagenen Job aus der Queue-Anzeige."""
    if not pixinsight.remove_backend_job(job_id, str(user.id)):
        raise HTTPException(404, "Job nicht gefunden oder läuft noch")
    return {"removed": job_id}


@router.get("/api/pixinsight/health")
async def agent_health(user: User = Depends(get_current_user)):
    """Prüft, ob der Mac-Agent erreichbar ist und PixInsight findet."""
    return await pixinsight.check_agent_health()
