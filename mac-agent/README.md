# cura-stro Mac-Agent — PixInsight Batch-Verarbeitung

Kleiner HTTP-Service, der auf dem Mac läuft und PixInsight headless (ohne GUI)
startet. Wird vom cura-stro-Backend getriggert, sobald eine Aufnahme verarbeitet
werden soll.

## Architektur (File-Broker-Modus)

Der Mac braucht **keinen SMB-Mount** auf das NAS. Alle Dateien werden über
HTTP transferiert:

```
cura-stro Backend                    Mac-Agent (dieser Service)
(liest NAS per SMB)                   (PixInsight lokal)
       │
       │  1. RAW-Dateien vom NAS lesen
       │  2. Als ZIP packen
       │  3. POST /process (multipart upload)
       │──────────────────────────────▶│
       │                               │  4. ZIP entpacken
       │                               │  5. PixInsight + WBPP starten
       │                               │  6. Ergebnisse als ZIP packen
       │  7. GET /results/{job_id}     │
       │◀──────────────────────────────│
       │  8. Ergebnis-ZIP entpacken
       │  9. Auf NAS schreiben (Prepared/)
       │ 10. Status → 'vorbereitet'
       │
       │  Später: Nutzer entwickelt manuell in PixInsight
       │  → legt Ergebnis in Developer/ → Watch-Loop → 'entwickelt'
```

### Status-Fluss

```
geplant → raw → in_bearbeitung → vorbereitet → entwickelt
                         │              │           │
                         │              │           └─ Watch-Loop erkennt
                         │              │              Developer-Dateien
                         │              └─ WBPP fertig, Master in Prepared/
                         └─ PixInsight-Batch läuft auf dem Mac
```

## Setup

### 1. Voraussetzungen

- PixInsight ist auf dem Mac installiert
- Python 3.10+
- Der Mac ist im selben Netzwerk wie das cura-stro-Backend

### 2. Installation

```bash
cd cura-stro/mac-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfiguration

Umgebungsvariablen (in `.env` oder direkt beim Start):

| Variable | Default | Beschreibung |
|---|---|---|
| `AGENT_PORT` | `7777` | Port, auf dem der Agent lauscht |
| `AGENT_TOKEN` | (leer) | Shared-Secret mit dem Backend (muss gleich sein) |
| `PIXINSIGHT_BIN` | `/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight` | Pfad zur PixInsight-Binary |
| `BATCH_SCRIPT` | `cura_batch.js` (neben agent.py) | Pfad zum Batch-Skript |
| `WBPP_SCRIPT` | `…/WeightedBatchPreProcessing.js` | Pfad zum WBPP-Skript |
| `WORK_DIR` | `~/cura-stro-jobs` | Temporäres Arbeitsverzeichnis |
| `MAX_CONCURRENT` | `1` | Maximal gleichzeitige PixInsight-Prozesse |

### 4. Start

```bash
# Development
python agent.py

# Mit Token
AGENT_TOKEN="dein-shared-secret" python agent.py

# Production (launchd-Daemon)
cp com.cura-stro.agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cura-stro.agent.plist
```

### 5. Backend-Konfiguration

Im cura-stro Backend `.env`:

```env
PIXINSIGHT_AGENT_URL=http://<mac-ip>:7777
PIXINSIGHT_AGENT_TOKEN=<gleicher-token-wie-auf-dem-mac>
```

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/health` | Health-Check (PixInsight gefunden? WBPP gefunden?) |
| `POST` | `/process` | Job annehmen (ZIP-Upload) & PixInsight starten |
| `GET` | `/status/{job_id}` | Job-Status abfragen |
| `GET` | `/results/{job_id}` | Ergebnis-ZIP herunterladen (wenn completed) |
| `GET` | `/jobs` | Alle Jobs auflisten |
| `GET` | `/logs/{job_id}` | Log-Inhalt eines Jobs |
| `DELETE` | `/jobs/{job_id}` | Abgeschlossenen Job löschen (inkl. Temp-Dateien) |

## WBPP (WeightedBatchPreProcessing)

Das Batch-Skript (`cura_batch.js`) versucht zuerst, das WBPP-Skript von
PixInsight aufzurufen. WBPP übernimmt die komplette Vorverarbeitung:

- Master-Kalibrierung (Bias/Dark/Flat)
- ImageCalibration
- StarAlignment (Registrierung)
- LocalNormalization (optional)
- ImageIntegration (Stacking mit Signal-Gewichtung)
- Drizzle (optional)

Falls WBPP nicht gefunden wird oder fehlschlägt, fällt das Skript auf einen
manuellen Durchlauf (ImageCalibration → StarAlignment → ImageIntegration)
zurück.

### WBPP-Pfad anpassen

Der Standard-Pfad für WBPP auf dem Mac ist:
```
/Applications/PixInsight/src/scripts/BatchProcessing/WeightedBatchPreProcessing.js
```

Falls dein WBPP woanders liegt, setze `WBPP_SCRIPT`:
```bash
WBPP_SCRIPT="/pfad/zu/WeightedBatchPreProcessing.js" python agent.py
```

## Sicherheit

- Setze `AGENT_TOKEN` auf beiden Seiten (Backend + Agent) auf denselben Wert
- Der Agent lauscht auf `0.0.0.0` — stelle sicher, dass nur das Backend ihn
  erreichen kann (Firewall / VLAN)
- Temp-Dateien werden in `WORK_DIR` gespeichert und können mit
  `DELETE /jobs/{job_id}` aufgeräumt werden
