# Konzept: Sonnensystem-Visualisierung (Museum-Qualität)

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
| Zurück | Backlink-Button | Navigation zur Startseite |

### Info-Overlay (bei Klick auf Planet)
- **Physik:** Masse, Durchmesser, Temperatur, Atmosphäre, Monde, Umlaufdauer
- **Foto-Tipps:** Belichtungszeit, Filter, beste Aufnahmezeit, Besonderheiten
- **Echtfoto:** Bild des Planeten (NASA/Bildquelle)
- Einblendung mit Animation (fader/slide), schließbar

### Post-Processing
- **Bloom** — Sonnen-Glow, helle Planetenränder
- **Vignette** — Abdunklung der Ränder für Fokus
- **Depth of Field / Unschärfe** — Hintergrundsterne leicht unscharf
- **Tone Mapping** — ACES Filmic für cineastische Farbwiedergabe

### Sternenhimmel
- `Stars`-Komponente (drei/drei) oder Skybox-Textur
- Tausende Sterne, leicht unscharf durch DoF

## Überraschungs-Feature: Time-Warp-Slider
Ein Slider am unteren Bildschirmrand, der die **Umlaufgeschwindigkeit aller Planeten** dynamisch steuert — von Zeitlupe (0.1×) bis Zeitraffer (100×). Standardwert so gewählt, dass Bewegung gut sichtbar ist (~1× = beschleunigte Echtzeit). Der Slider stört die Kamera-Steuerung nicht und hat eine sanfte Glow-Animation. Zusätzlich: **Tages-/Nachtzyklus-Anzeige** — ein kleines HUD zeigt das simulierte Datum basierend auf der verstrichenen Zeit.

## Architektur

### Dateien
| Datei | Zweck |
|---|---|
| `frontend/src/pages/SolarSystem.tsx` | Hauptkomponente — Canvas, Szene, Steuerung, State |
| `frontend/src/components/SolarSystem/Planet.tsx` | Einzelner Planet (Mesh, Textur, Orbit, Schatten) |
| `frontend/src/components/SolarSystem/Sun.tsx` | Sonne mit Emissive-Glow und Lichtquelle |
| `frontend/src/components/SolarSystem/Orbit.tsx` | Bahnring-Linie pro Planet |
| `frontend/src/components/SolarSystem/InfoPanel.tsx` | Info-Overlay (Physik, Foto-Tipps, Echtfoto) |
| `frontend/src/components/SolarSystem/TimeWarpSlider.tsx` | Geschwindigkeits-Slider + HUD |
| `frontend/src/components/SolarSystem/PlanetLabel.tsx` | Hover-Label (sanftes Einblenden) |
| `frontend/src/data/planets.ts` | Planeten-Konstanten (Kepler, Physik, Foto, Texturen) |
| `frontend/public/textures/` | Texturen-Assets (NASA/Solar System Scope) |

### Komponenten-Struktur
```
SolarSystem.tsx (Canvas + Scene)
├── Sun (Lichtquelle + Emissive-Mesh)
├── Stars (Hintergrund)
├── Planet[] (pro Planet: Mesh + Orbit + Label)
├── EffectComposer (Bloom, Vignette, DoF)
├── OrbitControls (Rechtsklick-Pivot, Zoom)
├── WASDControls (Custom useFrame-Kamera-Bewegung)
├── InfoPanel (Overlay bei Klick)
└── TimeWarpSlider (Geschwindigkeits-Steuerung)
```

### Tech-Stack
- **React 19** + **TypeScript** + **Vite**
- **@react-three/fiber** — React-Renderer für Three.js
- **@react-three/drei** — `Stars`, `OrbitControls`, `Html`, `Text`, `useTexture`
- **@react-three/postprocessing** — `EffectComposer`, `Bloom`, `Vignette`, `DepthOfField`
- **Tailwind CSS 4** — UI-Overlays (InfoPanel, Slider, Backlink)
- **Zustand** — State für ausgewählten Planet, Time-Warp-Geschwindigkeit
- **framer-motion** — Animationen für Info-Panel und Labels

### Performance
- Texturen asynchron laden (`useTexture` / `suspend`)
- `useFrame` für flüssige Animationen (60fps)
- Schatten nur für nahe Planeten (Shadow-Map-Optimierung)
- Sterne als Points (nicht als Meshes)

## Meilensteine
1. **Szene & Beleuchtung** — Canvas, Sonne, Sterne, Licht, Post-Processing
2. **Planeten & Bahnen** — Texturen, Orbit-Animation, Schatten, Labels
3. **Steuerung** — WASD, Mausrad-Zoom, Rechtsklick-Pivot, Klick-Fly-to
4. **Info-Overlay** — Physik, Foto-Tipps, Echtfoto, Animation
5. **Time-Warp-Slider** — Geschwindigkeits-Steuerung + HUD
6. **Polish** — Backlink, Hover-Labels, Tone-Mapping, Performance-Tuning

## Nicht-Ziele
- Keine Mobile-/Touch-Optimierung
- Keine Backend-Änderungen oder API-Anbindung
- Keine Benutzerverwaltung / Auth auf dieser Seite
- Keine Bearbeitung der alten `SolarSystemPage.jsx` (wird durch `.tsx` ersetzt)
- Keine physische Akkuratheit der Skalierung (Abstände/Größen werden für Visualisierbarkeit skaliert)