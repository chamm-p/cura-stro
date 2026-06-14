# cura-stro 🔭

Selbst-gehostete Astrofotografie-App: gute Foto-Objekte für deinen
Standort und die Nacht berechnen, Astrowetter & Mond berücksichtigen,
fotografierte Objekte verwalten, Astro-Dateien (FITS/XISF/TIFF)
analysieren und nach JPG konvertieren — abgesichert per Keycloak (OIDC)
mit lokalem Fallback. Plus ein MCP-Server, damit andere LLM-Lösungen
(z. B. curai) Objektliste und Astrowetter abfragen können.

## Stack

- **Backend:** FastAPI · async SQLAlchemy · Alembic · PostgreSQL 16
- **Frontend:** React 19 · Vite · TypeScript · Tailwind v4 · Inter
- **Auth:** Generic OIDC (Authlib) + lokaler Fallback-User
- **Astro:** astropy / astroplan (folgt) · hips2fits-Previews
- **Deploy:** docker-compose, Multi-Arch (amd64 + arm64)

## Schnellstart

```bash
cd deploy
cp .env.example .env        # Werte anpassen (SECRET_KEY, Passwörter, OIDC)
docker compose up -d --build
```

- Frontend: http://localhost:9601
- Backend-Health: http://localhost:9605/api/health

Beim ersten Start wird der lokale Default-User aus der `.env` angelegt
(`DEFAULT_USER_USERNAME` / `DEFAULT_USER_PASSWORD`).

### Optionaler Galaxy-Video-Loop

Der Login-Screen zeigt standardmäßig eine animierte Canvas-Galaxie. Legst
du eine `frontend/public/galaxy.mp4` ab, wird sie zusätzlich eingeblendet.

## Datenquellen

- **Deep-Sky-Katalog:** [OpenNGC](https://github.com/mattiaverga/OpenNGC)
  (CC-BY-SA-4.0) — gebündelt als `backend/app/data/catalog.json`, erzeugt
  per `backend/scripts/build_catalog.py`.
- **Objekt-Previews:** CDS [hips2fits](https://alasky.cds.unistra.fr/hips-image-services/hips2fits)
  (DSS2-Color), kein API-Key.
- **Hintergrundinfos:** Wikipedia REST-Summary (DE→EN), gecacht.
- **Geocoding:** OpenStreetMap Nominatim (Reverse/Suche), Open-Meteo
  (Höhe). Bei Eigenbetrieb die Nutzungsrichtlinien beachten.
- **Astrowetter:** Open-Meteo (Bewölkung/Wind/Feuchte, kein Key).
- **Seeing:** optionaler `weather-scraper`-Container (Playwright) lädt die
  meteoblue Astronomy-Seeing-Seite (URL pro Standort hinterlegbar) und
  liefert einen gecachten Screenshot. Mond via astropy.

## MCP-Server (für curai & andere LLMs)

cura-stro stellt unter `/mcp/` einen **Streamable-HTTP-MCP-Server** bereit
mit den Tools `list_good_targets`, `get_astro_weather`, `get_object_info`.
Absicherung über einen Token-Header (`MCP_TOKEN` in `deploy/.env`).

Anbindung per `mcp-remote` (z. B. in curai / Claude Desktop):

```json
{
  "mcpServers": {
    "cura-stro": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<dein-host>/mcp/",
        "--header",
        "x-curastro-token: <MCP_TOKEN>"
      ]
    }
  }
}
```

> Wichtig: URL **mit Trailing Slash** (`/mcp/`). Der Token-Header kann
> alternativ `Authorization: Bearer <MCP_TOKEN>` sein.

## Status

Aufbau in Phasen — siehe Implementierungsplan. Umgesetzt:
**Phase 0** (Gerüst/Deployment), **Phase 1** (Auth + Login-Screen),
**Phase 2** (Standorte/Equipment/Settings), **Phase 3** (Objektliste mit
astropy-Sichtbarkeit, Katalog, Höhenkurven, Typ-/Teleskopfilter, Planeten,
hips2fits-Previews), **Phase 4** (Astrowetter via Open-Meteo, Mondlicht-
Warnungen, meteoblue-Seeing-Scraper), **Phase 5** (Verwaltung), **Phase 6**
(FITS/XISF/TIFF-Upload + Analyse + JPG), **Phase 7** (Framing-/Belichtungs-
rechner), **Phase 3b** (Objekt-Hintergrundinfos), **Phase 8** (MCP-Server).
