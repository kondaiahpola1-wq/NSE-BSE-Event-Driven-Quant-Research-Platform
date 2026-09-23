#!/usr/bin/env bash
# health_check.sh — Cron watchdog for platform services.
# Runs every 30 min via crontab.
#
# Web: always ensure alive (24/7 research access)
# MCP + Scheduler: only during market/evening hours
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
LOG_DIR="$(cd "$(dirname "$0")/.." && pwd)/logs"
mkdir -p "$LOG_DIR"

IST_HOUR=$(TZ=Asia/Kolkata date +%-H)
IST_DOW=$(TZ=Asia/Kolkata date +%u)  # 1=Mon .. 7=Sun

IS_WEEKDAY=0
[ "$IST_DOW" -le 5 ] && IS_WEEKDAY=1

IS_MARKET=0
IS_EVENING=0
[ "$IS_WEEKDAY" -eq 1 ] && [ "$IST_HOUR" -ge 8 ] && [ "$IST_HOUR" -lt 16 ] && IS_MARKET=1
[ "$IS_WEEKDAY" -eq 1 ] && [ "$IST_HOUR" -ge 18 ] && [ "$IST_HOUR" -lt 21 ] && IS_EVENING=1

# ── Helper functions ───────────────────────────────────────────────────────
port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- 3>&-
}

ensure_web() {
    if port_open 8080; then
        return 0
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web dead, restarting..." >> "$LOG_DIR/health.log"
    cd "$ROOT"
    setsid "$VENV" -m uvicorn indian_quant.web.app:app \
        --host 0.0.0.0 --port 8080 --log-level warning \
        < /dev/null >> "$LOG_DIR/web.log" 2>&1 &
    sleep 3
    if port_open 8080; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web restarted OK" >> "$LOG_DIR/health.log"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web restart FAILED" >> "$LOG_DIR/health.log"
    fi
}

ensure_mcp() {
    if pgrep -f "nse-bse-mcp" >/dev/null 2>&1; then
        return 0
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: MCP dead, restarting..." >> "$LOG_DIR/health.log"
    cd /tmp && npx -y nse-bse-mcp >> "$LOG_DIR/mcp.log" 2>&1 &
    sleep 3
    if pgrep -f "nse-bse-mcp" >/dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: MCP restarted OK" >> "$LOG_DIR/health.log"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: MCP restart FAILED" >> "$LOG_DIR/health.log"
    fi
    cd "$ROOT"
}

ensure_scheduler() {
    if pgrep -f "platform_scheduler" >/dev/null 2>&1; then
        return 0
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Scheduler dead, restarting..." >> "$LOG_DIR/health.log"
    cd "$ROOT"
    nohup "$VENV" scripts/platform_scheduler.py --daemon >> "$LOG_DIR/scheduler.log" 2>&1 &
    sleep 2
    if pgrep -f "platform_scheduler" >/dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Scheduler restarted OK" >> "$LOG_DIR/health.log"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Scheduler restart FAILED" >> "$LOG_DIR/health.log"
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────
# Web always — 24/7 research access
ensure_web

# MCP + Scheduler — market/evening hours only
if [ "$IS_MARKET" -eq 1 ] || [ "$IS_EVENING" -eq 1 ]; then
    ensure_mcp
    ensure_scheduler
fi

# Upstox token watchdog — check every run, refresh if <5 min remaining
BROWSING_PYTHON="/home/ubuntu/Documents/projects/projects_agn/Browsing/venv/bin/python"
if [ -x "$BROWSING_PYTHON" ] && [ -f "$ROOT/scripts/upstox_token_watchdog.py" ]; then
    "$BROWSING_PYTHON" "$ROOT/scripts/upstox_token_watchdog.py" --threshold 5 >> "$LOG_DIR/upstox_watchdog.log" 2>&1 || true
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: check OK (market=$IS_MARKET evening=$IS_EVENING)" >> "$LOG_DIR/health.log"
