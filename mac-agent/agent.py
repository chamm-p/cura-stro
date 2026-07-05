"""cura-stro Mac-Agent — PixInsight-Batch-Trigger (File-Broker-Modus).

Läuft als kleiner HTTP-Service auf dem Mac, auf dem PixInsight installiert ist.
Nimmt Verarbeitungs-Jobs vom cura-stro Backend entgegen — **inklusive der RAW-
Dateien als ZIP-Upload**. PixInsight wird headless (CLI) gestartet, die
Ergebnisse werden als ZIP zurückgeladen.

Alle Dateien werden über HTTP transferiert (kein SMB-Mount nötig):

    Backend liest NAS  →  zip (Lights)  →  POST /process (multipart)  →  Agent
    Agent entpackt     →  PixInsight  →  zip  →  GET /results/{job_id}
    Backend entpackt   →  schreibt auf NAS (Prepared/)  →  Status: vorbereitet
    Backend ruft DELETE /jobs/{job_id}  →  Agent räumt Input + Output auf

Calibration-Frames (Flats/Darks/Bias) laufen über den persistenten
**Calib-Cache** (content-adressiert per SHA-256): das Backend fragt per
POST /calib/check, was fehlt, und lädt nur Fehlendes per POST /calib/upload
nach — jede Datei fließt genau EINMAL über die Leitung. Fertige Master
werden zusätzlich in den Cache übernommen; das Backend legt sie parallel
aufs NAS (Calib/Masters/) und referenziert bei Folgejobs nur noch sie.
Legacy-Fallback: kommt kein calib-Feld, liegen die Calib-Frames im ZIP.

Cleanup-Strategie (Platz sparen — der Mac hat wenig):
    - Nach PixInsight-Fertigstellung: Input-Verzeichnis (RAW-Frames) löschen
    - Nach erfolgreichem Ergebnis-Download: Output-Verzeichnis löschen
    - DELETE /jobs/{job_id}: räumt alles restlos auf (Fallback)
    - Calib-Cache: LRU-Verdrängung auf CALIB_CACHE_MAX_GB (Default 20 GB)

Endpoints:
    GET  /health              — Health-Check (inkl. Cache-Statistik)
    POST /calib/check         — Cache-Handshake: welche SHA-256 fehlen?
    POST /calib/upload        — einzelne Calib-Datei in den Cache (Hash-verifiziert)
    POST /process             — Job annehmen (ZIP-Upload) & PixInsight starten
    GET  /status/<job_id>     — Job-Status abfragen
    GET  /results/<job_id>    — Ergebnis-ZIP herunterladen (wenn completed)
    GET  /jobs                — Alle Jobs auflisten
    GET  /logs/<job_id>       — Log-Inhalt eines Jobs
    DELETE /jobs/<job_id>     — Abgeschlossenen Job löschen (inkl. Temp-Dateien)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

# ─── Logging-Setup (Console + Datei) ───
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(message)s"

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))

log = logging.getLogger("cura-stro.agent")
log.setLevel(logging.INFO)
log.handlers = []  # Alle existierenden Handler entfernen (verhindert Doppelung)
log.addHandler(_console_handler)
log.propagate = False  # Verhindert doppelte Ausgabe via uvicorn-Root-Handler

# Uvicorn-Logger an unseren Handler anbinden (kein eigener Handler → keine Doppelung)
for _uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _uv_log = logging.getLogger(_uv_name)
    _uv_log.handlers = []
    _uv_log.addHandler(_console_handler)
    _uv_log.propagate = False
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ─── Konfiguration (Umgebungsvariablen) ───
IS_WINDOWS = sys.platform == "win32"

AGENT_PORT = int(os.environ.get("AGENT_PORT", "7777"))
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
PIXINSIGHT_BIN = os.environ.get(
    "PIXINSIGHT_BIN",
    r"C:\Program Files\PixInsight\bin\PixInsight.exe" if IS_WINDOWS
    else "/Applications/PixInsight/PixInsight.app/Contents/MacOS/PixInsight",
)
BATCH_SCRIPT = os.environ.get(
    "BATCH_SCRIPT",
    str(Path(__file__).parent / "cura_batch.js"),
)
WORK_DIR = Path(os.environ.get("WORK_DIR", str(Path.home() / "cura-stro-jobs")))
LOG_DIR = Path(os.environ.get("LOG_DIR", str(WORK_DIR / "logs")))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

# Persistenter Calib-Cache (content-adressiert: Dateiname = <sha256><ext>).
# Kalibrier-Frames/-Master werden vom Backend nur EINMAL hochgeladen und
# hier wiederverwendet. LRU-Aufräumen hält das Limit ein (Mac hat wenig Platz).
CALIB_CACHE_DIR = Path(os.environ.get("CALIB_CACHE_DIR", str(WORK_DIR / "calib-cache")))
CALIB_CACHE_MAX_GB = float(os.environ.get("CALIB_CACHE_MAX_GB", "20"))

def _required_volume(path: Path) -> Path | None:
    """Liegt der Pfad auf einem externen Volume, liefert dessen Root —
    sonst None (lokaler Pfad, immer verfügbar).

    macOS:  /Volumes/<Name>/…       → /Volumes/<Name>
    Windows: Z:\\… (nicht C:) oder \\\\server\\share\\… → Laufwerks-/Share-Root
    """
    p = Path(path)
    if IS_WINDOWS:
        anchor = p.anchor  # z. B. 'Z:\\' oder '\\\\nas\\Fotos\\'
        if anchor and not anchor.lower().startswith("c:"):
            return Path(anchor)
        return None
    parts = p.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        return Path("/Volumes") / parts[2]
    return None


def _volume_present(vol: Path) -> bool:
    if IS_WINDOWS:
        # Getrenntes Netzlaufwerk/UNC: exists() schlägt fehl.
        return os.path.exists(str(vol))
    # macOS: exists() reicht NICHT — ein nicht gemountetes Volume wäre ein
    # stiller lokaler Ordner unter /Volumes. ismount ist die Wahrheit.
    return os.path.ismount(str(vol))


def _workdir_available() -> tuple[bool, str]:
    """Prüft, ob das Work-Dir wirklich beschreibbar verfügbar ist.

    Kritisch bei WORK_DIR auf dem NAS: ist das Volume/Laufwerk NICHT
    verbunden, würde sonst still auf die lokale Platte geschrieben."""
    for p in (WORK_DIR, CALIB_CACHE_DIR):
        vol = _required_volume(p)
        if vol is not None and not _volume_present(vol):
            return False, f"NAS-Volume/Laufwerk nicht verbunden: {vol} (benötigt für {p})"
    return True, ""


def _ensure_work_dirs() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CALIB_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# Verzeichnisse nur anlegen, wenn das Volume wirklich da ist (sonst legt
# der Startup-Check los und /process antwortet 503 mit klarer Meldung).
if _workdir_available()[0]:
    _ensure_work_dirs()

app = FastAPI(title="cura-stro Mac-Agent", version="0.8.0")


# ─── Job-Tracking ───
@dataclass
class Job:
    id: str
    work_input: str        # lokaler Pfad mit entpackten RAW-Dateien
    work_output: str       # lokaler Pfad für PixInsight-Ergebnisse
    result_zip: str        # Pfad zur Ergebnis-ZIP (wenn completed)
    frame_info: dict[str, Any]
    mode: str = "wbpp"     # wbpp · fastbatch · shell_sim
    status: str = "queued"  # queued · running · completed · failed
    started_at: str | None = None
    completed_at: str | None = None
    pid: int | None = None
    return_code: int | None = None
    log_file: str | None = None
    error: str | None = None
    # Letzte Zeilen des cura_batch-Logs bei Fehlern — der konkrete Grund
    # (z. B. StarAlignment fehlgeschlagen, Platz voll) fürs UI.
    error_detail: str | None = None
    # Aufgelöste Cache-Pfade für cura_batch.js (CURA_CALIB): masterBias/
    # masterDark/masterFlat (Pfad oder "") + biasSubs/darkSubs/flatSubs.
    calib_paths: dict[str, Any] = field(default_factory=dict)
    result_files: list[str] = field(default_factory=list)
    result_zip_size: int = 0
    input_cleaned: bool = False   # Input-Verzeichnis wurde gelöscht
    output_cleaned: bool = False  # Output-Verzeichnis wurde gelöscht

    def to_dict(self) -> dict:
        return asdict(self)


_jobs: dict[str, Job] = {}

# WICHTIG: Das Semaphore darf NICHT beim Modul-Import entstehen. Auf
# Python 3.9 bindet sich asyncio.Semaphore() an den Event-Loop zum
# Zeitpunkt der Erzeugung — beim Import ist das ein anderer als der
# uvicorn-Server-Loop. Folge: der erste Job läuft (kein Warten), aber
# ein WARTENDER zweiter Job crasht mit 'got Future attached to a
# different loop' und bleibt für immer 'queued'. Deshalb lazy im
# laufenden Loop erzeugen.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


# ─── Request-Models ───
class StatusResponse(BaseModel):
    job_id: str
    status: str


class CalibCheckRequest(BaseModel):
    token: str = ""
    files: list[dict[str, Any]] = []  # [{sha256, size, ext}]


# ─── Calib-Cache (content-adressiert) ───
def _cache_path(sha256: str, ext: str) -> Path:
    ext = ext if ext.startswith(".") else ("." + ext if ext else "")
    return CALIB_CACHE_DIR / f"{sha256}{ext}"


def _cache_find(sha256: str) -> Path | None:
    """Findet eine Cache-Datei über den Hash (Extension egal)."""
    if not CALIB_CACHE_DIR.is_dir():
        return None
    matches = list(CALIB_CACHE_DIR.glob(f"{sha256}.*")) + list(CALIB_CACHE_DIR.glob(sha256))
    return matches[0] if matches else None


def _require_workdir() -> None:
    """Wirft 503, wenn das Work-Dir (z. B. NAS-Volume) nicht verfügbar ist —
    statt still auf die lokale Platte zu schreiben."""
    ok, msg = _workdir_available()
    if not ok:
        raise HTTPException(503, f"{msg} — bitte das NAS-Volume auf dem Mac mounten")
    _ensure_work_dirs()


def _cache_size_bytes() -> int:
    if not CALIB_CACHE_DIR.is_dir():
        return 0
    return sum(f.stat().st_size for f in CALIB_CACHE_DIR.iterdir() if f.is_file())


def _calib_cache_cleanup() -> None:
    """LRU-Aufräumen: älteste (zuletzt benutzte) Dateien löschen, bis das
    Limit eingehalten ist. 'Benutzt' = mtime, das wir bei jedem Treffer
    aktualisieren (atime ist auf APFS oft deaktiviert)."""
    if not CALIB_CACHE_DIR.is_dir():
        return
    limit = int(CALIB_CACHE_MAX_GB * 1024 ** 3)
    files = sorted(
        (f for f in CALIB_CACHE_DIR.iterdir() if f.is_file()),
        key=lambda f: f.stat().st_mtime,
    )
    total = sum(f.stat().st_size for f in files)
    evicted = 0
    while total > limit and files:
        victim = files.pop(0)
        try:
            size = victim.stat().st_size
            victim.unlink()
            total -= size
            evicted += 1
        except Exception:
            break
    if evicted:
        log.info("Calib-Cache: %d Datei(en) verdrängt (LRU, Limit %.0f GB, jetzt %.1f GB)",
                 evicted, CALIB_CACHE_MAX_GB, total / 1024 ** 3)


def _check_token(token: str) -> None:
    if AGENT_TOKEN and token != AGENT_TOKEN:
        log.warning("Token-Prüfung fehlgeschlagen")
        raise HTTPException(403, "Ungültiges Token")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _js_path(p) -> str:
    """Pfad für PJSR (cura_batch.js): PixInsight versteht auf allen
    Plattformen Forward-Slashes — Windows-Backslashes normalisieren."""
    return str(p).replace("\\", "/")


def _zip_directory(src_dir: Path, zip_path: Path) -> int:
    """Zippt ein gesamtes Verzeichnis (rekursiv) und liefert die Größe.
    ZIP_STORED: XISF/FITS komprimieren praktisch nicht — Deflate kostet nur CPU."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir)
                zf.write(file_path, arcname)
                file_count += 1
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    log.info("  ZIP erstellt: %s (%d Dateien, %.1f MB)", zip_path.name, file_count, size_mb)
    return zip_path.stat().st_size


def _cleanup_input(job: Job) -> None:
    """Löscht das Input-Verzeichnis (RAW-Frames nicht mehr nötig nach Verarbeitung)."""
    input_path = Path(job.work_input)
    if input_path.exists() and input_path.is_dir():
        try:
            shutil.rmtree(input_path, ignore_errors=True)
            job.input_cleaned = True
            log.info("  Input aufgeräumt: %s", input_path)
        except Exception as e:
            log.warning("  Konnte Input nicht aufräumen: %s — %s", input_path, e)


def _cleanup_output(job: Job) -> None:
    """Löscht das Output-Verzeichnis und die Ergebnis-ZIP (nach erfolgreichem Download)."""
    output_path = Path(job.work_output)
    if output_path.exists() and output_path.is_dir():
        try:
            shutil.rmtree(output_path, ignore_errors=True)
            job.output_cleaned = True
            log.info("  Output aufgeräumt: %s", output_path)
        except Exception as e:
            log.warning("  Konnte Output nicht aufräumen: %s — %s", output_path, e)
    # Ergebnis-ZIP auch löschen
    if job.result_zip:
        zip_path = Path(job.result_zip)
        if zip_path.exists():
            try:
                zip_path.unlink(missing_ok=True)
                log.info("  Ergebnis-ZIP gelöscht: %s", zip_path)
            except Exception as e:
                log.warning("  Konnte Ergebnis-ZIP nicht löschen: %s — %s", zip_path, e)


def _classify_frame(filename: str) -> str:
    """Klassifiziert einen Dateinamen nach Frame-Typ (ASIAir-Konvention)."""
    lower = filename.lower()
    if lower.startswith("darkflat"):
        return "darkflat"
    if lower.startswith("light"):
        return "light"
    if lower.startswith("dark"):
        return "dark"
    if lower.startswith("flat"):
        return "flat"
    if lower.startswith("bias"):
        return "bias"
    return "light"


def _count_frames(input_dir: Path) -> dict[str, int]:
    """Zählt Dateien im Input-Verzeichnis nach Frame-Typ."""
    counts: dict[str, int] = {
        "light": 0, "dark": 0, "flat": 0, "bias": 0, "darkflat": 0, "other": 0,
    }
    for f in input_dir.rglob("*"):
        if f.is_file():
            ftype = _classify_frame(f.name)
            counts[ftype] = counts.get(ftype, 0) + 1
    return counts


async def _run_shell_sim(job: Job) -> None:
    """Shell-Simulation: Kopiert Light-Frames als 'Master' in den Output-Ordner.
    Kein PixInsight nötig — validiert den gesamten HTTP-Flow."""
    async with _get_semaphore():
        job.status = "running"
        job.started_at = _now_iso()
        log.info("=" * 60)
        log.info("Job %s — Shell-Simulation GESTARTET", job.id[:8])
        log.info("  Input:  %s", job.work_input)
        log.info("  Output: %s", job.work_output)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        try:
            with open(log_file, "w") as flog:
                flog.write(f"=== cura-stro Shell-Simulation (Job {job.id}) ===\n")
                flog.write(f"Input:  {job.work_input}\n")
                flog.write(f"Output: {job.work_output}\n")
                flog.write(f"Frame-Info: {json.dumps(job.frame_info, indent=2)}\n\n")

                input_dir = Path(job.work_input)
                output_dir = Path(job.work_output)
                output_dir.mkdir(parents=True, exist_ok=True)

                all_files = sorted(f for f in input_dir.rglob("*") if f.is_file())
                counts = _count_frames(input_dir)
                log.info("  Gefunden: %d Dateien (Lights: %d, Darks: %d, Flats: %d, Bias: %d, DarkFlats: %d)",
                         len(all_files), counts["light"], counts["dark"],
                         counts["flat"], counts["bias"], counts["darkflat"])
                flog.write(f"Gefunden: {len(all_files)} Dateien\n")
                flog.write(f"  Lights: {counts['light']}, Darks: {counts['dark']}, "
                           f"Flats: {counts['flat']}, Bias: {counts['bias']}, "
                           f"DarkFlats: {counts['darkflat']}\n\n")

                lights = []
                calib_files = []
                for f in all_files:
                    ftype = _classify_frame(f.name)
                    flog.write(f"  {f.name} → {ftype}\n")
                    if ftype == "light":
                        lights.append(f)
                    else:
                        calib_files.append((f, ftype))

                log.info("  Verarbeite %d Light-Frames …", len(lights))
                if lights:
                    master_path = output_dir / "master_light_simulated.xisf"
                    shutil.copy2(lights[0], master_path)
                    log.info("  Master (simuliert): %s", master_path.name)
                    flog.write(f"\nMaster (simuliert): {master_path.name}\n")

                    cal_dir = output_dir / "calibrated"
                    cal_dir.mkdir(exist_ok=True)
                    for i, light in enumerate(lights):
                        dst = cal_dir / f"calibrated_{i:04d}{light.suffix}"
                        shutil.copy2(light, dst)
                    log.info("  Kalibrierte Lights: %d Dateien", len(lights))
                    flog.write(f"Kalibrierte Lights: {len(lights)} Dateien\n")

                if calib_files:
                    calib_out = output_dir / "calibration"
                    calib_out.mkdir(exist_ok=True)
                    for f, ftype in calib_files:
                        dst = calib_out / f.name
                        if not dst.exists():
                            shutil.copy2(f, dst)
                    log.info("  Calibration-Files kopiert: %d Dateien", len(calib_files))
                    flog.write(f"Calibration-Files: {len(calib_files)} Dateien\n")

                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )

                log.info("  Ergebnis: %d Dateien", len(job.result_files))
                flog.write(f"\nErgebnis: {len(job.result_files)} Dateien\n")
                flog.write("Shell-Simulation abgeschlossen.\n")

            job.return_code = 0
            job.status = "completed"
            log.info("Job %s — Shell-Simulation ABGESCHLOSSEN", job.id[:8])

            zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
            if out_path.is_dir() and any(out_path.iterdir()):
                log.info("  Packe Ergebnis-ZIP …")
                job.result_zip_size = _zip_directory(out_path, zip_path)
                job.result_zip = str(zip_path)
            else:
                job.status = "failed"
                job.error = "Shell-Simulation lieferte keine Ergebnis-Dateien"
                log.error("Job %s — FEHLER: keine Ergebnis-Dateien", job.id[:8])

            # Input aufräumen (RAW-Frames nicht mehr nötig)
            if job.status == "completed":
                _cleanup_input(job)

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error("Job %s — FEHLER: %s", job.id[:8], e, exc_info=True)
            with open(log_file, "a") as flog:
                flog.write(f"\nFEHLER: {e}\n")
        finally:
            job.completed_at = _now_iso()
            log.info("=" * 60)


def _print_pi_log(log_file: Path, max_lines: int = 200) -> None:
    """Gibt den PixInsight-Log auf der Agent-Konsole aus (für Debugging)."""
    try:
        content = log_file.read_text(errors="replace").strip()
        if not content:
            log.info("  PixInsight-Log ist leer")
            return
        lines = content.split("\n")
        if len(lines) > max_lines:
            log.info("  --- PixInsight Log (letzte %d von %d Zeilen) ---", max_lines, len(lines))
            lines = lines[-max_lines:]
        else:
            log.info("  --- PixInsight Log (%d Zeilen) ---", len(lines))
        for line in lines:
            log.info("  PI | %s", line)
        log.info("  --- Ende PixInsight Log ---")
    except Exception as e:
        log.warning("  Konnte PixInsight-Log nicht lesen: %s", e)


def _cache_built_masters(output_dir: Path) -> None:
    """Übernimmt frisch gebaute master_bias/dark/flat.xisf in den Calib-Cache.

    Das Backend registriert dieselben Dateien (gleiche Bytes → gleicher
    SHA-256) auf dem NAS — beim nächsten Job trifft /calib/check dann sofort,
    ohne dass der Master erneut hochgeladen werden muss."""
    for name in ("master_bias.xisf", "master_dark.xisf", "master_flat.xisf"):
        for f in output_dir.rglob(name):
            try:
                h = hashlib.sha256()
                with open(f, "rb") as src:
                    while chunk := src.read(1024 * 1024):
                        h.update(chunk)
                dest = _cache_path(h.hexdigest(), ".xisf")
                if not dest.exists():
                    shutil.copy2(f, dest)
                    log.info("  Calib-Cache: %s übernommen (%s…)", name, h.hexdigest()[:12])
            except Exception as e:
                log.warning("  Konnte %s nicht in den Cache übernehmen: %s", name, e)


def _batch_log_tail(output_dir: Path, max_lines: int = 25) -> str | None:
    """Fehlergrund fürs UI: cura_batch_error.log komplett, sonst die letzten
    Zeilen von cura_batch.log (dort steht, wie weit das Script kam)."""
    try:
        err_log = output_dir / "cura_batch_error.log"
        if err_log.exists():
            return err_log.read_text(errors="replace").strip()[-2000:]
        batch_log = output_dir / "cura_batch.log"
        if batch_log.exists():
            lines = batch_log.read_text(errors="replace").strip().split("\n")
            return "\n".join(lines[-max_lines:])[-2000:]
    except Exception:  # noqa: BLE001
        pass
    return None


def _print_batch_log(output_dir: Path) -> None:
    """Gibt das von cura_batch.js geschriebene Datei-Log auf der Agent-Konsole
    aus. Das ist die EINZIGE Quelle für Script-Ausgaben/Fehler — PixInsight
    schickt die PJSR-Console auf macOS in die GUI, nicht nach stdout."""
    batch_log = output_dir / "cura_batch.log"
    err_log = output_dir / "cura_batch_error.log"
    if batch_log.exists():
        try:
            content = batch_log.read_text(errors="replace").strip()
            log.info("  --- cura_batch.js Log ---")
            for line in content.split("\n"):
                log.info("  JS | %s", line)
            log.info("  --- Ende cura_batch.js Log ---")
        except Exception as e:
            log.warning("  Konnte cura_batch.js-Log nicht lesen: %s", e)
    else:
        log.warning("  KEIN cura_batch.js-Log gefunden (%s) — Skript wurde "
                    "vermutlich gar nicht ausgeführt (PixInsight-Aufruf/Parse-"
                    "Fehler) oder Output-Verzeichnis stimmt nicht.", batch_log)
    if err_log.exists():
        try:
            log.error("  --- cura_batch.js FEHLER ---")
            for line in err_log.read_text(errors="replace").strip().split("\n"):
                log.error("  JS-ERR | %s", line)
            log.error("  --- Ende cura_batch.js FEHLER ---")
        except Exception:
            pass


def _pixinsight_running() -> bool:
    """Läuft PixInsight gerade (GUI oder hängengebliebener Prozess)?"""
    try:
        if IS_WINDOWS:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PixInsight.exe"],
                capture_output=True, text=True, timeout=5,
            )
            return "PixInsight.exe" in (r.stdout or "")
        r = subprocess.run(
            ["pgrep", "-f", "PixInsight"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [p.strip() for p in r.stdout.strip().split("\n") if p.strip()]
        return any(p != str(os.getpid()) for p in pids)
    except Exception:  # noqa: BLE001
        return False


def _kill_existing_pixinsight() -> None:
    """Killt alle laufenden PixInsight-Prozesse vor einem headless-Batch.
    Verhindert 'Yielded execution to running instance' — das Skript wuerde
    sonst an eine bestehende Instanz delegiert und nie ausgefuehrt."""
    import time
    try:
        if IS_WINDOWS:
            if _pixinsight_running():
                log.info('  Beende laufende PixInsight.exe (taskkill) …')
                subprocess.run(
                    ["taskkill", "/F", "/IM", "PixInsight.exe"],
                    capture_output=True, timeout=10,
                )
                time.sleep(2)
            return
        result = subprocess.run(
            ['pgrep', '-f', 'PixInsight'],
            capture_output=True, text=True, timeout=5,
        )
        pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
        # Eigene PID ausschliessen (falls der Agent-Pfad 'PixInsight' enthaelt)
        my_pid = os.getpid()
        pids = [p for p in pids if p != str(my_pid)]
        if pids:
            log.info('  Killte %d laufende(n) PixInsight-Prozess(e): %s', len(pids), ', '.join(pids))
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid], timeout=5)
                except Exception:
                    pass
            time.sleep(2)
    except FileNotFoundError:
        pass  # pgrep nicht verfuegbar
    except Exception as e:
        log.warning('  Konnte PixInsight-Prozesse nicht killen: %s', e)


async def _run_pixinsight(job: Job) -> None:
    """Führt PixInsight headless mit dem Batch-Skript aus."""
    async with _get_semaphore():
        job.status = "running"
        job.started_at = _now_iso()
        log.info("=" * 60)
        log.info("Job %s — PixInsight (%s) GESTARTET", job.id[:8], job.mode)
        log.info("  Input:  %s", job.work_input)
        log.info("  Output: %s", job.work_output)
        log.info("  Mode:   %s", job.mode)
        log.info("  Calib-Frames sind im ZIP enthalten (keine lokalen Pfade nötig)")

        Path(job.work_output).mkdir(parents=True, exist_ok=True)

        log_file = LOG_DIR / f"{job.id}.log"
        job.log_file = str(log_file)

        batch_script = BATCH_SCRIPT

        # Wrapper-JS generieren: setzt Config als globale JS-Variablen und
        # inkludiert cura_batch.js.  KEIN JSON.parse im PJSR-Skript nötig —
        # PJSR hat kein JSON-Objekt.  Stattdessen werden die Werte direkt
        # als JavaScript-Variablen injiziert.
        wrapper_path = Path(job.work_input).parent / f"{job.id}_wrapper.js"
        batch_source = Path(batch_script).read_text()
        wrapper_js = (
            "var CURA_INPUT_DIR = " + json.dumps(_js_path(job.work_input)) + ";\n"
            + "var CURA_OUTPUT_DIR = " + json.dumps(_js_path(job.work_output)) + ";\n"
            + "var CURA_MODE = " + json.dumps(job.mode) + ";\n"
            + "var CURA_FRAME_INFO = " + json.dumps(job.frame_info) + ";\n"
            + "var CURA_CALIB = " + json.dumps(job.calib_paths or {}) + ";\n"
            + batch_source
        )
        wrapper_path.write_text(wrapper_js)
        log.info("  Wrapper: %s (cura_batch.js inlined, Config als JS-Variablen)", wrapper_path)

        # Laufende PixInsight-Instanzen killen (verhindert Yielding)
        _kill_existing_pixinsight()

        # PixInsight CLI Aufruf: -n erzwingt neue Instanz, --force-exit killt danach
        cmd = [
            PIXINSIGHT_BIN,
            "-n",                       # Neue Instanz erzwingen (kein Yielding)
            f"-r={_js_path(wrapper_path)}",
            "--force-exit",
        ]

        log.info("  PixInsight CLI: %s", " ".join(cmd))
        log.info("  Skript: %s", batch_script)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
            )
            job.pid = proc.pid
            log.info("  PixInsight PID: %d — warte auf Abschluss …", proc.pid)
            rc = await proc.wait()
            job.return_code = rc

            # PixInsight-Log auf Agent-Konsole ausgeben (für Debugging)
            _print_pi_log(log_file)
            # Script-eigenes Log (cura_batch.js schreibt es, weil die PJSR-
            # Console auf macOS in die GUI geht und NICHT nach stdout).
            _print_batch_log(Path(job.work_output))

            if rc == 0:
                out_path = Path(job.work_output)
                if out_path.is_dir():
                    job.result_files = sorted(
                        str(f.relative_to(out_path))
                        for f in out_path.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"
                        }
                    )
                log.info("  Ergebnis: %d Dateien", len(job.result_files))

                if job.result_files:
                    job.status = "completed"
                    log.info("Job %s — PixInsight ABGESCHLOSSEN (exit 0, %d Dateien)",
                             job.id[:8], len(job.result_files))
                    # Frisch gebaute Bias/Dark/Flat-Master in den Cache übernehmen
                    _cache_built_masters(out_path)
                    zip_path = Path(job.work_output).parent / f"{job.id}_results.zip"
                    log.info("  Packe Ergebnis-ZIP …")
                    job.result_zip_size = _zip_directory(out_path, zip_path)
                    job.result_zip = str(zip_path)

                    # Input aufräumen (RAW-Frames nicht mehr nötig)
                    _cleanup_input(job)
                else:
                    job.status = "failed"
                    # Gemeint sind die MASTER-Dateien des Stackings — das
                    # manuell entwickelte Einzelbild entsteht später und wird
                    # hier NICHT erwartet.
                    job.error = ("PixInsight hat keine Master-Dateien erzeugt "
                                 "(Stacking unvollständig) — siehe Details")
                    job.error_detail = _batch_log_tail(Path(job.work_output))
                    log.error("Job %s — FEHLER: keine Master im Output (exit 0). "
                              "Ursache steht im cura_batch.js-Log oben.", job.id[:8])
            else:
                job.status = "failed"
                job.error = f"PixInsight exit code {rc} — siehe Details"
                job.error_detail = _batch_log_tail(Path(job.work_output))
                log.error("Job %s — FEHLER: PixInsight exit code %d", job.id[:8], rc)
                log.error("  Log: %s", log_file)

        except FileNotFoundError:
            job.status = "failed"
            job.error = f"PixInsight nicht gefunden unter: {PIXINSIGHT_BIN}"
            log.error("Job %s — FEHLER: PixInsight nicht gefunden: %s", job.id[:8], PIXINSIGHT_BIN)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error("Job %s — FEHLER: %s", job.id[:8], e, exc_info=True)
        finally:
            job.completed_at = _now_iso()
            wrapper_path.unlink(missing_ok=True)
            _calib_cache_cleanup()
            log.info("=" * 60)


# ─── Endpoints ───
@app.on_event("startup")
async def _startup():
    log.info("=" * 60)
    log.info("cura-stro Mac-Agent v0.8.1 — startet")
    log.info("  Port:         %d", AGENT_PORT)
    wd_ok, wd_msg = _workdir_available()
    if wd_ok:
        _ensure_work_dirs()
        log.info("  Work-Dir:     %s", WORK_DIR)
    else:
        log.error("  Work-Dir:     NICHT VERFÜGBAR — %s", wd_msg)
        log.error("                Jobs werden mit 503 abgelehnt, bis das Volume gemountet ist.")
    log.info("  Log-Dir:      %s", LOG_DIR)
    log.info("  Calib-Cache:  %s (%.1f MB belegt, Limit %.0f GB)",
             CALIB_CACHE_DIR, _cache_size_bytes() / (1024 * 1024), CALIB_CACHE_MAX_GB)
    log.info("  PixInsight:   %s (%s)",
             PIXINSIGHT_BIN,
             "✓ gefunden" if Path(PIXINSIGHT_BIN).exists() else "✗ NICHT gefunden")
    log.info("  Batch-Script: %s (%s)",
             BATCH_SCRIPT,
             "✓ gefunden" if Path(BATCH_SCRIPT).exists() else "✗ NICHT gefunden")
    log.info("  Max parallel: %d", MAX_CONCURRENT)
    log.info("  Token:        %s", "aktiv" if AGENT_TOKEN else "deaktiviert (offen)")
    log.info("=" * 60)


@app.get("/health")
async def health():
    pixinsight_ok = Path(PIXINSIGHT_BIN).exists()
    script_ok = Path(BATCH_SCRIPT).exists()
    # Pruefen, ob PixInsight bereits laeuft (GUI oder hängengebliebener Prozess)
    pixinsight_running = _pixinsight_running()
    wd_ok, wd_msg = _workdir_available()
    return {
        "status": "ok" if pixinsight_ok and script_ok and wd_ok else "degraded",
        "work_dir_available": wd_ok,
        "work_dir_error": wd_msg or None,
        "pixinsight_found": pixinsight_ok,
        "pixinsight_running": pixinsight_running,
        "pixinsight_path": PIXINSIGHT_BIN,
        "batch_script_found": script_ok,
        "batch_script_path": BATCH_SCRIPT,
        "work_dir": str(WORK_DIR),
        "active_jobs": sum(1 for j in _jobs.values() if j.status == "running"),
        "total_jobs": len(_jobs),
        "shell_sim_available": True,
        "calib_cache_files": (
            sum(1 for f in CALIB_CACHE_DIR.iterdir() if f.is_file())
            if CALIB_CACHE_DIR.is_dir() else 0
        ),
        "calib_cache_mb": round(_cache_size_bytes() / (1024 * 1024), 1),
        "calib_cache_max_gb": CALIB_CACHE_MAX_GB,
    }


@app.post("/calib/check")
async def calib_check(req: CalibCheckRequest):
    """Cache-Handshake: das Backend schickt das Manifest (sha256/size/ext),
    der Agent meldet, welche Dateien ihm fehlen. Treffer werden 'berührt'
    (mtime), damit das LRU-Aufräumen sie nicht verdrängt."""
    _check_token(req.token)
    _require_workdir()
    missing: list[str] = []
    present = 0
    for item in req.files:
        sha = str(item.get("sha256", ""))
        if not sha:
            continue
        p = _cache_find(sha)
        if p is None:
            missing.append(sha)
            continue
        size = item.get("size") or 0
        if size and p.stat().st_size != size:
            # Beschädigt/unvollständig → neu anfordern
            p.unlink(missing_ok=True)
            missing.append(sha)
            continue
        p.touch()  # LRU-Treffer
        present += 1
    log.info("POST /calib/check — %d im Cache, %d fehlen", present, len(missing))
    return {"present": present, "missing": missing}


@app.post("/calib/upload")
async def calib_upload(
    file: UploadFile = File(...),
    sha256: str = Form(...),
    ext: str = Form(default=""),
    token: str = Form(default=""),
):
    """Nimmt eine einzelne Calib-Datei entgegen und legt sie content-
    adressiert im Cache ab. Der Hash wird beim Empfang verifiziert —
    eine korrupte Übertragung landet nie im Cache."""
    _check_token(token)
    _require_workdir()
    tmp_path = CALIB_CACHE_DIR / f".upload_{uuid.uuid4().hex}"
    h = hashlib.sha256()
    total = 0
    try:
        with open(tmp_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                h.update(chunk)
                total += len(chunk)
        actual = h.hexdigest()
        if actual != sha256:
            tmp_path.unlink(missing_ok=True)
            log.error("POST /calib/upload — Hash-Mismatch (erwartet %s…, ist %s…)",
                      sha256[:12], actual[:12])
            raise HTTPException(400, "SHA-256 stimmt nicht — Übertragung korrupt")
        final = _cache_path(sha256, ext or Path(file.filename or "").suffix)
        tmp_path.replace(final)
        log.info("POST /calib/upload — %s… gespeichert (%.1f MB)", sha256[:12], total / (1024 * 1024))
        return {"stored": sha256, "bytes": total}
    except HTTPException:
        raise
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload fehlgeschlagen: {e}")


def _resolve_calib(calib_json: str) -> dict[str, Any]:
    """Löst das calib-Manifest des Backends (SHA-256-Referenzen) in lokale
    Cache-Pfade für cura_batch.js auf. Fehlt eine Datei im Cache → 409,
    das Backend muss sie erst per /calib/upload nachliefern."""
    if not calib_json:
        return {}
    try:
        calib = json.loads(calib_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "calib ist kein gültiges JSON")

    def resolve(item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        sha = str(item.get("sha256", ""))
        p = _cache_find(sha)
        if p is None:
            raise HTTPException(409, f"Calib-Datei fehlt im Cache: {sha[:16]}… — erst /calib/upload")
        p.touch()
        return _js_path(p)

    resolved = {
        "masterBias": resolve(calib.get("master_bias")),
        "masterDark": resolve(calib.get("master_dark")),
        "masterFlat": resolve(calib.get("master_flat")),
        "biasSubs": [resolve(i) for i in calib.get("bias_subs", [])],
        "darkSubs": [resolve(i) for i in calib.get("dark_subs", [])],
        "flatSubs": [resolve(i) for i in calib.get("flat_subs", [])],
    }
    return resolved


@app.post("/process")
async def process(
    file: UploadFile = File(..., description="ZIP mit RAW-Frames (Lights; Calib via Cache)"),
    frame_info: str = Form(default="{}", description="JSON mit Frame-Metadaten"),
    mode: str = Form(default="wbpp", description="Processing-Modus: wbpp|fastbatch|shell_sim"),
    calib: str = Form(default="", description="JSON: Calib-Referenzen (SHA-256 im Cache)"),
    token: str = Form(default=""),
):
    """Nimmt ein ZIP mit RAW-Frames entgegen, entpackt es lokal und startet
    PixInsight headless (oder die Shell-Simulation). Die Ergebnisse können
    später als ZIP heruntergeladen werden (GET /results/{job_id})."""
    _check_token(token)
    _require_workdir()

    log.info("-" * 60)
    log.info("POST /process — neuer Job empfangen")
    log.info("  Mode:          %s", mode)
    log.info("  Upload:        %s (%s bytes)",
             file.filename, file.size if file.size else "?")

    try:
        info = json.loads(frame_info) if frame_info else {}
    except json.JSONDecodeError:
        info = {}
    if info:
        log.info("  Frame-Info:    %s", json.dumps(info, indent=2))

    if mode not in ("wbpp", "fastbatch", "shell_sim"):
        log.warning("  Unbekannter Mode '%s' → fallback auf wbpp", mode)
        mode = "wbpp"

    # Calib-Referenzen auflösen (409 wenn etwas im Cache fehlt)
    calib_paths = _resolve_calib(calib)
    if calib_paths:
        log.info(
            "  Calib (Cache):  Master B/D/F: %s/%s/%s — Subs B/D/F: %d/%d/%d",
            "✓" if calib_paths["masterBias"] else "—",
            "✓" if calib_paths["masterDark"] else "—",
            "✓" if calib_paths["masterFlat"] else "—",
            len(calib_paths["biasSubs"]), len(calib_paths["darkSubs"]), len(calib_paths["flatSubs"]),
        )

    job_id = str(uuid.uuid4())
    # Lesbarer Ordnername: <Objekt>_<Gerät>_<jobid8> statt nackter UUID —
    # so bleibt auf dem Mac zuordenbar, was wozu gehört.
    label = "_".join(
        x for x in ((info.get("object_name") or "").strip(), (info.get("device_name") or "").strip()) if x
    )
    label = "".join(c if (c.isalnum() or c in "._-") else "-" for c in label)[:60].strip("._-")
    job_dir = WORK_DIR / (f"{label}_{job_id[:8]}" if label else job_id)
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("  Job-ID:        %s", job_id)
    log.info("  Job-Dir:       %s", job_dir)

    # ZIP empfangen und speichern
    log.info("  Empfangen ZIP-Upload …")
    zip_path = job_dir / "upload.zip"
    total_bytes = 0
    with open(zip_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
            total_bytes += len(chunk)
    upload_mb = total_bytes / (1024 * 1024)
    log.info("  Upload komplett: %.1f MB", upload_mb)

    # ZIP entpacken
    log.info("  Entpacke ZIP …")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(input_dir)
    except zipfile.BadZipFile:
        log.error("  FEHLER: keine gültige ZIP-Datei")
        raise HTTPException(400, "Hochgeladene Datei ist kein gültiges ZIP")
    except Exception as e:
        log.error("  FEHLER beim Entpacken: %s", e)
        raise HTTPException(400, f"Fehler beim Entpacken: {e}")

    # Upload-ZIP löschen (Platz sparen — entpackte Dateien reichen)
    zip_path.unlink(missing_ok=True)
    log.info("  Upload-ZIP gelöscht (Platz gespart)")

    raw_files = [f for f in input_dir.rglob("*") if f.is_file()]
    if not raw_files:
        log.error("  FEHLER: ZIP enthält keine Dateien")
        raise HTTPException(400, "ZIP enthält keine Dateien")

    counts = _count_frames(input_dir)
    log.info("  Entpackt: %d Dateien (Lights: %d, Darks: %d, Flats: %d, Bias: %d, DarkFlats: %d)",
             len(raw_files), counts["light"], counts["dark"],
             counts["flat"], counts["bias"], counts["darkflat"])

    job = Job(
        id=job_id,
        work_input=str(input_dir),
        work_output=str(output_dir),
        result_zip="",
        frame_info=info,
        mode=mode,
        calib_paths=calib_paths,
    )
    _jobs[job_id] = job

    if mode == "shell_sim":
        log.info("  Starte Shell-Simulation …")
        asyncio.create_task(_run_shell_sim(job))
    else:
        log.info("  Starte PixInsight (%s) …", mode)
        asyncio.create_task(_run_pixinsight(job))

    log.info("  Job %s queued — Rückmeldung an Backend", job_id[:8])
    log.info("-" * 60)

    return {
        "job_id": job_id,
        "status": "queued",
        "input_files": len(raw_files),
        "mode": mode,
    }


@app.get("/status/{job_id}")
async def job_status(job_id: str, token: str = ""):
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        log.warning("GET /status/%s — Job nicht gefunden", job_id[:8])
        raise HTTPException(404, "Job nicht gefunden")
    return job.to_dict()


@app.get("/results/{job_id}")
async def job_results(job_id: str, token: str = ""):
    """Lädt die Ergebnis-ZIP eines abgeschlossenen Jobs herunter.
    Nach erfolgreichem Download wird das Output-Verzeichnis aufgeräumt."""
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        log.warning("GET /results/%s — Job nicht gefunden", job_id[:8])
        raise HTTPException(404, "Job nicht gefunden")
    if job.status != "completed":
        log.info("GET /results/%s — Job noch '%s' (409)", job_id[:8], job.status)
        raise HTTPException(409, f"Job ist noch '{job.status}' — keine Ergebnisse verfügbar")
    if not job.result_zip or not Path(job.result_zip).exists():
        log.warning("GET /results/%s — ZIP nicht gefunden", job_id[:8])
        raise HTTPException(404, "Ergebnis-ZIP nicht gefunden")
    size_mb = job.result_zip_size / (1024 * 1024)
    log.info("GET /results/%s — sende ZIP (%.1f MB, %d Dateien)",
             job_id[:8], size_mb, len(job.result_files))

    # Ergebnis-ZIP in Memory lesen (vor dem Aufräumen)
    zip_data = Path(job.result_zip).read_bytes()

    # Output aufräumen (Ergebnisse wurden heruntergeladen → nicht mehr nötig)
    _cleanup_output(job)

    # Ergebnis-ZIP aus Memory senden (Datei auf Disk bereits gelöscht)
    return Response(
        content=zip_data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_results.zip"'},
    )


@app.get("/jobs")
async def list_jobs(token: str = ""):
    _check_token(token)
    return {"jobs": [j.to_dict() for j in _jobs.values()]}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str, token: str = ""):
    """Entfernt einen Job und seine Temp-Dateien (restloses Aufräumen)."""
    _check_token(token)
    job = _jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    job_dir = Path(job.work_input).parent
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    log.info("DELETE /jobs/%s — Job gelöscht (Temp-Dateien entfernt)", job_id[:8])
    return {"deleted": job_id}


@app.get("/logs/{job_id}")
async def job_logs(job_id: str, token: str = ""):
    """Liefert den Log-Inhalt eines Jobs."""
    _check_token(token)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nicht gefunden")
    if not job.log_file or not Path(job.log_file).exists():
        return {"log": "(kein Log vorhanden)"}
    return {"log": Path(job.log_file).read_text()}


if __name__ == "__main__":
    import uvicorn
    # log_config=None: uvicorn rekonfiguriert Logging NICHT — unsere Handler
    # bleiben erhalten, keine Doppelung.
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT, log_config=None)
