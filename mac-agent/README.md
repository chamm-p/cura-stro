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
       │                               │  5. PixInsight + WBPP/FastBatch starten
       │                               │     (oder Shell-Simulation im Test-Modus)
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

### Processing-Modi

| Modus | Beschreibung |
|---|---|
| `wbpp` | WeightedBatchPreProcessing — vollständig, langsam (Standard) |
| `fastbatch` | FastBatchProcessing — schneller, weniger Optionen |
| `shell_sim` | Shell-Simulation — kein PixInsight nötig, validiert den HTTP-Flow |

Im `shell_sim`-Modus werden die Light-Frames einfach als "Master" kopiert.
Das ist nützlich, um den gesamten Workflow (Backend → Agent → Ergebnisse → NAS)
zu testen, ohne dass PixInsight installiert sein muss.

### Calibration-Frames (Flats/Darks/Bias)

Pro Setup (Teleskop+Kamera) kann im cura-stro-UI (Settings → Equipment) ein
**Calibration-Dir** hinterlegt werden. Das ist ein Pfad auf dem Mac, wo die
Kalibrierungs-Frames für dieses Setup liegen. Der Pfad wird an den Mac-Agent
durchgereicht und PixInsight/WBPP berücksichtigt diese Frames automatisch.

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

- PixInsight ist auf dem Mac installiert (nicht nötig für `shell_sim`-Modus)
- Python 3.10+ (auf dem Mac vorinstalliert, prüfe mit `python3 --version`)
- Der Mac ist im selben Netzwerk wie das cura-stro-Backend

### 2. Installation

```bash
# Repo klonen (falls noch nicht geschehen)
git clone https://github.com/chamm-p/cura-stro.git
cd cura-stro/mac-agent

# Virtualenv erstellen (isoliert die Python-Abhängigkeiten)
python3 -m venv .venv

# Virtualenv aktivieren — WICHTIG: danach ist 'pip' verfügbar
source .venv/bin/activate

# Jetzt pip installieren (funktioniert nur im aktivierten venv!)
pip install -r requirements.txt

# Falls pip trotzdem nicht gefunden wird, alternativ:
# python3 -m pip install -r requirements.txt
```

> **Hinweis:** Nach `source .venv/bin/activate` siehst du `(.venv)` vorne
> im Terminal-Prompt. Erst dann ist `pip` als Befehl verfügbar. Ohne aktives
> venv musst du `python3 -m pip` statt `pip` verwenden.

### 3. Token erzeugen (einmalig, shared mit Backend)

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Kopiere den ausgegebenen String — das ist dein `AGENT_TOKEN`.

### 4. Konfiguration

Umgebungsvariablen (direkt beim Start oder in einer `.env`-Datei neben `agent.py`):

| Variable | Default | Beschreibung |
|---|---|---|
| `AGENT_PORT` | `7777` | Port, auf dem der Agent lauscht |
| `AGENT_TOKEN` | (leer) | Shared-Secret mit dem Backend (muss gleich sein) |
| `PIXINSIGHT_BIN` | `/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight` | Pfad zur PixInsight-Binary |
| `BATCH_SCRIPT` | `cura_batch.js` (neben agent.py) | Pfad zum Batch-Skript |
| `WBPP_SCRIPT` | `…/WeightedBatchPreProcessing.js` | Pfad zum WBPP-Skript |
| `FASTBATCH_SCRIPT` | `…/FastBatchProcessing.js` | Pfad zum FastBatch-Skript |
| `WORK_DIR` | `~/cura-stro-jobs` | Temporäres Arbeitsverzeichnis |
| `MAX_CONCURRENT` | `1` | Maximal gleichzeitige PixInsight-Prozesse |

### 5. Start

```bash
# Virtualenv aktivieren (falls noch nicht aktiv)
source .venv/bin/activate

# Development (ohne Token — nur für Tests)
python3 agent.py

# Mit Token (empfohlen)
AGENT_TOKEN="dein-token-aus-schritt-3" python3 agent.py

# Health-Check im Browser oder Terminal:
#   Browser:  http://localhost:7777/health
#   Terminal: curl http://localhost:7777/health
```

Der Agent läuft jetzt und wartet auf Aufträge vom Backend.

### 6. Backend konfigurieren (auf dem Linux-Server)

In der `.env` des cura-stro-Backends (z. B. `/opt/cura-stro/deploy/.env`):

```env
PIXINSIGHT_AGENT_URL=http://<mac-ip>:7777
PIXINSIGHT_AGENT_TOKEN=<gleicher-token-wie-auf-dem-mac>
```

> Die `deploy/.env.example` enthält diese Zeilen bereits als Vorlage.
> Ersetze `<mac-ip>` durch die IP-Adresse deines Mac im lokalen Netzwerk
> (z. B. `192.168.1.42`) und den Token durch den aus Schritt 3.

Danach das Backend neu starten.

### 7. Verarbeitung auslösen

1. cura-stro im Browser öffnen
2. Zur **Verwaltung** (Manage-Seite)
3. Eine Aufnahme mit Status **`raw`** anklicken → **Ergebnis-Modal**
4. In der **PixInsight**-Sektion:
   - Health-Check zeigt: Agent erreichbar? PixInsight gefunden?
   - **Processing-Modus wählen**: WBPP / FastBatch / Shell-Sim
   - Button **"In PixInsight verarbeiten"** klicken
5. Das Backend überträgt die RAW-Dateien als ZIP an den Mac, der Mac startet
   PixInsight mit WBPP (oder Shell-Sim), das Backend pollt bis fertig und
   holt die Ergebnisse zurück
6. Status wechselt auf **`vorbereitet`** — Master-Files liegen im
   `Prepared/`-Ordner auf dem NAS

### 8. Calibration-Dir festlegen (optional, pro Setup)

1. cura-stro → **Einstellungen** → **Equipment**-Tab
2. Beim jeweiligen Setup (Teleskop+Kamera) auf **"Calib-Frames"** klicken
3. Pfad auf dem Mac eingeben, z. B. `/Users/astro/PixInsight/Calibration/E127-ASI2600`
4. Speichern — dieser Pfad wird automatisch an den Mac-Agent durchgereicht

### 9. Manuell weiterentwickeln

- PixInsight manuell öffnen
- Master-Files aus `Prepared/<Objekt>/<Gerät>/` laden
- Bild entwickeln (Stretching, Rauschreduktion, Farbkalibrierung, etc.)
- Fertiges Bild in `Developer/<Objekt>/<Gerät>/` speichern
- Die Watch-Loop im Backend erkennt die Datei automatisch → Status **`entwickelt`**

## Production (launchd-Daemon)

Für dauerhaften Betrieb (startet automatisch beim Booten):

```bash
# 1. Agent installieren
sudo mkdir -p /usr/local/bin/cura-stro-agent
sudo cp agent.py cura_batch.js requirements.txt /usr/local/bin/cura-stro-agent/
cd /usr/local/bin/cura-stro-agent
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

# 2. plist anpassen (Token, Pfade) und installieren
cp com.cura-stro.agent.plist ~/Library/LaunchAgents/
# Token in der plist anpassen!
launchctl load ~/Library/LaunchAgents/com.cura-stro.agent.plist
```

Logs: `/tmp/cura-stro-agent.log` und `/tmp/cura-stro-agent.err`

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/health` | Health-Check (PixInsight gefunden? WBPP gefunden? Shell-Sim verfügbar?) |
| `POST` | `/process` | Job annehmen (ZIP-Upload) & PixInsight starten — Form-Felder: `mode`, `calibration_dir`, `frame_info`, `token` |
| `GET` | `/status/{job_id}` | Job-Status abfragen |
| `GET` | `/results/{job_id}` | Ergebnis-ZIP herunterladen (wenn completed) |
| `GET` | `/jobs` | Alle Jobs auflisten |
| `GET` | `/logs/{job_id}` | Log-Inhalt eines Jobs |
| `DELETE` | `/jobs/{job_id}` | Abgeschlossenen Job löschen (inkl. Temp-Dateien) |

## Shell-Simulation testen (ohne PixInsight)

Um den gesamten Workflow zu testen, ohne dass PixInsight installiert ist:

1. Mac-Agent starten: `python3 agent.py`
2. Im cura-stro-UI: Processing-Modus **"Shell-Sim"** wählen
3. **"In PixInsight verarbeiten"** klicken
4. Der Agent kopiert die Light-Frames als "Master" und sendet sie zurück
5. Status wechselt auf `vorbereitet` — du kannst den gesamten Flow prüfen

## WBPP (WeightedBatchPreProcessing)

Das Batch-Skript (`cura_batch.js`) versucht zuerst, das WBPP- oder
FastBatch-Skript von PixInsight aufzurufen. WBPP übernimmt die komplette
Vorverarbeitung:

- Master-Kalibrierung (Bias/Dark/Flat)
- ImageCalibration
- StarAlignment (Registrierung)
- LocalNormalization (optional)
- ImageIntegration (Stacking mit Signal-Gewichtung)
- Drizzle (optional)

Falls das Skript nicht gefunden wird oder fehlschlägt, fällt es auf einen
manuellen Durchlauf (ImageCalibration → StarAlignment → ImageIntegration)
zurück.

### WBPP-Pfad anpassen

Der Standard-Pfad für WBPP auf dem Mac ist:
```
/Applications/PixInsight/src/scripts/BatchProcessing/WeightedBatchPreProcessing.js
```

Falls dein WBPP woanders liegt, setze `WBPP_SCRIPT`:
```bash
WBPP_SCRIPT="/pfad/zu/WeightedBatchPreProcessing.js" python3 agent.py
```

### FastBatchProcessing

Alternativ kann FastBatchProcessing verwendet werden (schneller, weniger
Optionen). Setze den Processing-Modus im UI auf "FastBatch" oder konfiguriere
`FASTBATCH_SCRIPT`:
```bash
FASTBATCH_SCRIPT="/pfad/zu/FastBatchProcessing.js" python3 agent.py
```

## Sicherheit

- Setze `AGENT_TOKEN` auf beiden Seiten (Backend + Agent) auf denselben Wert
- Der Agent lauscht auf `0.0.0.0` — stelle sicher, dass nur das Backend ihn
  erreichen kann (Firewall / VLAN)
- Temp-Dateien werden in `WORK_DIR` gespeichert und können mit
  `DELETE /jobs/{job_id}` aufgeräumt werden

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `pip: command not found` | Virtualenv nicht aktiviert: `source .venv/bin/activate`, oder `python3 -m pip` statt `pip` verwenden |
| `python3: command not found` | Python nicht installiert: `brew install python` oder Xcode Command Line Tools: `xcode-select --install` |
| Health-Check: `pixinsight_found: false` | `PIXINSIGHT_BIN` Pfad stimmt nicht — prüfe mit `ls /Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight` |
| Backend kann Agent nicht erreichen | Mac-Firewall blockiert Port 7777 — Systemeinstellungen → Netzwerk → Firewall, oder IP/Port in `.env` falsch |
| `ModuleNotFoundError: No module named 'fastapi'` | `pip install -r requirements.txt` im aktivierten venv ausführen |
| Agent tut nichts (nur `/health` im Log) | Backend kann RAW-Dateien nicht lesen — Docker-Logs prüfen: `docker logs curastro-backend -f`. Processing-Modus auf "Shell-Sim" stellen zum Testen |
| 409 Conflict bei `/results/{job_id}` | Job ist noch nicht `completed` — Status mit `GET /status/{job_id}` prüfen, dann erneut abholen |
