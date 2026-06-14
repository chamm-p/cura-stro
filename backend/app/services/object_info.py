"""Hintergrundinfos zu Deep-Sky-Objekten via Wikipedia (Phase 3b).

Sucht einen passenden Wikipedia-Artikel (DE bevorzugt, EN als Fallback) über
mehrere Titel-Kandidaten (Eigenname, „Messier N", „NGC 7000" …) und cacht
Text + Quelle + Thumbnail in der DB. Kombiniert mit unseren Katalog-Fakten.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogObject
from app.models.object_info import ObjectInfo

logger = logging.getLogger(__name__)
_CACHE_DAYS = 120
_UA = {"User-Agent": "cura-stro/0.1 (astrophotography app)"}

_TYPE_DE = {
    "galaxy": "Galaxie", "open_cluster": "Offener Sternhaufen", "globular_cluster": "Kugelsternhaufen",
    "planetary_nebula": "Planetarischer Nebel", "emission_nebula": "Emissionsnebel",
    "reflection_nebula": "Reflexionsnebel", "supernova_remnant": "Supernova-Überrest",
    "cluster_nebulosity": "Sternhaufen mit Nebel", "nebula": "Nebel",
}


def _title_candidates(obj: CatalogObject) -> list[str]:
    titles: list[str] = []
    if obj.name:
        titles.append(obj.name)
    if obj.catalog == "Messier":
        n = re.sub(r"\D", "", obj.ident)
        if n:
            titles.append(f"Messier {n}")
    # Ident mit Leerzeichen: NGC7000 → "NGC 7000", IC1396 → "IC 1396".
    spaced = re.sub(r"([A-Za-z]+)(\d.*)", r"\1 \2", obj.ident)
    titles += [spaced, obj.ident]
    if obj.source_name and obj.source_name not in titles:
        titles.append(re.sub(r"([A-Za-z]+)0*(\d.*)", r"\1 \2", obj.source_name))
    # Duplikate raus, Reihenfolge erhalten.
    seen, out = set(), []
    for t in titles:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


async def _wiki_summary(client: httpx.AsyncClient, lang: str, title: str) -> dict | None:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code != 200:
            return None
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if d.get("type") == "disambiguation" or not d.get("extract"):
        return None
    return d


async def fetch_from_wikipedia(obj: CatalogObject) -> dict | None:
    async with httpx.AsyncClient(timeout=12.0, headers=_UA) as client:
        for lang in ("de", "en"):
            for title in _title_candidates(obj):
                d = await _wiki_summary(client, lang, title)
                if d:
                    return {
                        "source": f"wikipedia-{lang}",
                        "title": d.get("title"),
                        "text": d.get("extract"),
                        "url": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
                        "thumbnail_url": (d.get("thumbnail") or {}).get("source"),
                    }
    return None


def _catalog_facts(obj: CatalogObject) -> dict:
    facts = {}
    facts["Typ"] = _TYPE_DE.get(obj.obj_type, obj.obj_type)
    if obj.catalog and obj.catalog != "Other":
        facts["Katalog"] = obj.catalog
    if obj.magnitude is not None:
        facts["Helligkeit"] = f"{obj.magnitude} mag"
    if obj.size_major_arcmin:
        if obj.size_minor_arcmin:
            facts["Größe"] = f"{obj.size_major_arcmin}' × {obj.size_minor_arcmin}'"
        else:
            facts["Größe"] = f"{obj.size_major_arcmin}'"
    if obj.constellation:
        facts["Sternbild"] = obj.constellation
    return facts


async def get_object_info(db: AsyncSession, obj: CatalogObject, *, refresh: bool = False) -> ObjectInfo:
    """Liefert (gecachte) Hintergrundinfos; holt bei Bedarf von Wikipedia."""
    info = await db.scalar(select(ObjectInfo).where(ObjectInfo.catalog_object_id == obj.id))
    fresh = (
        info is not None
        and info.fetched_at is not None
        and info.fetched_at > datetime.now(timezone.utc) - timedelta(days=_CACHE_DAYS)
    )
    facts = _catalog_facts(obj)
    if info and fresh and not refresh:
        info.facts = facts  # Katalog-Fakten immer aktuell beilegen.
        return info

    wiki = await fetch_from_wikipedia(obj)
    if info is None:
        info = ObjectInfo(catalog_object_id=obj.id)
        db.add(info)
    info.facts = facts
    info.fetched_at = datetime.now(timezone.utc)
    if wiki:
        info.source = wiki["source"]
        info.title = wiki["title"]
        info.text = wiki["text"]
        info.url = wiki["url"]
        info.thumbnail_url = wiki["thumbnail_url"]
    await db.flush()
    return info
