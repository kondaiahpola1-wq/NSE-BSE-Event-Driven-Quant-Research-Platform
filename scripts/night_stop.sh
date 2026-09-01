#!/usr/bin/env bash
# night_stop.sh — Stop everything at 21:00 IST
set -euo pipefail
LOG="/tmp/nse-platform-cron/night_stop.log"
mkdir -p /tmp/nse-platform-cron
echo "$(date '+%Y-%m-%d %H:%M:%S') Night stop: stopping all services" >> "$LOG"
for proc in announcements_backfill bulk_ingest daily_signals paper_track suggestion_manager cache_signals platform_scheduler; do
    pkill -f "$proc" 2>/dev/null || true
done
fuser -k 8080/tcp 2>/dev/null || true
echo "$(date '+%Y-%m-%d %H:%M:%S') All services stopped for the night." >> "$LOG"
