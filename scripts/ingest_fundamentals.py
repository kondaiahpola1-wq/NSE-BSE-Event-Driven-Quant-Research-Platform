#!/usr/bin/env python3
"""Ingest fundamental data for all stocks into PostgreSQL.

Data sources (cascade): FinStack key_ratios → Indian Market MCP → yfinance
Stores: company_profile, key_ratios

Usage:
    python scripts/ingest_fundamentals.py                    # Full universe
    python scripts/ingest_fundamentals.py --recent           # Only recently traded
    python scripts/ingest_fundamentals.py --symbol RELIANCE  # Single stock
    python scripts/ingest_fundamentals.py --batch-size 50 --sleep 2
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.pipeline.fundamentals import (
    ingest_all_fundamentals,
    ingest_fundamentals,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_fundamentals")


def main():
    parser = argparse.ArgumentParser(description="Ingest fundamental data into PostgreSQL")
    parser.add_argument("--symbol", help="Single symbol to ingest")
    parser.add_argument("--symbols", nargs="+", help="List of symbols to ingest")
    parser.add_argument("--recent", action="store_true", help="Only recently traded stocks")
    parser.add_argument("--batch-size", type=int, default=50, help="Symbols per batch")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args()

    if args.symbol:
        ok = ingest_fundamentals(args.symbol.upper())
        print(f"{'OK' if ok else 'NO DATA'}: {args.symbol}")
    elif args.symbols:
        for sym in args.symbols:
            ok = ingest_fundamentals(sym.upper())
            print(f"{'OK' if ok else 'NO DATA'}: {sym}")
    else:
        result = ingest_all_fundamentals(
            recent=args.recent,
            batch_size=args.batch_size,
            sleep=args.sleep,
        )
        print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
