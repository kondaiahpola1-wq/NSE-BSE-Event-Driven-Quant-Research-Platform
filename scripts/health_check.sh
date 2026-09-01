#!/usr/bin/env bash
# health_check.sh — Lightweight cron watchdog for platform services.
# Runs every 30 min via crontab. Only restarts during active hours.
#
# Schedule:
#   08:00–16:00 IST Mon-Fri: ensure MCP + web alive
#   18:00–21:00 IST Mon-Fri: ensure web alive
#   Weekends: skip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
LOG_DIR="/tmp/nse-platform-cron"
mkdir -p "$LOG_DIR"

IST_HOUR=$(TZ=Asia/Kolkata date +%-H)
IST_DOW=$(TZ=Asia/Kolkata date +%u)  # 1=Mon .. 7=Sun

# ── Skip weekends ──────────────────────────────────────────────────────────
if [ "$IST_DOW" -gt 5 ]; then
    exit 0
fi

# ── Skip outside active hours ──────────────────────────────────────────────
IS_MARKET=0
IS_EVENING=0
[ "$IST_HOUR" -ge 8 ] && [ "$IST_HOUR" -lt 16 ] && IS_MARKET=1
[ "$IST_HOUR" -ge 18 ] && [ "$IST_HOUR" -lt 21 ] && IS_EVENING=1

if [ "$IS_MARKET" -eq 0 ] && [ "$IS_EVENING" -eq 0 ]; then
    exit 0
fi

# ── Helper functions ───────────────────────────────────────────────────────
port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- 3>&-
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

ensure_web() {
    if port_open 8080; then
        return 0
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web dead, restarting..." >> "$LOG_DIR/health.log"
    cd "$ROOT"
    setsid "$VENV" -m uvicorn indian_quant.web.app:app \
        --host 127.0.0.1 --port 8080 --log-level warning \
        < /dev/null >> "$LOG_DIR/web.log" 2>&1 &
    sleep 3
    if port_open 8080; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web restarted OK" >> "$LOG_DIR/health.log"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: Web restart FAILED" >> "$LOG_DIR/health.log"
    fi
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
if [ "$IS_MARKET" -eq 1 ]; then
    ensure_mcp
    ensure_web
    ensure_scheduler
elif [ "$IS_EVENING" -eq 1 ]; then
    ensure_web
    ensure_scheduler
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') HEALTH: check OK (market=$IS_MARKET evening=$IS_EVENING)" >> "$LOG_DIR/health.log"
