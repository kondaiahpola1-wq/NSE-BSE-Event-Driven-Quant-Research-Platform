from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.announcements import BSEAnnouncementClient


def download(args: argparse.Namespace) -> None:
    client = BSEAnnouncementClient(download_folder=args.output_dir)
    from_date = datetime.now() - timedelta(days=args.days)
    all_ann = client.fetch_all_announcements(
        from_date=from_date,
        segment=args.segment,
        output_path=args.output_file,
    )
    print(f"Downloaded {len(all_ann)} announcements")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download BSE announcements")
    parser.add_argument("--output-dir", default="./Bse_Nse_announcement_downloads")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--segment", default="equity")
    parser.add_argument("--output-file", default=None)
    args = parser.parse_args()
    download(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())