"""MCP-Server (Phase 8) — exponiert Objektliste + Astrowetter für externe
LLM-Lösungen (z. B. curai) via Streamable HTTP unter ``/mcp``.

Anbindung per ``mcp-remote`` mit Token-Header (siehe deploy/.env.example).
Single-User: die Tools laufen auf den Daten des ersten (Admin-)Users.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from app.database import async_session
from app.models.catalog import CatalogObject
from app.models.observing import Location
from app.models.user import User
from app.services import object_info as oi
from app.services import target_service

# uvicorn.error-Logger → erscheint zuverlässig in `docker compose logs backend`.
logger = logging.getLogger("uvicorn.error")

# streamable_http_path="/" → die ASGI-App bedient die Wurzel; wir mounten sie
# unter /mcp, sodass der externe Endpunkt genau .../mcp/ ist.
# DNS-Rebinding-Schutz aus: Zugriff läuft hinter nginx (Host wechselt) und ist
# bereits per Token-Header abgesichert (siehe main.py:mcp_token_guard).
mcp = FastMCP(
    "cura-stro",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _user(db) -> User | None:
    """Den tatsächlich genutzten Account wählen: Eigentümer des zuletzt
    angelegten Standorts (Single-User, aber OIDC legt einen separaten User an,
    während der Bootstrap-`astro`-User leer bleibt). Fallback: zuletzt
    eingeloggt, sonst der erste User."""
    loc = await db.scalar(select(Location).order_by(Location.created_at.desc()))
    if loc:
        owner = await db.get(User, loc.user_id)
        if owner:
            return owner
    return await db.scalar(select(User).order_by(User.last_login.desc().nullslast(), User.created_at))


@mcp.tool()
async def list_good_targets(
    date: str | None = None,
    location: str | None = None,
    catalog: str | None = None,
    object_type: str = "all",
    min_altitude: float = 30.0,
    max_magnitude: float | None = None,
    limit: int = 15,
) -> dict:
    """Gute Astrofoto-Ziele für eine Nacht.

    Args:
        date: Abend-Datum YYYY-MM-DD (Default: heute am Standort).
        location: Standortname (Default: Standard-Standort).
        catalog: Messier | NGC | IC | all.
        object_type: all | galaxy | cluster | nebula | planet.
        min_altitude: Mindesthöhe in Grad (Default 30).
        max_magnitude: maximale Magnitude (Helligkeitsgrenze).
        limit: max. Anzahl Ergebnisse.

    Liefert Standort, Mond, Wetter-Urteil und eine Liste sichtbarer Objekte
    mit Höhe, bester Zeit, Aufnahmefenster und Mondlicht-Einschätzung.
    """
    async with async_session() as db:
        user = await _user(db)
        if not user:
            return {"error": "Kein Benutzer vorhanden."}
        res = await target_service.good_targets(
            db, user, date=date, location_name=location, catalog=catalog,
            type_group=object_type, min_altitude=min_altitude, max_magnitude=max_magnitude, limit=limit,
        )
        logger.info("MCP list_good_targets user=%s loc=%s → %s", user.username, location,
                    res.get("error") or f"{res.get('count')} Ziele @ {res.get('location')}")
        return res


@mcp.tool()
async def get_astro_weather(date: str | None = None, location: str | None = None) -> dict:
    """Astrowetter + Mond für eine Nacht.

    Args:
        date: Abend-Datum YYYY-MM-DD (Default: heute).
        location: Standortname (Default: Standard-Standort).

    Liefert Bewölkung (gesamt + Schichten), Niederschlag, Wind, Mondphase
    und -beleuchtung für das Nachtfenster des Standorts.
    """
    async with async_session() as db:
        user = await _user(db)
        if not user:
            return {"error": "Kein Benutzer vorhanden."}
        res = await target_service.astro_weather(db, user, date=date, location_name=location)
        logger.info("MCP get_astro_weather user=%s → %s", user.username, res.get("error") or res.get("location"))
        return res


@mcp.tool()
async def get_object_info(ident: str) -> dict:
    """Hintergrundinfos zu einem Deep-Sky-Objekt (Wikipedia + Katalogdaten).

    Args:
        ident: Objektbezeichnung, z. B. M31, NGC7000, IC1396.
    """
    async with async_session() as db:
        obj = await db.scalar(select(CatalogObject).where(CatalogObject.ident == ident.strip()))
        logger.info("MCP get_object_info ident=%s → %s", ident, "ok" if obj else "nicht gefunden")
        if not obj:
            return {"error": f"Objekt '{ident}' nicht im Katalog."}
        info = await oi.get_object_info(db, obj)
        return {
            "ident": obj.ident, "name": obj.name, "facts": info.facts or {},
            "source": info.source, "title": info.title, "text": info.text, "url": info.url,
        }
