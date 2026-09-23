from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.announcements import AnnouncementScanner, Watchlist
from indian_quant.config.connections import get_engine


def scan_and_save(args: argparse.Namespace) -> None:
    watchlist = Watchlist()
    scanner = AnnouncementScanner(
        data_dir=args.data_dir,
        instrument_master=args.instrument_master,
        watchlist=watchlist.symbols,
    )
    now_ist = datetime.now()
    result = scanner.scan(date_str=args.date, now_ist=now_ist)
    print(f"Scanned {result.date_str}: {result.total_announcements} total, {result.filtered_announcements} alpha, {len(result.signals)} signals")
    print(f"Watchlist: {len(watchlist)} symbols loaded")
    if args.save:
        output = Path(args.save)
        output.parent.mkdir(parents=True, exist_ok=True)
        records = [s.__dict__ for s in result.signals]
        with open(output, "w") as f:
            json.dump(records, f, indent=2, default=str)
        print(f"Saved {len(records)} signals to {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BSE Announcement Alpha Scanner")
    parser.add_argument("--date", default=None, help="Date to scan (YYYY-MM-DD)")
    parser.add_argument("--data-dir", default="./Bse_Nse_announcement_downloads")
    parser.add_argument("--instrument-master", default="data/upstox_master.csv.gz")
    parser.add_argument("--save", default=None, help="Save results to JSON file")
    args = parser.parse_args()
    scan_and_save(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())