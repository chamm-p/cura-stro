# Auto-Build-Plan

**Ziel:** # Konzept: Sonnensystem-Visualisierung (Museum-Qualität)

## Ziel
Komplette Neuentwicklung der Sonnensystem-Seite (`/solarsystem`) als interaktive 3D-Visualisierung in Museum-Qualität. Planeten mit fotorealistischen Texturen ziehen ihre Bahn, Schatten und Beleuchtung sind physikalisch korrekt, Post-Processing (Bloom, Vignette, Unschärfe) sorgt für cineastische Atmosphäre. Steuerung per WASD, Mausrad-Zoom, Rechtsklick-Pivot und Klick-Fly-to mit Info-Overlay.

## Umgebung
- **Ziel:** Desktop-Browser (Chrome primär), keine Mobile-Optimierung erforderlich
- **Start:** `npm run dev` (Frontend) oder Docker Compose (`cd deploy && docker compose up -d --build`)
- **Frontend-Port:** 9601 (konfigurierbar)

## Nutzer & Zugriff
- **Öffentlich** — kein Login erforderlich, keine `ProtectedRoute`
- Prominenter **Backlink** zur Startseite (Dashboard) oben links

## Daten
- Alle Planeten-Daten als **Frontend-Konstanten** im TSX-Modul:
  - Kepler-Elemente (Bahnradius, Umlaufdauer, Neigung, Exzentrizität)
  - Physikalische Daten (Masse, Durchmesser, Temperatur, Atmosphäre, Monde)
  - Foto-Tipps (Belichtung, Filter, beste Zeit, Besonderheiten)
  - Echtfoto-URL (verlinkt auf NASA/Bildquelle)
- **Keine Backend-Abhängigkeit** — Seite läuft standalone

## Texturen
- **NASA / Solar System Scope** (frei nutzbar, hochauflösend)
- Werden als statische Assets im `frontend/public/textures/` mitgeliefert
- Pro Planet: Oberflächentextur (Color Map), optional Bump/Normal Map
- Sonne: Emissive-Textur mit Glow
- Sterne: Skybox / `Stars`-Komponente von drei/drei

## UI & Abläufe

### Steuerung
| Aktion | Eingabe | Effekt |
|---|---|---|
| Fliegen | WASD-Tasten | Kamera-Bewegung im 3D-Raum |
| Zoom | Mausrad | Dolly vor/zurück |
| Pivot | Rechtsklick + Mausbewegung | Kamera um Szenenmittelpunkt rotieren |
| Planet anfliegen | Klick auf Planet | Cineastischer Fly-to + Zentrierung + Info-Overlay |
| Name anzeigen | Maus-Hover über Planet | Sanftes Einblenden des Planetennamens (Label) |
| Zurück | Backli

## ☐ Baseline — bestehendes System zum Laufen bringen

- Start: `cd /work/frontend && npm run dev`
- 🖥️ Erreichbar: Port 9601 /solarsystem

## ☐ Milestone 1: Texturen & Schatten — fotorealistische Planeten, korrekte Beleuchtung

Alle 8 Planeten erhalten hochauflösende Color-Map-Texturen (NASA/Solar System Scope, als statische Assets in public/textures/). Die Sonne ist als Punktlichtquelle mit Shadow-Map konfiguriert; jeder Planet wirft und empfängt Schatten (shadow-mapSize ≥ 2048). Die sonnenabgewandte Seite ist visuell dunkler. Bloom wird so eingestellt, dass Umlaufbahnen NICHT unscharf erscheinen (Bloom nur auf emissive Materialien/Sonne, nicht global über die ganze Szene).

- Test: `cd /work/frontend && ls public/textures/ | grep -qi 'mercury\|venus\|earth\|mars\|jupiter\|saturn\|uranus\|neptune' && echo ok` — Prüft, dass Planeten-Texturen als statische Assets vorhanden sind
- Test: `cd /work/frontend && grep -q 'castShadow\|receiveShadow' src/components/SolarSystem/Planet.tsx && grep -qi 'shadow' src/components/SolarSystem/Sun.tsx && echo ok` — Prüft, dass Schatten konfiguriert sind (castShadow/receiveShadow + Sun-Light mit Shadow)
