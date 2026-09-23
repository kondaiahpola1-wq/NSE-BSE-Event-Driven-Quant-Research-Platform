#!/usr/bin/env python3
"""Ingest sector classification for all stocks into PostgreSQL.

Data sources (cascade): FinStack → Indian Market MCP → yfinance
Stores: sector_map

Usage:
    python scripts/ingest_sectors.py                    # Full universe
    python scripts/ingest_sectors.py --symbol RELIANCE  # Single stock
    python scripts/ingest_sectors.py --batch-size 50 --sleep 2
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.pipeline.sectors import (
    ingest_all_sectors,
    ingest_sectors,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_sectors")


def main():
    parser = argparse.ArgumentParser(description="Ingest sector data into PostgreSQL")
    parser.add_argument("--symbol", help="Single symbol to ingest")
    parser.add_argument("--batch-size", type=int, default=50, help="Symbols per batch")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args()

    if args.symbol:
        ok = ingest_sectors(args.symbol.upper())
        print(f"{'OK' if ok else 'NO DATA'}: {args.symbol}")
    else:
        result = ingest_all_sectors(
            batch_size=args.batch_size,
            sleep=args.sleep,
        )
        print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
