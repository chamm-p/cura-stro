# ──────────────────────────────────────────────────────────────────────────
# cura-stro Agent — Start-Script für WINDOWS (PowerShell)
#
# Pendant zu start.sh: venv prüfen/erstellen, Abhängigkeiten installieren,
# .env laden, Agent starten.
#
# Usage (PowerShell):
#   .\start.ps1              — Agent starten
#   .\start.ps1 -Check       — Health-Check (Agent muss laufen)
#   .\start.ps1 -Stop        — Agent stoppen
#
# Falls Scripts blockiert sind (ExecutionPolicy), einmalig:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# Konfiguration in .env neben agent.py, z. B.:
#   AGENT_TOKEN=…                       (gleich wie im Backend)
#   PIXINSIGHT_BIN=C:\Program Files\PixInsight\bin\PixInsight.exe
#   WORK_DIR=Z:\Astrofotos\cura-stro-jobs      (Netzlaufwerk möglich —
#                                               der Agent prüft die Verbindung)
#   CALIB_CACHE_MAX_GB=20
#
# Autostart: Aufgabenplanung → "Bei Anmeldung" →
#   powershell -WindowStyle Hidden -File <Pfad>\start.ps1
# ──────────────────────────────────────────────────────────────────────────
param(
    [switch]$Check,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPy  = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$VenvPip = Join-Path $ScriptDir ".venv\Scripts\pip.exe"
$Port    = if ($env:AGENT_PORT) { $env:AGENT_PORT } else { "7777" }

function Info($msg)  { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[!]  $msg" -ForegroundColor Yellow }

# ─── Health-Check ───
if ($Check) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 5
        $resp | ConvertTo-Json -Depth 4
    } catch {
        Warn "Agent nicht erreichbar auf Port $Port"
        exit 1
    }
    exit 0
}

# ─── Stoppen ───
if ($Stop) {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*agent.py*" }
    if ($procs) {
        $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "  Beendet: PID $($_.ProcessId)" }
        Info "Agent gestoppt"
    } else {
        Warn "Agent läuft nicht"
    }
    exit 0
}

# ─── venv + Abhängigkeiten ───
if (-not (Test-Path $VenvPy)) {
    Write-Host "Erstelle Virtualenv ..."
    python -m venv (Join-Path $ScriptDir ".venv")
    Info "Virtualenv erstellt"
}
& $VenvPy -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installiere Abhängigkeiten ..."
    & $VenvPip install -q --upgrade pip
    & $VenvPip install -q -r (Join-Path $ScriptDir "requirements.txt")
    Info "Abhängigkeiten installiert"
}

# ─── .env laden ───
$EnvFile = Join-Path $ScriptDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#=\s][^=]*)=(.*)$') {
            $name = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    Info ".env geladen"
}
if (-not $env:AGENT_TOKEN) {
    Warn "Kein AGENT_TOKEN gesetzt — Agent läuft offen (nur für Tests)"
}

# ─── Netzlaufwerk-Hinweis ───
$wd = if ($env:WORK_DIR) { $env:WORK_DIR } else { Join-Path $env:USERPROFILE "cura-stro-jobs" }
if ($wd -match '^[D-Zd-z]:' -and -not (Test-Path (Split-Path -Qualifier $wd))) {
    Warn "WORK_DIR-Laufwerk nicht verbunden: $wd — der Agent lehnt Jobs mit 503 ab, bis es da ist."
    Warn "Netzlaufwerk verbinden (net use) oder UNC-Pfad in WORK_DIR verwenden."
}

# ─── Start ───
Write-Host ""
Write-Host "cura-stro Agent (Windows)" -ForegroundColor Cyan
Write-Host "  Python:   $VenvPy"
Write-Host "  Port:     $Port"
Write-Host "  Work-Dir: $wd"
Write-Host ""
& $VenvPy (Join-Path $ScriptDir "agent.py")
