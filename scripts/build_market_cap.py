"""Build market cap classification from NSE index constituents.

Classification:
  Large Cap: NIFTY 50 constituents
  Mid Cap:   NIFTY Midcap 150 constituents
  Small Cap: NIFTY Smallcap 250 constituents
  Micro Cap: Everything else

Data source: niftyindices.com CSVs (free, no auth, official NSE data).

Usage:
    python scripts/build_market_cap.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from indian_quant.features.market_cap import MCAP_FILE, classify_by_value, save_mcap_cache

INDEX_URLS = {
    "NIFTY 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "NIFTY Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "NIFTY Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
}

# Approximate market cap thresholds for unknown stocks (₹ Cr)
# Based on SEBI definitions
TIER_THRESHOLDS = {
    "NIFTY 50": ("Large Cap", 20000),
    "NIFTY Midcap 150": ("Mid Cap", 5000),
    "NIFTY Smallcap 250": ("Small Cap", 500),
}


def fetch_index_symbols() -> dict[str, set[str]]:
    """Download index constituent CSVs and extract symbols."""
    client = httpx.Client(timeout=15.0, follow_redirects=True)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    index_symbols: dict[str, set[str]] = {}

    for index_name, url in INDEX_URLS.items():
        try:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            symbols = set()
            for row in reader:
                sym = row.get("Symbol", "").strip()
                if sym:
                    symbols.add(sym)
            index_symbols[index_name] = symbols
            print(f"  {index_name}: {len(symbols)} symbols")
        except Exception as e:
            print(f"  {index_name}: FAILED ({e})")
            index_symbols[index_name] = set()

    client.close()
    return index_symbols


def classify_all_universe(index_symbols: dict[str, set[str]]) -> dict[str, dict]:
    """Classify all universe symbols by market cap tier."""
    # Load universe
    reg_file = Path("data/universe/registry.json")
    if not reg_file.exists():
        print("ERROR: registry.json not found")
        return {}

    data = json.loads(reg_file.read_text())
    symbols_data = data.get("symbols", {})
    if isinstance(symbols_data, dict):
        symbols_list = list(symbols_data.values())
    else:
        symbols_list = symbols_data

    # Load existing cache to preserve market_cap_cr values
    existing = {}
    if MCAP_FILE.exists():
        try:
            existing = json.loads(MCAP_FILE.read_text())
        except Exception:
            pass

    results = {}
    nifty50 = index_symbols.get("NIFTY 50", set())
    midcap150 = index_symbols.get("NIFTY Midcap 150", set())
    smallcap250 = index_symbols.get("NIFTY Smallcap 250", set())

    large_count = mid_count = small_count = other_count = 0

    for sym_info in symbols_list:
        symbol = sym_info.get("symbol", "")
        exchange = sym_info.get("exchange", "NSE")
        key = f"{exchange}|{symbol}"

        # Preserve existing market_cap_cr if available
        prev_mcap = existing.get(key, {}).get("market_cap_cr")
        mcap_cr = prev_mcap

        # Classify by index membership
        if exchange == "BSE" and not sym_info.get("dual_listed"):
            tier = "Other"
            other_count += 1
        elif symbol in nifty50:
            tier = "Large Cap"
            large_count += 1
        elif symbol in midcap150:
            tier = "Mid Cap"
            mid_count += 1
        elif symbol in smallcap250:
            tier = "Small Cap"
            small_count += 1
        elif mcap_cr is not None and mcap_cr < 1000:
            # Only classify as Micro Cap if we have actual data < 1000 Cr
            tier = "Micro Cap"
            other_count += 1
        else:
            tier = "Other"
            other_count += 1

        results[key] = {
            "market_cap_cr": mcap_cr,
            "market_cap_class": tier,
        }

    print(f"\nClassification: Large={large_count}, Mid={mid_count}, "
          f"Small={small_count}, Other={other_count}, Total={len(results)}")

    return results


def main() -> int:
    print("Fetching NSE index constituents...")
    index_symbols = fetch_index_symbols()

    print("\nClassifying universe...")
    results = classify_all_universe(index_symbols)

    if results:
        save_mcap_cache(results)
        print(f"Saved to {MCAP_FILE}")

    # Verify
    classes = {}
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
    print(f"\nFinal: {json.dumps(classes, indent=2)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
