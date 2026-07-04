#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────
# cura-stro Mac-Agent — Start-Script
#
# Regelt alles: venv prüfen/erstellen, Abhängigkeiten installieren,
# Token laden, Agent starten.
#
# Usage:
#   ./start.sh              — Normaler Start
#   ./start.sh --sim        — Shell-Sim-Modus erzwingen (PixInsight nicht nötig)
#   ./start.sh --check      — Nur Health-Check, Agent nicht starten
#   ./start.sh --stop       — Läuft der Agent? Stoppen (kill)
#   ./start.sh --logs       — Log-Datei tailen
#   ./start.sh --install    — launchd-Daemon installieren (Auto-Start beim Booten)
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─── Pfad-Ermittlung ───
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"
AGENT="$SCRIPT_DIR/agent.py"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
TOKEN_FILE="$SCRIPT_DIR/.agent_token"
ENV_FILE="$SCRIPT_DIR/.env"
LOG_FILE="${CURA_STRO_AGENT_LOG:-/tmp/cura-stro-agent.log}"
PID_FILE="/tmp/cura-stro-agent.pid"
PORT="${AGENT_PORT:-7777}"

# ─── Farben ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
err()   { echo -e "${RED}✗${NC} $1"; }
header(){ echo -e "\n${CYAN}${BOLD}═══ $1 ═══${NC}\n"; }

# ─── venv prüfen / erstellen ───
ensure_venv() {
    if [ -f "$VENV_PY" ]; then
        info "Virtualenv gefunden: $VENV_DIR"
    else
        header "Virtualenv erstellen"
        python3 -m venv "$VENV_DIR"
        info "Virtualenv erstellt: $VENV_DIR"
    fi
}

# ─── Abhängigkeiten prüfen / installieren ───
ensure_deps() {
    header "Abhängigkeiten prüfen"
    if "$VENV_PY" -c "import fastapi" 2>/dev/null; then
        info "Abhängigkeiten bereits installiert"
    else
        warn "Abhängigkeiten fehlen — installiere …"
        "$VENV_PIP" install --upgrade pip -q
        "$VENV_PIP" install -r "$REQUIREMENTS" -q
        info "Abhängigkeiten installiert"
    fi
}

# ─── Token laden ───
load_token() {
    if [ -f "$ENV_FILE" ]; then
        info ".env gefunden — lade Umgebungsvariablen"
        set -a
        source "$ENV_FILE"
        set +a
    fi
    if [ -z "${AGENT_TOKEN:-}" ] && [ -f "$TOKEN_FILE" ]; then
        export AGENT_TOKEN="$(cat "$TOKEN_FILE" | tr -d '[:space:]')"
        info "Token aus .agent_token geladen"
    fi
    if [ -n "${AGENT_TOKEN:-}" ]; then
        info "Token: aktiv"
    else
        warn "Kein Token gesetzt — Agent läuft offen (nur für Tests empfohlen)"
        echo "  Token erzeugen:  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
        echo "  Token speichern: echo 'dein-token' > .agent_token"
    fi
}

# ─── Prüfen ob Agent bereits läuft ───
is_running() {
    # Alle Python-Prozesse suchen, die agent.py ausführen
    if pgrep -f "$AGENT" >/dev/null 2>&1; then
        return 0
    fi
    # Fallback: PID-Datei prüfen
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null || echo '')"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

get_pid() {
    # Primär: pgrep nach agent.py-Pfad
    local pid
    pid=$(pgrep -f "$AGENT" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        echo "$pid"
        return
    fi
    # Fallback: PID-Datei
    if [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE" 2>/dev/null || echo '')"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return
        fi
    fi
    echo ""
}

# ─── Health-Check ───
do_health() {
    header "Health-Check"
    local resp
    resp=$(curl -s --connect-timeout 3 "http://localhost:$PORT/health" 2>/dev/null || echo '')
    if [ -z "$resp" ]; then
        err "Agent nicht erreichbar auf Port $PORT"
        return 1
    fi
    echo "$resp" | "$VENV_PY" -m json.tool 2>/dev/null || echo "$resp"
}

# ─── Agent stoppen ───
do_stop() {
    header "Agent stoppen"
    local stopped_any=false

    # Alle Prozesse finden, die agent.py ausführen
    local pids
    pids=$(pgrep -f "$AGENT" 2>/dev/null || echo '')
    if [ -n "$pids" ]; then
        echo "$pids" | while read -r pid; do
            kill "$pid" 2>/dev/null || true
            echo "  SIGTERM → PID $pid"
        done
        sleep 2
        # Prüfen ob noch welche laufen → SIGKILL
        pids=$(pgrep -f "$AGENT" 2>/dev/null || echo '')
        if [ -n "$pids" ]; then
            warn "SIGTERM ignoriert — sende SIGKILL"
            echo "$pids" | while read -r pid; do
                kill -9 "$pid" 2>/dev/null || true
                echo "  SIGKILL → PID $pid"
            done
        fi
        stopped_any=true
    fi

    # Auch PID-Datei-basierten Prozess killen (falls pgrep ihn nicht fand)
    if [ -f "$PID_FILE" ]; then
        local fpid
        fpid="$(cat "$PID_FILE" 2>/dev/null || echo '')"
        if [ -n "$fpid" ] && kill -0 "$fpid" 2>/dev/null; then
            kill "$fpid" 2>/dev/null || true
            sleep 1
            kill -9 "$fpid" 2>/dev/null || true
            echo "  PID $fpid (aus PID-Datei) beendet"
            stopped_any=true
        fi
        rm -f "$PID_FILE"
    fi

    if [ "$stopped_any" = true ]; then
        info "Agent gestoppt"
    else
        warn "Agent läuft nicht"
    fi
}

# ─── Logs tailen ───
do_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo -e "${CYAN}tail -f $LOG_FILE${NC} (Strg+C zum Beenden)\n"
        tail -f "$LOG_FILE"
    else
        warn "Keine Log-Datei gefunden: $LOG_FILE"
        echo "  Der Agent loggt auf stdout/stderr. Starte mit: ./start.sh"
    fi
}

# ─── launchd-Daemon installieren ───
do_install() {
    header "launchd-Daemon installieren"
    local plist_src="$SCRIPT_DIR/com.cura-stro.agent.plist"
    local plist_dst="$HOME/Library/LaunchAgents/com.cura-stro.agent.plist"

    if [ ! -f "$plist_src" ]; then
        err "plist-Vorlage nicht gefunden: $plist_src"
        exit 1
    fi

    mkdir -p "$HOME/Library/LaunchAgents"
    sed "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" "$plist_src" > "$plist_dst"
    if [ -n "${AGENT_TOKEN:-}" ]; then
        sed -i '' "s|__AGENT_TOKEN__|$AGENT_TOKEN|g" "$plist_dst"
    else
        sed -i '' 's|<string>__AGENT_TOKEN__</string>||g' "$plist_dst"
    fi

    launchctl unload "$plist_dst" 2>/dev/null || true
    launchctl load "$plist_dst"
    info "Daemon installiert und geladen: $plist_dst"
    echo "  Startet automatisch beim Booten."
    echo "  Logs: /tmp/cura-stro-agent.log und /tmp/cura-stro-agent.err"
    echo "  Stop: launchctl unload $plist_dst"
}

# ─── Haupt-Start ───
do_start() {
    header "cura-stro Mac-Agent"

    # Prüfen ob bereits läuft
    if is_running; then
        local pid
        pid=$(get_pid)
        warn "Agent läuft bereits (PID $pid) — Port $PORT"
        echo "  Stoppen:    ./start.sh --stop"
        echo "  Neustart:   ./start.sh --restart"
        echo "  Health:     ./start.sh --check"
        return 0
    fi

    ensure_venv
    ensure_deps
    load_token

    local sim_note=""
    if [ "${1:-}" = "--sim" ]; then
        sim_note="  Modus:        Shell-Sim (PixInsight nicht nötig)"
    fi

    header "Agent starten"
    echo "  Python:       $VENV_PY"
    echo "  Agent:         $AGENT"
    echo "  Port:          $PORT"
    echo "  Work-Dir:      ${WORK_DIR:-~/cura-stro-jobs}"
    echo "  Log:           $LOG_FILE"
    [ -n "$sim_note" ] && echo -e "$sim_note"
    echo ""

    # Starten mit Process-Substitution (keine Pipeline!).
    # Dadurch ist $! die PID des Python-Prozesses, nicht von tee.
    # tee läuft in einer Subshell und beendet sich selbst, wenn Python
    # die Pipe schließt (beim Exit).
    "$VENV_PY" "$AGENT" > >(tee "$LOG_FILE") 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    info "Agent gestartet (PID $pid)"

    # Kurz warten und Health-Check
    sleep 2
    if do_health 2>/dev/null; then
        echo ""
        info "Agent ist bereit! Health-Check OK."
    else
        warn "Agent startet noch — Health-Check in ein paar Sekunden wiederholen:"
        echo "  ./start.sh --check"
    fi
}

# ─── Neustart ───
do_restart() {
    do_stop
    sleep 1
    do_start "$@"
}

# ─── Hilfe ───
show_help() {
    cat << 'HELP'
cura-stro Mac-Agent — Start-Script

Usage:
  ./start.sh              Agent starten (venv + deps + token automatisch)
  ./start.sh --sim        Wie oben, aber Shell-Sim-Modus-Hinweis
  ./start.sh --stop       Agent stoppen (alle Instanzen)
  ./start.sh --restart    Agent neu starten
  ./start.sh --check      Health-Check (Agent muss laufen)
  ./start.sh --logs       Log-Datei tailen (Strg+C zum Beenden)
  ./start.sh --install    launchd-Daemon installieren (Auto-Start beim Booten)
  ./start.sh --help       Diese Hilfe

Konfiguration:
  .env                    Umgebungsvariablen (AGENT_TOKEN, AGENT_PORT, …)
  .agent_token            Alternativ: Token als einzige Zeile in dieser Datei
  requirements.txt        Python-Abhängigkeiten (werden automatisch installiert)

Umgebungsvariablen:
  AGENT_PORT              Port (Default: 7777)
  AGENT_TOKEN             Shared-Secret mit Backend
  PIXINSIGHT_BIN          Pfad zur PixInsight-Binary
  WORK_DIR                Temp-Verzeichnis (Default: ~/cura-stro-jobs)
  CURA_STRO_AGENT_LOG     Log-Datei-Pfad (Default: /tmp/cura-stro-agent.log)

HELP
}

# ─── Main ───
case "${1:-}" in
    --stop)     do_stop ;;
    --restart) shift; do_restart "$@" ;;
    --check)   do_health ;;
    --logs)    do_logs ;;
    --install) load_token; do_install ;;
    --sim)     do_start "--sim" ;;
    --help|-h) show_help ;;
    "")        do_start ;;
    *)         echo "Unbekannter Parameter: $1"; show_help; exit 1 ;;
esac
