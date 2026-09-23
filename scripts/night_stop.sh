#!/usr/bin/env bash
# night_stop.sh — Stop heavy background jobs at 21:00 IST
# Web stays alive 24/7 for research. Scheduler handles its own lifecycle.
set -euo pipefail
LOG="$(cd "$(dirname "$0")/.." && pwd)/logs/night_stop.log"
mkdir -p "$(dirname "$LOG")"
echo "$(date '+%Y-%m-%d %H:%M:%S') Night stop: stopping heavy jobs" >> "$LOG"
for proc in announcements_backfill bulk_ingest daily_signals paper_track suggestion_manager cache_signals; do
    pkill -f "$proc" 2>/dev/null || true
done
echo "$(date '+%Y-%m-%d %H:%M:%S') Heavy jobs stopped. Web and scheduler stay alive." >> "$LOG"
