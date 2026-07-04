"""PixInsight-Integration — triggert den Mac-Agent für Batch-Verarbeitung.

Der Mac-Agent (mac-agent/agent.py) läuft auf dem Mac, auf dem PixInsight
installiert ist. Er nimmt Jobs per HTTP entgegen, startet PixInsight headless
und meldet Status zurück.

Der cura-stro-Backend ruft den Agent auf, sobald der Nutzer eine Observation
"verarbeiten" will. Der Agent kennt die Pfade (NAS-Mount auf dem Mac) und
schreibt die Ergebnisse direkt ins Developer-Verzeichnis — wo der Watch-Loop
(results.py) sie automatisch erkennt.

Status-Fluss:
    raw → in_bearbeitung → (Watch-Loop erkennt Ergebnis) → entwickelt
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.observation import Observation
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()


async def _agent_url(path: str = "") -> str:
    base = _cfg.pixinsight_agent_url.rstrip("/")
    return f"{base}{path}"


async def _agent_token() -> str:
    return _cfg.pixinsight_agent_token


async def raw_reldir(db: AsyncSession, user: User, obs: Observation) -> str:
    """Relativer Pfad zum RAW-Verzeichnis der Aufnahme."""
    return archive.reldir(
        archive.folder_name(user, "RAW"),
        await archive.object_label(db, obs),
        await archive.device_label(db, obs),
    )


async def developer_reldir(db: AsyncSession, user: User, obs: Observation) -> str:
    """Relativer Pfad zum Developer-Verzeichnis der Aufnahme."""
    return archive.reldir(
        archive.folder_name(user, "Developer"),
        await archive.object_label(db, obs),
        await archive.device_label(db, obs),
    )


async def _frame_summary(db: AsyncSession, obs: Observation) -> dict[str, Any]:
    """Sammelt Frame-Info für das PixInsight-Skript (Filter, Belichtungen, etc.)."""
    subs = await db.scalars(select(SubFrame).where(SubFrame.observation_id == obs.id))
    subs = list(subs)
    by_filter: dict[str, dict] = {}
    for s in subs:
        f = s.filter_name or "—"
        slot = by_filter.setdefault(f, {"filter": f, "subs": 0, "exposures_s": set()})
        slot["subs"] += 1
        if s.exposure_s:
            slot["exposures_s"].add(s.exposure_s)
    filters = []
    for slot in by_filter.values():
        filters.append({
            "filter": slot["filter"],
            "subs": slot["subs"],
            "exposures_s": sorted(slot["exposures_s"]),
        })
    # Frame-Typen zählen
    frame_types = {}
    for s in subs:
        ft = (s.frame_type or "Light").lower()
        frame_types[ft] = frame_types.get(ft, 0) + 1
    return {
        "object_name": await archive.object_label(db, obs),
        "device_name": await archive.device_label(db, obs),
        "total_subs": len(subs),
        "filters": filters,
        "frame_types": frame_types,
    }


async def trigger_batch(db: AsyncSession, user: User, obs: Observation) -> dict[str, Any]:
    """Triggert den Mac-Agent, um PixInsight für diese Observation zu starten.

    Setzt voraus, dass der Mac das gleiche NAS-Volume gemountet hat wie das
    Backend. Die Pfade (input_dir/output_dir) werden aus der Archiv-Konfig
    des Nutzers abgeleitet.
    """
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert (PIXINSIGHT_AGENT_URL)")

    # Prüfen, dass Subs vorhanden sind
    sub_count = await db.scalar(
        select(SubFrame).where(SubFrame.observation_id == obs.id)
    )
    if not sub_count:
        raise ValueError("Keine Sub-Frames für diese Aufnahme — erst ASIAir-Daten importieren")

    # Pfade für den Mac ableiten
    # Der Mac kennt das NAS über seinen eigenen Mount-Point. Wir übergeben
    # die *relativen* Pfade (RAW/<Obj>/<Ger>/) und der Mac setzt seinen
    # Mount-Prefix davor — konfiguriert im Agent via NAS_MOUNT_PREFIX.
    raw_rel = await raw_reldir(db, user, obs)
    dev_rel = await developer_reldir(db, user, obs)

    frame_info = await _frame_summary(db, obs)

    payload = {
        "input_dir": raw_rel,
        "output_dir": dev_rel,
        "frame_info": frame_info,
        "token": await _agent_token(),
    }

    # Observation-Status setzen
    obs.status = "in_bearbeitung"
    obs.is_new = False
    await db.flush()

    # Agent asynchron aufrufen (nicht-blockierend, Timeout für HTTP-Handshake)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(await _agent_url("/process"), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        obs.status = "raw"  # Zurücksetzen — Agent nicht erreichbar
        await db.flush()
        raise ValueError(
            f"Mac-Agent nicht erreichbar unter {_cfg.pixinsight_agent_url}. "
            "Ist der Agent auf dem Mac gestartet?"
        )
    except httpx.HTTPStatusError as e:
        obs.status = "raw"
        await db.flush()
        raise ValueError(f"Mac-Agent Fehler: {e.response.status_code} — {e.response.text}")

    return {
        "job_id": data.get("job_id"),
        "status": data.get("status", "queued"),
        "agent_url": _cfg.pixinsight_agent_url,
        "input_dir": raw_rel,
        "output_dir": dev_rel,
        "frame_info": frame_info,
    }


async def check_job_status(job_id: str) -> dict[str, Any]:
    """Fragt den Status eines laufenden PixInsight-Jobs vom Mac-Agent ab."""
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                await _agent_url(f"/status/{job_id}"),
                params={"token": await _agent_token()},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"status": "unknown", "error": "Agent nicht erreichbar"}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"Agent: {e.response.status_code}"}


async def check_agent_health() -> dict[str, Any]:
    """Health-Check des Mac-Agents."""
    if not _cfg.pixinsight_agent_url:
        return {"available": False, "reason": "nicht konfiguriert"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(await _agent_url("/health"))
            resp.raise_for_status()
            data = resp.json()
            return {"available": True, **data}
    except Exception as e:
        return {"available": False, "reason": str(e)}
