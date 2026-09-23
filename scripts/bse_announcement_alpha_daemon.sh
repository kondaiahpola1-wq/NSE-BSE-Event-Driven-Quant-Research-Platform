#!/bin/bash
# BSE Announcement Alpha — Continuous Daemon
# Runs download → scan → paper order every 10 seconds, 24/7.
# Paper only (sandbox). No real money at risk.

set -euo pipefail

source /home/ubuntu/anaconda3/etc/profile.d/conda.sh
conda activate Analysis_Bse_Nse

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

INTERVAL="${1:-10}"  # seconds between runs

echo "[$(date)] BSE Announcement Alpha daemon started (interval: ${INTERVAL}s)"

while true; do
    echo "[$(date)] Running pipeline..."
    .venv/bin/python scripts/bse_announcement_alpha/download.py --days 1 --output-dir ./Bse_Nse_announcement_downloads >> logs/bse_announcement_alpha_daemon.log 2>&1
    .venv/bin/python scripts/bse_announcement_alpha/scan.py --data-dir ./Bse_Nse_announcement_downloads --instrument-master data/upstox_master.csv.gz >> logs/bse_announcement_alpha_daemon.log 2>&1
    .venv/bin/python scripts/bse_announcement_alpha/order.py --data-dir ./Bse_Nse_announcement_downloads --instrument-master data/upstox_master.csv.gz >> logs/bse_announcement_alpha_daemon.log 2>&1
    sleep "$INTERVAL"
done
