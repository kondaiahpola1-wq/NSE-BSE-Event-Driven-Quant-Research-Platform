"""Fast market cap fetch — only for symbols that have signals in PostgreSQL.

Usage:
    python scripts/fetch_market_cap_fast.py
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa

from indian_quant.features.market_cap import MCAP_FILE, classify_by_value, save_mcap_cache


def get_signal_symbols() -> list[tuple[str, str]]:
    """Get all unique (symbol, exchange) pairs from cached_signals."""
    engine = sa.create_engine("postgresql://postgres:quant2026@127.0.0.1:5432/postgres")
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT DISTINCT symbol, exchange FROM cached_signals")
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def fetch_one(symbol: str, exchange: str) -> dict:
    """Fetch market cap for a single symbol via yfinance."""
    import yfinance as yf

    suffix = ".NS" if exchange == "NSE" else ".BO"
    key = f"{exchange}|{symbol}"
    try:
        info = yf.Ticker(f"{symbol}{suffix}").info
        mcap = info.get("marketCap")
        if mcap and isinstance(mcap, (int, float)) and mcap > 0:
            mcap_cr = round(mcap / 1e7, 2)
            return {
                key: {
                    "market_cap_cr": mcap_cr,
                    "market_cap_class": classify_by_value(mcap_cr),
                }
            }
    except Exception:
        pass
    return {key: {"market_cap_cr": None, "market_cap_class": "Unknown"}}


def main() -> int:
    symbols = get_signal_symbols()
    print(f"Fetching market cap for {len(symbols)} symbols with signals...")

    # Load existing cache
    existing = {}
    if MCAP_FILE.exists():
        try:
            existing = json.loads(MCAP_FILE.read_text())
            print(f"Loaded {len(existing)} cached entries")
        except Exception:
            pass

    # Filter out already cached
    todo = [(s, e) for s, e in symbols if f"{e}|{s}" not in existing]
    print(f"To fetch: {len(todo)} (skipping {len(symbols) - len(todo)} cached)")

    if not todo:
        print("Nothing to fetch")
        return 0

    # Parallel fetch
    results = dict(existing)
    t0 = time.time()
    done = 0
    with_mcap = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, s, e): (s, e) for s, e in todo}
        for future in as_completed(futures):
            result = future.result()
            results.update(result)
            done += 1
            for v in result.values():
                if v.get("market_cap_cr") is not None:
                    with_mcap += 1
            if done % 100 == 0:
                print(f"  {done}/{len(todo)} done ({time.time() - t0:.0f}s)", flush=True)

    # Save
    save_mcap_cache(results)

    # Summary
    classes = {}
    total_with = 0
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
        if v.get("market_cap_cr") is not None:
            total_with += 1

    print(f"\n{'=' * 50}")
    print(f"Total: {len(results)} cached, {total_with} with market cap")
    print(f"Classification: {json.dumps(classes, indent=2)}")
    print(f"Time: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
