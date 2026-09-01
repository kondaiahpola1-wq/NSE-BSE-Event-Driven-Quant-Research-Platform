#!/usr/bin/env bash
# morning_start.sh — Start scheduler daemon + MCP + web at 08:00 IST
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="/tmp/nse-platform-cron"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') Morning start: launching platform" >> "$LOG_DIR/start.log"

cd "$ROOT"

# Start scheduler daemon (forks to background)
nohup .venv/bin/python scripts/platform_scheduler.py >> "$LOG_DIR/scheduler.log" 2>&1 &
echo "$(date '+%Y-%m-%d %H:%M:%S') Scheduler daemon started (PID $!)" >> "$LOG_DIR/start.log"

# Start web dashboard if not running
if ! (exec 3<>"/dev/tcp/127.0.0.1/8080") 2>/dev/null; then
    setsid .venv/bin/uvicorn indian_quant.web.app:app \
        --host 127.0.0.1 --port 8080 --log-level warning \
        < /dev/null >> "$LOG_DIR/web.log" 2>&1 &
    sleep 3
    if (exec 3<>"/dev/tcp/127.0.0.1/8080") 2>/dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') Web started on port 8080" >> "$LOG_DIR/start.log"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') Web FAILED to start" >> "$LOG_DIR/start.log"
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Web already running on 8080" >> "$LOG_DIR/start.log"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Platform startup complete" >> "$LOG_DIR/start.log"
