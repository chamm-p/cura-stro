"""meteoblue Seeing-Scraper (Playwright/Chromium).

Lädt die meteoblue Outdoorsports/Seeing-Seite und liefert einen Screenshot
des Seeing-Meteogramms. DOM-Textparsing wäre zu brüchig — das Bild ist die
robuste, immer brauchbare Repräsentation (der/die Nutzer:in liest das Seeing
wie auf meteoblue ab). Zusätzlich Best-Effort-Extraktion sichtbarer Werte.

Endpunkte:
  GET /health
  GET /seeing?url=<meteoblue-seeing-url>   → image/png
"""

import logging

from fastapi import FastAPI, HTTPException, Query, Response
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seeing-scraper")

app = FastAPI(title="cura-stro seeing-scraper")

# Kandidaten-Selektoren für die Seeing-Sektion (meteoblue ändert das Markup
# gelegentlich → mehrere Fallbacks, am Ende ganzseitiger Clip).
_SEEING_SELECTORS = [
    "table.table-seeing",  # meteoblue Astronomy-Seeing-Tabelle (alle Tage)
    "div.seeing-content",
    "#seeing",
    "section:has(h2:has-text('Seeing'))",
]
_CONSENT = [
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Zustimmen')",
    "button:has-text('Accept all')",
    "button:has-text('Agree')",
    "[aria-label='Consent'] button",
]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/seeing")
async def seeing(url: str = Query(...)):
    if "meteoblue.com" not in url:
        raise HTTPException(400, "Nur meteoblue-URLs erlaubt")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = await browser.new_page(
                viewport={"width": 1280, "height": 1700},
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            for sel in _CONSENT:
                try:
                    await page.click(sel, timeout=1500)
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(3500)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            element = None
            for sel in _SEEING_SELECTORS:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        element = el
                        break
                except Exception:
                    continue

            if element is not None:
                png = await element.screenshot(type="png")
            else:
                # Fallback: oberer Seitenbereich (Seeing steht meist oben).
                png = await page.screenshot(type="png", clip={"x": 0, "y": 0, "width": 1280, "height": 1200})

            await browser.close()
            return Response(content=png, media_type="image/png")
    except Exception as e:
        logger.exception("Seeing-Scrape fehlgeschlagen")
        raise HTTPException(502, f"meteoblue konnte nicht geladen werden: {e}")
