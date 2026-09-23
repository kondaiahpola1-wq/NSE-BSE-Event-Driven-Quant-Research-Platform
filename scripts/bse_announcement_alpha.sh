#!/bin/bash
# BSE Announcement Alpha - Paper Order Launcher
# Runs download → scan → paper order pipeline
# Usage: ./scripts/bse_announcement_alpha.sh [--download-only] [--order-only]

set -euo pipefail

source /home/ubuntu/anaconda3/etc/profile.d/conda.sh
conda activate Analysis_Bse_Nse

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

DOWNLOAD_ONLY="${1:-}"

echo "[$(date)] BSE Announcement Alpha pipeline started"

if [ "$DOWNLOAD_ONLY" != "--order-only" ]; then
    echo "[$(date)] Downloading announcements..."
    .venv/bin/python scripts/bse_announcement_alpha/download.py --days 1 --output-dir ./Bse_Nse_announcement_downloads
fi

echo "[$(date)] Scanning for alpha signals..."
.venv/bin/python scripts/bse_announcement_alpha/scan.py --data-dir ./Bse_Nse_announcement_downloads --instrument-master data/upstox_master.csv.gz --save data/normalized/announcements/announcement_alpha_$(date +%Y-%m-%d).json

if [ "$DOWNLOAD_ONLY" != "--download-only" ]; then
    echo "[$(date)] Placing paper orders..."
    .venv/bin/python scripts/bse_announcement_alpha/order.py --data-dir ./Bse_Nse_announcement_downloads --instrument-master data/upstox_master.csv.gz
fi

echo "[$(date)] Pipeline complete"