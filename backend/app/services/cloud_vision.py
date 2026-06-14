"""meteoblue-Wolken via Vision-LLM (V2).

Der Seeing-Scraper liefert einen Screenshot der meteoblue-Seeing-Tabelle; die
Wolken sind dort farbcodiert (dunkelblau 0 % → rot 100 %), nicht als Zahl. Ein
Vision-LLM (curai-Gateway, OpenAI-kompatibel) liest die drei Schichten
Low/Mid/High pro Tag und Stunde aus. Wichtig: das Modell darf ZUERST frei
analysieren und gibt DANN den JSON-Block aus — erzwingt man „nur JSON",
verwechselt es die Schichten/erfindet Reihen.
"""

from __future__ import annotations

import base64
import json
import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()

_PROMPT = (
    "Dies ist eine meteoblue Astronomy-Seeing-Tabelle. Lies die Wolkenbedeckung "
    "pro Tag und Stunde ab. Es gibt drei Wolken-Schichten Low (tief), Mid (mittel), "
    "High (hoch), farbcodiert von dunkelblau (0%) bis rot (100%). Gehe sorgfältig "
    "Stunde für Stunde vor. Beschreibe ZUERST kurz in Prosa den Verlauf je Tag und "
    "gib DANACH einen Codeblock ```json "
    '{"hours":[{"date":"YYYY-MM-DD","hour":H,"low":I,"mid":I,"high":I}]}``` '
    "mit ALLEN ablesbaren Stunden (Werte 0–100)."
)


def is_enabled() -> bool:
    return bool(_cfg.llm_gateway_url and _cfg.llm_token)


async def fetch_seeing_image(meteoblue_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.get(f"{_cfg.seeing_scraper_url}/seeing", params={"url": meteoblue_url})
        r.raise_for_status()
        return r.content


def _clamp(v) -> int:
    return max(0, min(100, int(round(float(v)))))


def _parse_hours(text: str) -> list[dict]:
    """Stunden-Objekte aus der LLM-Antwort schälen — robust gegen Prosa UND
    abgeschnittenes JSON: jedes flache ``{...}`` mit ``date``+``hour`` einzeln
    parsen (so überlebt der Großteil, selbst wenn das Ende fehlt)."""
    out: dict[tuple[str, int], dict] = {}
    for obj in re.findall(r"\{[^{}]*\}", text):
        if '"date"' not in obj or '"hour"' not in obj:
            continue
        try:
            h = json.loads(obj)
            date = str(h["date"]).strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                continue
            hour = int(h["hour"])
            if not 0 <= hour <= 23:
                continue
            out[(date, hour)] = {
                "date": date, "hour": hour,
                "low": _clamp(h.get("low", 0)), "mid": _clamp(h.get("mid", 0)), "high": _clamp(h.get("high", 0)),
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(out.values(), key=lambda x: (x["date"], x["hour"]))


async def extract_clouds(image_bytes: bytes) -> list[dict]:
    if not is_enabled():
        return []
    b64 = base64.b64encode(image_bytes).decode()
    body = {
        "model": _cfg.llm_vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "temperature": 0,
        "max_tokens": 8000,
    }
    url = _cfg.llm_gateway_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=240.0) as client:
        r = await client.post(url, headers={"Authorization": f"Bearer {_cfg.llm_token}"}, json=body)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    hours = _parse_hours(content)
    logger.info("Vision-Wolken: %d Stunden extrahiert", len(hours))
    return hours


async def fetch_clouds(meteoblue_url: str) -> list[dict]:
    """Komplett: Screenshot holen → Vision-Extraktion. [] bei Fehler/deaktiviert."""
    if not is_enabled():
        return []
    try:
        img = await fetch_seeing_image(meteoblue_url)
        return await extract_clouds(img)
    except Exception as e:  # noqa: BLE001
        logger.warning("Vision-Wolken fehlgeschlagen: %s", e)
        return []
