#!/usr/bin/env python3
"""Ingest sector classification and compute sector aggregates.

Usage:
    python scripts/ingest_sectors.py                    # Full universe
    python scripts/ingest_sectors.py --symbol RELIANCE  # Single stock
    python scripts/ingest_sectors.py --refresh          # Force refresh all
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import sqlalchemy as sa
from indian_quant.web.prod_config import get_pg_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_sectors")


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default
    except (ValueError, TypeError):
        return default


def fetch_sector(symbol: str) -> dict | None:
    """Fetch sector/industry for a symbol."""
    # 1. FinStack company_profile
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient
        client = FinStackClient()
        result = client.call_tool("company_profile", {"symbol": symbol})
        if result and isinstance(result, dict):
            sector = result.get("sector") or result.get("industry_sector")
            industry = result.get("industry") or result.get("industry_subsector")
            if sector:
                return {"sector": sector, "industry": industry}
    except Exception:
        pass

    # 2. Indian Market MCP
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient
        client = IndianMarketClient()
        result = client.call_tool("get_company_profile", {"symbol": symbol})
        if result and isinstance(result, dict):
            sector = result.get("sector")
            industry = result.get("industry")
            if sector:
                return {"sector": sector, "industry": industry}
    except Exception:
        pass

    # 3. yfinance fallback
    try:
        import yfinance as yf
        for suffix in (".NS", ".BO"):
            try:
                ticker = yf.Ticker(f"{symbol}{suffix}")
                info = ticker.info
                sector = info.get("sector")
                if sector:
                    return {"sector": sector, "industry": info.get("industry")}
            except Exception:
                continue
    except Exception:
        pass

    return None


def upsert_sector_map(engine, symbol: str, data: dict) -> None:
    """Store sector mapping."""
    values = {
        "symbol": symbol.upper(),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "nse_index": data.get("nse_index"),
        "sector_mcap_rank": data.get("sector_mcap_rank"),
        "updated_at": datetime.utcnow(),
    }
    cols = ", ".join(values.keys())
    phs = ", ".join(f":{k}" for k in values)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")
    sql = sa.text(
        f"INSERT INTO sector_map ({cols}) VALUES ({phs}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {updates}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def compute_sector_daily(engine, as_of: str | None = None) -> int:
    """Compute sector daily aggregates from delivery data.

    For each sector on each date, compute:
    - avg_return: average daily return
    - avg_deliv_z: average delivery z-score
    - avg_volume_z: average volume z-score
    - stock_count: number of stocks
    """
    delivery_dir = Path("data/normalized/delivery/NSE")
    if not delivery_dir.exists():
        log.warning("No delivery directory found")
        return 0

    # Load sector map
    sector_map = {}
    with engine.connect() as conn:
        result = conn.execute(sa.text("SELECT symbol, sector FROM sector_map WHERE sector IS NOT NULL"))
        for row in result:
            sector_map[row[0]] = row[1]

    if not sector_map:
        log.warning("No sector mappings found. Run sector map ingestion first.")
        return 0

    # Scan delivery parquets and compute sector aggregates
    sector_date_data = {}  # {sector: {date: [returns, deliv_zs, vol_zs]}}

    import numpy as np
    for parquet_file in sorted(delivery_dir.glob("*.parquet"))[:500]:
        try:
            symbol = parquet_file.stem
            sector = sector_map.get(symbol)
            if not sector:
                continue

            df = pd.read_parquet(parquet_file)
            if len(df) < 5:
                continue

            # Compute features
            df["ret_1d"] = df["close"].pct_change()
            if "deliv_pct" in df.columns:
                mean = df["deliv_pct"].rolling(30, min_periods=15).mean()
                std = df["deliv_pct"].rolling(30, min_periods=15).std().replace(0, np.nan)
                df["deliv_z"] = (df["deliv_pct"] - mean) / std
            if "volume" in df.columns:
                v_mean = df["volume"].rolling(30, min_periods=15).mean()
                v_std = df["volume"].rolling(30, min_periods=15).std().replace(0, np.nan)
                df["vol_z"] = (df["volume"] - v_mean) / v_std

            # Get last 5 days
            recent = df.tail(5)
            for _, row in recent.iterrows():
                date_str = str(row.get("date", ""))[:10]
                if not date_str:
                    continue
                if sector not in sector_date_data:
                    sector_date_data[sector] = {}
                if date_str not in sector_date_data[sector]:
                    sector_date_data[sector][date_str] = {"rets": [], "deliv_zs": [], "vol_zs": []}

                ret = _safe_float(row.get("ret_1d"))
                dz = _safe_float(row.get("deliv_z"))
                vz = _safe_float(row.get("vol_z"))
                if ret is not None:
                    sector_date_data[sector][date_str]["rets"].append(ret)
                if dz is not None:
                    sector_date_data[sector][date_str]["deliv_zs"].append(dz)
                if vz is not None:
                    sector_date_data[sector][date_str]["vol_zs"].append(vz)

        except Exception as e:
            log.debug(f"Error processing {parquet_file.name}: {e}")

    # Store sector_daily
    count = 0
    for sector, dates in sector_date_data.items():
        for date_str, metrics in dates.items():
            if not metrics["rets"]:
                continue
            values = {
                "sector": sector,
                "trade_date": date_str,
                "avg_return": sum(metrics["rets"]) / len(metrics["rets"]),
                "avg_deliv_z": (sum(metrics["deliv_zs"]) / len(metrics["deliv_zs"])) if metrics["deliv_zs"] else None,
                "avg_volume_z": (sum(metrics["vol_zs"]) / len(metrics["vol_zs"])) if metrics["vol_zs"] else None,
                "net_fii": None,  # Will be populated from institutional data
                "net_dii": None,
                "stock_count": len(metrics["rets"]),
                "updated_at": datetime.utcnow(),
            }
            cols = ", ".join(values.keys())
            phs = ", ".join(f":{k}" for k in values)
            updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k not in ("sector", "trade_date"))
            sql = sa.text(
                f"INSERT INTO sector_daily ({cols}) VALUES ({phs}) "
                f"ON CONFLICT (sector, trade_date) DO UPDATE SET {updates}"
            )
            with engine.begin() as conn:
                conn.execute(sql, values)
            count += 1

    return count


def get_universe_symbols(engine) -> list[str]:
    """Get all NSE symbols."""
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text(
                "SELECT DISTINCT symbol FROM cached_signals WHERE exchange = 'NSE' ORDER BY symbol"
            ))
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Ingest sector classification")
    parser.add_argument("--symbol", help="Single symbol")
    parser.add_argument("--symbols", nargs="+", help="List of symbols")
    parser.add_argument("--refresh", action="store_true", help="Force refresh all")
    parser.add_argument("--compute-daily", action="store_true", help="Compute sector daily aggregates")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    engine = get_pg_engine()
    start = time.time()

    # ── Sector Map ──
    if args.compute_daily:
        log.info("Computing sector daily aggregates...")
        count = compute_sector_daily(engine)
        log.info(f"  {count} sector-day records stored")
        return

    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        symbols = get_universe_symbols(engine)

    log.info(f"Building sector map for {len(symbols)} symbols...")
    success = 0
    failed = 0

    for i, symbol in enumerate(symbols):
        try:
            # Check if already mapped (unless refresh)
            if not args.refresh:
                with engine.connect() as conn:
                    existing = conn.execute(
                        sa.text("SELECT sector FROM sector_map WHERE symbol = :s"),
                        {"s": symbol}
                    ).fetchone()
                    if existing and existing[0]:
                        success += 1
                        continue

            data = fetch_sector(symbol)
            if data:
                upsert_sector_map(engine, symbol, data)
                success += 1
            else:
                failed += 1

            if (i + 1) % args.batch_size == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log.info(f"  [{i+1}/{len(symbols)}] success={success} failed={failed} rate={rate:.1f}/s")
                time.sleep(args.sleep)

        except KeyboardInterrupt:
            log.info("Interrupted.")
            break
        except Exception as e:
            log.warning(f"Error processing {symbol}: {e}")
            failed += 1

    # Compute sector daily
    log.info("\nComputing sector daily aggregates...")
    count = compute_sector_daily(engine)
    log.info(f"  {count} sector-day records stored")

    elapsed = time.time() - start
    log.info(f"\nDone in {elapsed:.1f}s: {success} success, {failed} failed")


if __name__ == "__main__":
    main()
