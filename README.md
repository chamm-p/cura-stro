# cura-stro

**Astro-Imaging-Stack** — Selbst-gehostete Astrofotografie-App mit Backend/DB/Frontend, Fokus auf Katalogdaten, Bildarchivierung und 3D-Sonnensystem-Visualisierung.

## Stack

- **Backend:** FastAPI + async SQLAlchemy + PostgreSQL (Docker)
- **Frontend:** React/Vite/TypeScript (Docker/Nginx)
- **Auth:** OIDC (Keycloak) mit Single-User-Fallback
- **Wetter:** Open-Meteo + meteoblue Vision
- **Sichtbarkeit:** astropy (offline Ephemeride)

## Schnellstart

### Backend

```bash
cd backend
docker compose up -d --build
```

### Frontend

```bash
cd frontend
npm install && npm run dev
```

### Kompletter Stack

```bash
cd deploy
docker compose up -d --build
```

## Architektur

- Multi-Container (Docker Compose), deploy/.env steuert Konfiguration
- Alembic-Migrationen (0001–0024) für Datenbank-Updates
- API-Endpoints in `backend/app/api/`
- Design-System: `.curai/design-system.md` (Farben, Typografie, Layout)

## Features

- Objektliste mit Sichtbarkeit, Mond, Wetter, Teleskop-Status
- CRUD für Aufnahmen (geplant → raw → entwickelt)
- 3D-Sonnensystem-Visualisierung mit Three.js
- Zeitreise-Modus für Planetenkonstellationen
- Archivierung von Astro-Dateien (FITS/XISF/TIFF → JPG)

## Konfiguration

Umgebungsvariablen in `deploy/.env` (Kopie von `.env.example`):

| Variable | Beschreibung |
|---|---|
| `DATABASE_URL` | PostgreSQL-Verbindungszeichenfolge |
| `OIDC_ISSUER` | Keycloak-Issuer-URL |
| `ARCHIVE_PATH` | Lokaler oder NAS-Pfad für Bildarchiv |
| `LLM_GATEWAY` | Vision-LLM-Endpoint für Wolkenanalyse |

## Vorschau

Die laufende App ist unter `https://dev-prev.hammann.org/` erreichbar.