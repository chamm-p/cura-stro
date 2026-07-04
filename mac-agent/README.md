# cura-stro Mac-Agent — PixInsight Batch-Verarbeitung

Kleiner HTTP-Service, der auf dem Mac läuft und PixInsight headless (ohne GUI)
startet. Wird vom cura-stro-Backend getriggert, sobald eine Aufnahme verarbeitet
werden soll.

## Architektur

```
cura-stro Backend  ──HTTP──▶  Mac-Agent (dieser Service)
                                  │
                                  ├──▶ PixInsight CLI (headless)
                                  │      └── cura_batch.js (PJSR-Skript)
                                  │
                                  ├──▶ liest RAW/<Objekt>/<Gerät>/  (NAS-Mount)
                                  └──▶ schreibt Developer/<Objekt>/<Gerät>/  (NAS-Mount)
```

Der Mac muss das gleiche NAS-Volume gemountet haben wie das cura-stro-Backend.
Der Agent erhält die *relativen* Pfade (z. B. `RAW/IC 417/ASK 2600/`) und setzt
seinen eigenen Mount-Prefix davor (konfigurierbar via `NAS_MOUNT_PREFIX`).

## Installation

### 1. Python-Abhängigkeiten

```bash
cd cura-stro/mac-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. PixInsight-Pfad prüfen

Standard-Pfad auf dem Mac:
```
/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight
```

Falls abweichend, via Umgebungsvariable setzen:
```bash
export PIXINSIGHT_BIN=/pfad/zu/PixInsight
```

### 3. NAS-Mount konfigurieren

Der Mac muss das NAS-Volume mounten, auf dem das cura-stro-Archiv liegt.
Der Mount-Pfad wird via `NAS_MOUNT_PREFIX` konfiguriert:

```bash
# Beispiel: NAS ist gemountet unter /Volumes/astro
export NAS_MOUNT_PREFIX=/Volumes/astro
```

Der Agent setzt dann z. B. `/Volumes/astro/RAW/IC 417/ASK 2600/` zusammen.

### 4. Shared-Secret setzen

Das gleiche Token wie im cura-stro-Backend (`.env`: `PIXINSIGHT_AGENT_TOKEN`):

```bash
export AGENT_TOKEN=dein-shared-secret
```

### 5. Starten (Development)

```bash
python agent.py
# Läuft auf http://0.0.0.0:7777
```

### 6. Als launchd-Daemon installieren (Auto-Start)

```bash
# Pfade in com.cura-stro.agent.plist anpassen!
sudo cp com.cura-stro.agent.plist /Library/LaunchDaemons/
sudo launchctl load /Library/LaunchDaemons/com.cura-stro.agent.plist
```

Logs: `/tmp/cura-stro-agent.log`

## API-Endpoints

| Method | Path | Beschreibung |
|--------|------|-------------|
| `GET`  | `/health` | Health-Check (PixInsight gefunden? Skript vorhanden?) |
| `POST` | `/process` | Job annehmen & PixInsight starten |
| `GET`  | `/status/{job_id}` | Job-Status abfragen |
| `GET`  | `/jobs` | Alle Jobs auflisten |
| `GET`  | `/logs/{job_id}` | Log-Inhalt eines Jobs |
| `DELETE` | `/jobs/{job_id}` | Abgeschlossenen Job löschen |

### POST /process

```json
{
  "input_dir": "RAW/IC 417/ASK 2600/",
  "output_dir": "Developer/IC 417/ASK 2600/",
  "frame_info": {
    "object_name": "IC 417",
    "device_name": "ASK 2600",
    "total_subs": 120,
    "filters": [
      {"filter": "H", "subs": 60, "exposures_s": [300.0]},
      {"filter": "OIII", "subs": 60, "exposures_s": [300.0]}
    ],
    "frame_types": {"light": 120, "dark": 30, "flat": 20, "bias": 50}
  },
  "token": "dein-shared-secret"
}
```

## cura_batch.js — PixInsight Batch-Skript

Das mitgelieferte PJSR-Skript führt die klassische Vorverarbeitung durch:

1. **Dateien sortieren** nach Frame-Typ (ASIAir-Namenskonvention: `Light_…`, `Dark_…`, `Flat_…`, `Bias_…`)
2. **Master-Frames erstellen** (Bias/Dark/Flat mitteln via ImageIntegration)
3. **ImageCalibration** — Lights mit Bias/Dark/Flat kalibrieren
4. **StarAlignment** — Lights registrieren (auf Referenz-Frame)
5. **ImageIntegration** — Kalibrierte & ausgerichtete Lights zum Master stacken
6. **Ergebnis** ins Output-Verzeichnis schreiben (`master_<Objekt>_<Filter>.xisf`)

### WBPP-Alternative

Statt des eigenen Skripts kann auch das beliebte **WeightedBatchPreProcessing
(WBPP)**-Script verwendet werden. Dazu `BATCH_SCRIPT` auf den WBPP-Pfad setzen:

```bash
export BATCH_SCRIPT=/Applications/PixInsight/src/scripts/BatchProcessing/WeightedBatchPreProcessing.js
```

WBPP bietet erweiterte Funktionen (LocalNormalization, Drizzle, automatische
Gruppierung), ist aber komplexer in der headless-Konfiguration.

## Status-Fluss in cura-stro

```
geplant → raw → in_bearbeitung → entwickelt
                       │                ▲
                       │                │ Watch-Loop erkennt
                       │                │ neue Datei im
                       └─ Mac-Agent ────┘ Developer-Ordner
                          schreibt Ergebnis
```

- `raw`: Subs importiert, bereit zur Verarbeitung
- `in_bearbeitung`: PixInsight-Batch läuft auf dem Mac (neu)
- `entwickelt`: Ergebnis im Developer-Ordner (Watch-Loop setzt automatisch)

## Fehlersuche

| Problem | Lösung |
|---------|--------|
| Agent nicht erreichbar | Mac an? Port 7777 frei? `launchctl list \| grep cura-stro` |
| PixInsight nicht gefunden | `PIXINSIGHT_BIN` prüfen, `GET /health` |
| Keine Light-Frames | Input-Verzeichnis prüfen, NAS-Mount korrekt? |
| Job failed | `GET /logs/{job_id}` für PixInsight-Log |
| Token-Fehler (403) | `AGENT_TOKEN` auf beiden Seiten gleich? |
