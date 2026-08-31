#!/usr/bin/env bash
# start_platform.sh — One-command startup for the NSE-BSE Quant Platform
#
# Usage:
#   ./start_platform.sh              # Start web + MCP (skip data refresh)
#   ./start_platform.sh --update     # Ingest today's data, then start
#   ./start_platform.sh --foreground # Run web in foreground (Ctrl+C to stop)
#   ./start_platform.sh --stop       # Stop all platform processes
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

DO_UPDATE=false
FOREGROUND=false
DO_STOP=false

for arg in "$@"; do
    case "$arg" in
        --update)      DO_UPDATE=true ;;
        --foreground)  FOREGROUND=true ;;
        --stop|-s)     DO_STOP=true ;;
        --help|-h)
            echo "Usage: $0 [--update] [--foreground] [--stop]"
            echo
            echo "  (no args)       Start web dashboard + MCP server"
            echo "  --update        Run make update first (ingest + signals)"
            echo "  --foreground    Run web in foreground (Ctrl+C to stop)"
            echo "  --stop          Stop all platform processes"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown flag: $arg${NC}"
            exit 1
            ;;
    esac
done

if [ "$DO_STOP" = true ]; then
    exec "$ROOT/stop_platform.sh"
fi

# port_open <port> — works even for sockets owned by another user (unlike fuser)
port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- 3>&-
}

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   NSE-BSE Quant Research Platform — Start   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo

# ── Step 1: Fresh data (optional) ──────────────────────────────────────
if [ "$DO_UPDATE" = true ]; then
    echo -e "${YELLOW}▶ Step 1: Running make update...${NC}"
    make update
    echo -e "${GREEN}  ✓ Data up to date${NC}"
    echo
else
    echo -e "${YELLOW}▶ Step 1: Skipping data update (use --update to include)${NC}"
    echo
fi

# ── Step 2: Start MCP server ───────────────────────────────────────────
echo -e "${YELLOW}▶ Step 2: MCP server (nse-bse-mcp)...${NC}"
if pgrep -f "nse-bse-mcp" >/dev/null 2>&1; then
    echo -e "  Already running ✓"
else
    cd /tmp && npx -y nse-bse-mcp > /tmp/nse-bse-mcp.log 2>&1 &
    MCP_PID=$!
    sleep 3
    if kill -0 "$MCP_PID" 2>/dev/null; then
        echo -e "  ${GREEN}✓ Started (PID $MCP_PID)${NC}"
    else
        echo -e "  ${RED}✗ Failed to start — check /tmp/nse-bse-mcp.log${NC}"
    fi
    cd "$ROOT"
fi
echo

# ── Step 3: Announcements backfill ──────────────────────────────────────
echo -e "${YELLOW}▶ Step 3: Announcements backfill...${NC}"
if pgrep -f "announcements_backfill" >/dev/null 2>&1; then
    echo -e "  Already running ✓"
else
    MANIFEST="data/normalized/_ann_manifest.json"
    if [ -f "$MANIFEST" ] && python3 -c "import json; m=json.load(open('$MANIFEST')); print(len(m))" 2>/dev/null | grep -qE "^[0-9]+$"; then
        DONE=$(python3 -c "import json; print(len(json.load(open('$MANIFEST'))))")
        echo -e "  Resuming from manifest ($DONE symbols done)"
    fi
    nohup .venv/bin/python scripts/announcements_backfill.py --from 2024-01-01 --to 2026-08-26 > /tmp/backfill.log 2>&1 &
    BACKFILL_PID=$!
    sleep 2
    if kill -0 "$BACKFILL_PID" 2>/dev/null; then
        echo -e "  ${GREEN}✓ Started in background (PID $BACKFILL_PID)${NC}"
    else
        echo -e "  ${YELLOW}⚠ Could not start (may need MCP) — check /tmp/backfill.log${NC}"
    fi
fi
echo

# ── Step 4: Start web dashboard ────────────────────────────────────────
echo -e "${YELLOW}▶ Step 4: Web dashboard...${NC}"
if port_open 8080; then
    echo -e "  Already running ✓"
else
    if [ "$FOREGROUND" = true ]; then
        echo -e "  ${GREEN}Starting in foreground (Ctrl+C to stop)...${NC}"
        echo
        exec .venv/bin/python scripts/run_web.py --port 8080
        # exec replaces the script — nothing below runs
    else
        setsid .venv/bin/uvicorn indian_quant.web.app:app --host 127.0.0.1 --port 8080 --log-level warning < /dev/null > /tmp/web.log 2>&1 &
        sleep 3
        if port_open 8080; then
            echo -e "  ${GREEN}✓ Started (port 8080)${NC}"
        else
            echo -e "  ${RED}✗ Failed — check /tmp/web.log${NC}"
        fi
    fi
fi
echo

# ── Status ──────────────────────────────────────────────────────────────
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║               Platform Status                ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo

check_port() {
    local port=$1 name=$2
    if port_open "$port"; then
        echo -e "  ${GREEN}●${NC} $name — port $port — ${GREEN}running${NC}"
    else
        echo -e "  ${RED}●${NC} $name — port $port — ${RED}not running${NC}"
    fi
}
check_proc() {
    local pattern=$1 name=$2
    if pgrep -f "$pattern" >/dev/null 2>&1; then
        local pid
        pid=$(pgrep -f "$pattern" | head -1)
        echo -e "  ${GREEN}●${NC} $name — PID $pid — ${GREEN}running${NC}"
    else
        echo -e "  ${RED}●${NC} $name — ${RED}not running${NC}"
    fi
}

check_port 3000 "MCP Server (nse-bse-mcp)"
check_port 8080 "Web Dashboard"
check_proc "announcements_backfill" "Announcements Backfill"
echo
echo -e "  ${CYAN}Dashboard:${NC} http://127.0.0.1:8080"
echo -e "  ${CYAN}Dashboard:${NC} http://127.0.0.1:8080/signals"
echo -e "  ${CYAN}Dashboard:${NC} http://127.0.0.1:8080/suggestions"
echo -e "  ${CYAN}Dashboard:${NC} http://127.0.0.1:8080/positions"
echo -e "  ${CYAN}Dashboard:${NC} http://127.0.0.1:8080/research"
echo
echo -e "  Logs: /tmp/web.log  /tmp/nse-bse-mcp.log  /tmp/backfill.log"
echo -e "  Stop: ${YELLOW}./stop_platform.sh${NC}"
