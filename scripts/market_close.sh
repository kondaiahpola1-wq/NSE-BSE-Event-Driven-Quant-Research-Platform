#!/usr/bin/env bash
# market_close.sh — Stop heavy background jobs at 16:00 IST, keep web alive
set -euo pipefail
LOG="/tmp/nse-platform-cron/market_close.log"
mkdir -p /tmp/nse-platform-cron
echo "$(date '+%Y-%m-%d %H:%M:%S') Market close: stopping heavy jobs" >> "$LOG"
for proc in announcements_backfill bulk_ingest daily_signals paper_track suggestion_manager cache_signals; do
    pkill -f "$proc" 2>/dev/null || true
done
echo "$(date '+%Y-%m-%d %H:%M:%S') Heavy jobs stopped. Web stays alive." >> "$LOG"
