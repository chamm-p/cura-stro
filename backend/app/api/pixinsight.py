"""PixInsight-Batch-API — triggert die Verarbeitung auf dem Mac-Agent.

Endpoints:
    POST   /api/observations/{obs_id}/process   — PixInsight-Batch starten
    GET    /api/pixinsight/status/{job_id}       — Job-Status abfragen
    GET    /api/pixinsight/health                — Agent-Health-Check
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/api/observations/{obs_id}/process")
async def trigger_processing(
    obs_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Startet den PixInsight-Batch für diese Aufnahme über den Mac-Agent.

    Setzt den Status auf 'in_bearbeitung'. Der Mac-Agent verarbeitet die
    RAW-Dateien und schreibt Ergebnisse ins Developer-Verzeichnis, wo der
    Watch-Loop sie automatisch erkennt (Status → 'entwickelt').
    """
    obs = await _owned_obs(db, user, obs_id)
    try:
        result = await pixinsight.trigger_batch(db, user, obs)
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


@router.get("/api/pixinsight/health")
async def agent_health(user: User = Depends(get_current_user)):
    """Prüft, ob der Mac-Agent erreichbar ist und PixInsight findet."""
    return await pixinsight.check_agent_health()
