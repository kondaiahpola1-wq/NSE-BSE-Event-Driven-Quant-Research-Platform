"""Build market cap data for all stocks using NSE/BSE official APIs.

Fallback order (verified, benchmark-tested):
  1. niftyindices.com CSVs  — instant bulk, 450 NSE index stocks
  2. NSE API (nse lib)      — 0.36s/stock, totalMarketCap for all NSE stocks
  3. BSE API (bse lib)      — 0.18s/stock, MktCapFull for all BSE stocks
  4. yfinance parallel      — 0.27s/stock, for any remaining misses
  5. Classify by SEBI thresholds using actual market cap values

Usage:
    python scripts/build_market_cap.py
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from indian_quant.features.market_cap import (
    LARGE_CAP_MIN,
    MCAP_FILE,
    MID_CAP_MIN,
    SMALL_CAP_MIN,
    classify_by_value,
    save_mcap_cache,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

INDEX_URLS = {
    "NIFTY 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "NIFTY Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "NIFTY Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


# ---------------------------------------------------------------------------
# Phase 1: niftyindices.com CSVs (instant)
# ---------------------------------------------------------------------------

def fetch_index_symbols() -> dict[str, set[str]]:
    """Download index constituent CSVs and extract symbols."""
    client = httpx.Client(timeout=15.0, follow_redirects=True)
    index_symbols: dict[str, set[str]] = {}

    for index_name, url in INDEX_URLS.items():
        try:
            resp = client.get(url, headers=HEADERS)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            symbols = {row.get("Symbol", "").strip() for row in reader if row.get("Symbol", "").strip()}
            index_symbols[index_name] = symbols
            logger.info(f"  {index_name}: {len(symbols)} symbols")
        except Exception as e:
            logger.warning(f"  {index_name}: FAILED ({e})")
            index_symbols[index_name] = set()

    client.close()
    return index_symbols


# ---------------------------------------------------------------------------
# Phase 2: NSE API (nse lib) — market cap for all NSE stocks
# ---------------------------------------------------------------------------

def fetch_nse_market_cap(
    symbols: list[str],
    save_fn=None,
    nifty50: set | None = None,
    midcap150: set | None = None,
    smallcap250: set | None = None,
) -> dict[str, float]:
    """Fetch market cap from NSE API for all NSE symbols."""
    from nse import NSE

    results: dict[str, float] = {}
    failed = 0

    with NSE(download_folder="/tmp/nse_mcap", server=True) as nse:
        for i, sym in enumerate(symbols):
            try:
                data = nse.getDetailedScripData(sym)
                equity = data.get("equityResponse", [{}])[0]
                trade_info = equity.get("tradeInfo", {})
                mcap = trade_info.get("totalMarketCap")
                if mcap:
                    results[sym] = round(mcap / 1e7, 2)  # raw ₹ → Cr
            except Exception:
                failed += 1

            if (i + 1) % 200 == 0:
                logger.info(f"  NSE: {i + 1}/{len(symbols)} done, {len(results)} hits, {failed} failed")
            if save_fn and (i + 1) % 500 == 0:
                save_fn(results, {}, {})
                logger.info(f"  NSE checkpoint saved at {i + 1}/{len(symbols)}")
            time.sleep(0.35)  # respect 3 req/sec rate limit

    logger.info(f"  NSE: {len(results)}/{len(symbols)} fetched, {failed} failed")
    return results


# ---------------------------------------------------------------------------
# Phase 3: BSE API (bse lib) — market cap for all BSE stocks
# ---------------------------------------------------------------------------

def fetch_bse_market_cap(
    symbols: list[str],
    save_fn=None,
    nse_mcap: dict | None = None,
    nifty50: set | None = None,
    midcap150: set | None = None,
    smallcap250: set | None = None,
) -> dict[str, float]:
    """Fetch market cap from BSE API for all BSE symbols."""
    from bse import BSE

    results: dict[str, float] = {}
    failed = 0

    with BSE(download_folder="/tmp/bse_mcap") as bse:
        for i, sym in enumerate(symbols):
            try:
                code = bse.getScripCode(sym)
                if code:
                    stats = bse.getScripTradingStats(code)
                    mcap_str = stats.get("MktCapFull", "")
                    if mcap_str and mcap_str not in ("", "N/A", "--"):
                        mcap_cr = float(mcap_str.replace(",", ""))
                        results[sym] = round(mcap_cr, 2)
            except Exception:
                failed += 1

            if (i + 1) % 200 == 0:
                logger.info(f"  BSE: {i + 1}/{len(symbols)} done, {len(results)} hits, {failed} failed")
            if save_fn and (i + 1) % 500 == 0:
                save_fn(results)
                logger.info(f"  BSE checkpoint saved at {i + 1}/{len(symbols)}")
            time.sleep(0.35)

    logger.info(f"  BSE: {len(results)}/{len(symbols)} fetched, {failed} failed")
    return results


# ---------------------------------------------------------------------------
# Phase 4: yfinance fallback (for any remaining misses)
# ---------------------------------------------------------------------------

def _fetch_yfinance_mcap(sym: str) -> tuple[str, float | None]:
    """Fetch market cap from yfinance for one symbol."""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{sym}.NS")
        mcap = t.info.get("marketCap")
        return sym, round(mcap / 1e7, 2) if mcap else None
    except Exception:
        return sym, None


def fetch_yfinance_bulk(symbols: list[str], max_workers: int = 10) -> dict[str, float]:
    """Fetch market cap for remaining symbols from yfinance in parallel."""
    results: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_yfinance_mcap, sym): sym for sym in symbols}
        done = 0
        for future in as_completed(futures):
            sym, mcap = future.result()
            done += 1
            if mcap is not None:
                results[sym] = mcap
            if done % 200 == 0:
                logger.info(f"  yfinance: {done}/{len(symbols)} done, {len(results)} hits")

    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_universe() -> dict[str, dict]:
    """Load universe registry."""
    reg_file = Path("data/universe/registry.json")
    if not reg_file.exists():
        logger.error("registry.json not found")
        return {}
    data = json.loads(reg_file.read_text())
    return data.get("symbols", {})


def _save_intermediate(
    symbols_data: dict,
    nifty50: set,
    midcap150: set,
    smallcap250: set,
    nse_mcap: dict[str, float],
    bse_mcap: dict[str, float],
    yf_mcap: dict[str, float],
) -> None:
    """Save intermediate results so progress is not lost on interrupt."""
    # Load existing cache to preserve previous fetches
    prev = {}
    if MCAP_FILE.exists():
        prev = json.loads(MCAP_FILE.read_text())
    results: dict[str, dict] = {}
    for sym_info in symbols_data.values():
        symbol = sym_info.get("symbol", "")
        exchange = sym_info.get("exchange", "NSE")
        key = f"{exchange}|{symbol}"
        mcap_cr = None
        source = "index"
        if symbol in nifty50:
            tier = "Large Cap"
            mcap_cr = LARGE_CAP_MIN
        elif symbol in midcap150:
            tier = "Mid Cap"
            mcap_cr = MID_CAP_MIN
        elif symbol in smallcap250:
            tier = "Small Cap"
            mcap_cr = SMALL_CAP_MIN
        elif symbol in nse_mcap:
            mcap_cr = nse_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "nse_api"
        elif symbol in bse_mcap:
            mcap_cr = bse_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "bse_api"
        elif symbol in yf_mcap:
            mcap_cr = yf_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "yfinance"
        else:
            tier = "Other"
            source = "unknown"

        # Use previous cache value if no new data
        if source == "unknown" and key in prev:
            results[key] = prev[key]
        else:
            results[key] = {
                "market_cap_cr": round(mcap_cr, 2) if mcap_cr else None,
                "market_cap_class": tier,
                "source": source,
            }
    save_mcap_cache(results)
    classes = {}
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
    logger.info(f"  Intermediate save: {len(results)} stocks, {json.dumps(classes)}")


def main() -> int:
    start_total = time.time()

    symbols_data = load_universe()
    if not symbols_data:
        return 1

    nse_symbols = [v["symbol"] for v in symbols_data.values() if v.get("exchange") == "NSE"]
    bse_symbols = [v["symbol"] for v in symbols_data.values() if v.get("exchange") == "BSE"]
    logger.info(f"Universe: {len(nse_symbols)} NSE, {len(bse_symbols)} BSE")

    # Load existing cache to skip already-fetched stocks
    results_cache = {}
    if MCAP_FILE.exists():
        results_cache = json.loads(MCAP_FILE.read_text())
        logger.info(f"Loaded existing cache: {len(results_cache)} entries")

    # Phase 1: Index classification (instant)
    logger.info("\n=== Phase 1: NSE index constituents ===")
    index_symbols = fetch_index_symbols()
    nifty50 = index_symbols.get("NIFTY 50", set())
    midcap150 = index_symbols.get("NIFTY Midcap 150", set())
    smallcap250 = index_symbols.get("NIFTY Smallcap 250", set())
    classified_by_index = nifty50 | midcap150 | smallcap250

    # Phase 2: NSE API for remaining NSE stocks
    logger.info("\n=== Phase 2: NSE API (getDetailedScripData) ===")
    existing_nse = {k.split("|")[1] for k, v in results_cache.items() if v.get("source") == "nse_api"}
    remaining_nse = [s for s in nse_symbols if s not in classified_by_index and s not in existing_nse]
    logger.info(f"  Remaining NSE stocks: {len(remaining_nse)} (already have {len(existing_nse)} from cache)")

    nse_start = time.time()
    nse_mcap = fetch_nse_market_cap(
        remaining_nse,
        save_fn=lambda nse_m, bse_m, yf_m: _save_intermediate(
            symbols_data, nifty50, midcap150, smallcap250, nse_m, bse_m, yf_m
        ),
    )
    nse_time = time.time() - nse_start
    logger.info(f"  NSE done in {nse_time:.0f}s")

    # Save intermediate results after NSE phase
    _save_intermediate(symbols_data, nifty50, midcap150, smallcap250, nse_mcap, {}, {})

    # Phase 3: BSE API for all BSE stocks
    logger.info("\n=== Phase 3: BSE API (getScripTradingStats) ===")
    existing_bse = {k.split("|")[1] for k, v in results_cache.items() if v.get("source") == "bse_api"}
    remaining_bse = [s for s in bse_symbols if s not in existing_bse]
    logger.info(f"  Remaining BSE stocks: {len(remaining_bse)} (already have {len(existing_bse)} from cache)")

    bse_start = time.time()
    bse_mcap = fetch_bse_market_cap(
        remaining_bse,
        save_fn=lambda bse_m: _save_intermediate(
            symbols_data, nifty50, midcap150, smallcap250, nse_mcap, bse_m, {}
        ),
    )
    bse_time = time.time() - bse_start
    logger.info(f"  BSE done in {bse_time:.0f}s")

    # Save intermediate results after BSE phase
    _save_intermediate(symbols_data, nifty50, midcap150, smallcap250, nse_mcap, bse_mcap, {})

    # Phase 4: yfinance for remaining misses
    all_hits = set(classified_by_index) | set(all_nse_mcap.keys()) | set(all_bse_mcap.keys())
    nse_misses = [s for s in nse_symbols if s not in all_hits]
    bse_misses = [s for s in bse_symbols if s not in all_hits]
    misses = nse_misses + bse_misses

    if misses:
        logger.info(f"\n=== Phase 4: yfinance fallback ({len(misses)} misses) ===")
        yf_start = time.time()
        yf_mcap = fetch_yfinance_bulk(misses, max_workers=10)
        yf_time = time.time() - yf_start
        logger.info(f"  yfinance done in {yf_time:.0f}s, {len(yf_mcap)} hits")
    else:
        yf_mcap = {}
        logger.info("\n=== Phase 4: yfinance fallback (0 misses, skipped) ===")

    # Combine all data (merge existing cache with new fetches)
    logger.info("\n=== Building classification ===")
    # Load existing NSE/BSE data from cache
    existing_nse_mcap = {}
    existing_bse_mcap = {}
    for k, v in results_cache.items():
        parts = k.split("|", 1)
        if len(parts) == 2:
            exchange, symbol = parts
            src = v.get("source", "")
            mcap = v.get("market_cap_cr")
            if src == "nse_api" and mcap:
                existing_nse_mcap[symbol] = mcap
            elif src == "bse_api" and mcap:
                existing_bse_mcap[symbol] = mcap
    # Merge: new data overrides existing
    all_nse_mcap = {**existing_nse_mcap, **nse_mcap}
    all_bse_mcap = {**existing_bse_mcap, **bse_mcap}
    logger.info(f"  NSE data: {len(all_nse_mcap)} total ({len(nse_mcap)} new)")
    logger.info(f"  BSE data: {len(all_bse_mcap)} total ({len(bse_mcap)} new)")

    results: dict[str, dict] = {}

    for sym_info in symbols_data.values():
        symbol = sym_info.get("symbol", "")
        exchange = sym_info.get("exchange", "NSE")
        key = f"{exchange}|{symbol}"

        mcap_cr = None
        source = "index"

        if symbol in nifty50:
            tier = "Large Cap"
            mcap_cr = LARGE_CAP_MIN
        elif symbol in midcap150:
            tier = "Mid Cap"
            mcap_cr = MID_CAP_MIN
        elif symbol in smallcap250:
            tier = "Small Cap"
            mcap_cr = SMALL_CAP_MIN
        elif symbol in all_nse_mcap:
            mcap_cr = all_nse_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "nse_api"
        elif symbol in all_bse_mcap:
            mcap_cr = all_bse_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "bse_api"
        elif symbol in yf_mcap:
            mcap_cr = yf_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "yfinance"
        else:
            tier = "Other"
            source = "unknown"

        results[key] = {
            "market_cap_cr": round(mcap_cr, 2) if mcap_cr else None,
            "market_cap_class": tier,
            "source": source,
        }

    save_mcap_cache(results)

    # Summary
    classes: dict[str, int] = {}
    sources: dict[str, int] = {}
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
        src = v.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    total_time = time.time() - start_total
    logger.info(f"\n=== Summary ===")
    logger.info(f"Total time: {total_time:.0f}s ({total_time/60:.1f}min)")
    logger.info(f"Classification: {json.dumps(classes, indent=2)}")
    logger.info(f"Sources: {json.dumps(sources, indent=2)}")
    logger.info(f"Saved to {MCAP_FILE}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
