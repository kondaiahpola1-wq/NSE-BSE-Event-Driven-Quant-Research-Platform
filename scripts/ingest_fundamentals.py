#!/usr/bin/env python3
"""Ingest fundamental data for all stocks into PostgreSQL.

Data sources (cascade): FinStack key_ratios → Indian Market MCP → yfinance
Stores: company_profile, key_ratios, quarterly_financials

Usage:
    python scripts/ingest_fundamentals.py                    # Full universe
    python scripts/ingest_fundamentals.py --recent           # Only recently traded
    python scripts/ingest_fundamentals.py --symbol RELIANCE  # Single stock
    python scripts/ingest_fundamentals.py --batch-size 50 --sleep 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from indian_quant.web.prod_config import get_pg_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_fundamentals")


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default  # NaN check
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=None):
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _fetch_finstack(symbol: str) -> dict | None:
    """Fetch from FinStack key_ratios tool."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient
        client = FinStackClient()
        return client.call_tool("key_ratios", {"symbol": symbol})
    except Exception as e:
        log.debug(f"FinStack failed for {symbol}: {e}")
        return None


def _fetch_indian_market(symbol: str) -> dict | None:
    """Fetch from Indian Market MCP get_key_ratios."""
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient
        client = IndianMarketClient()
        return client.call_tool("get_key_ratios", {"symbol": symbol})
    except Exception as e:
        log.debug(f"Indian Market MCP failed for {symbol}: {e}")
        return None


def _fetch_company_profile(symbol: str) -> dict | None:
    """Fetch company profile for sector/industry."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient
        client = FinStackClient()
        return client.call_tool("company_profile", {"symbol": symbol})
    except Exception:
        pass
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient
        client = IndianMarketClient()
        return client.call_tool("get_company_profile", {"symbol": symbol})
    except Exception:
        pass
    return None


def _yf_ticker(symbol: str):
    """Try yfinance with .NS then .BO suffix."""
    import yfinance as yf
    for suffix in (".NS", ".BO"):
        try:
            t = yf.Ticker(f"{symbol}{suffix}")
            info = t.info
            if info and info.get("trailingPE"):
                return t, info
        except Exception:
            continue
    return None, None


def _fetch_yfinance(symbol: str) -> dict | None:
    """Fetch from yfinance as last resort."""
    try:
        ticker, info = _yf_ticker(symbol)
        if not ticker or not info:
            return None
        return {
            "source": "yfinance",
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "enterprise_value": info.get("enterpriseValue"),
            "market_cap": info.get("marketCap"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "gross_margin": info.get("grossMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_q_growth": info.get("earningsQuarterlyGrowth"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "free_cash_flow": info.get("freeCashflow"),
            "eps_trailing": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "book_value": info.get("bookValue"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "beta": info.get("beta"),
            "w52_high": info.get("fiftyTwoWeekHigh"),
            "w52_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "company_name": info.get("longName"),
            "employees": info.get("fullTimeEmployees"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary", "")[:500],
        }
    except Exception as e:
        log.debug(f"yfinance failed for {symbol}: {e}")
        return None


def fetch_fundamentals(symbol: str) -> dict | None:
    """Fetch fundamentals with cascade: FinStack → Indian Market MCP → yfinance."""
    # 1. FinStack
    data = _fetch_finstack(symbol)
    if data and isinstance(data, dict) and data.get("valuation"):
        # FinStack returns nested structure
        val = data.get("valuation", {})
        prof = data.get("profitability", {})
        grow = data.get("growth", {})
        health = data.get("financial_health", {})
        psh = data.get("per_share", {})
        div = data.get("dividend", {})
        return {
            "source": "finstack",
            "pe_trailing": _safe_float(val.get("pe_trailing")),
            "pe_forward": _safe_float(val.get("pe_forward")),
            "peg_ratio": _safe_float(val.get("peg_ratio")),
            "price_to_book": _safe_float(val.get("price_to_book")),
            "price_to_sales": _safe_float(val.get("price_to_sales")),
            "ev_to_ebitda": _safe_float(val.get("ev_to_ebitda")),
            "ev_to_revenue": _safe_float(val.get("ev_to_revenue")),
            "enterprise_value": _safe_int(val.get("enterprise_value")),
            "market_cap": _safe_int(val.get("market_cap")),
            "profit_margin": _safe_float(prof.get("profit_margin")),
            "operating_margin": _safe_float(prof.get("operating_margin")),
            "gross_margin": _safe_float(prof.get("gross_margin")),
            "ebitda_margin": _safe_float(prof.get("ebitda_margin")),
            "roe": _safe_float(prof.get("roe")),
            "roa": _safe_float(prof.get("roa")),
            "revenue_growth": _safe_float(grow.get("revenue_growth")),
            "earnings_growth": _safe_float(grow.get("earnings_growth")),
            "earnings_q_growth": _safe_float(grow.get("earnings_quarterly_growth")),
            "debt_to_equity": _safe_float(health.get("debt_to_equity")),
            "current_ratio": _safe_float(health.get("current_ratio")),
            "quick_ratio": _safe_float(health.get("quick_ratio")),
            "total_debt": _safe_int(health.get("total_debt")),
            "total_cash": _safe_int(health.get("total_cash")),
            "free_cash_flow": _safe_int(health.get("free_cash_flow")),
            "eps_trailing": _safe_float(psh.get("eps_trailing")),
            "eps_forward": _safe_float(psh.get("eps_forward")),
            "book_value": _safe_float(psh.get("book_value")),
            "revenue_per_share": _safe_float(psh.get("revenue_per_share")),
            "dividend_rate": _safe_float(div.get("dividend_rate")),
            "dividend_yield": _safe_float(div.get("dividend_yield")),
            "payout_ratio": _safe_float(div.get("payout_ratio")),
            "ex_div_date": div.get("ex_dividend_date"),
        }

    # 2. Indian Market MCP (flat structure)
    data = _fetch_indian_market(symbol)
    if data and isinstance(data, dict) and data.get("pe_trailing"):
        return {
            "source": "indian_market_mcp",
            "pe_trailing": _safe_float(data.get("pe_trailing")),
            "pe_forward": _safe_float(data.get("pe_forward")),
            "peg_ratio": _safe_float(data.get("peg")),
            "price_to_book": _safe_float(data.get("pb")),
            "price_to_sales": _safe_float(data.get("ps")),
            "ev_to_ebitda": _safe_float(data.get("ev_ebitda")),
            "ev_to_revenue": _safe_float(data.get("ev_to_revenue")),
            "enterprise_value": _safe_int(data.get("enterprise_value_cr")),
            "market_cap": _safe_int(data.get("market_cap_cr")),
            "profit_margin": _safe_float(data.get("profit_margin")),
            "operating_margin": _safe_float(data.get("operating_margin")),
            "gross_margin": _safe_float(data.get("gross_margin")),
            "roe": _safe_float(data.get("roe")),
            "roa": _safe_float(data.get("roa")),
            "revenue_growth": _safe_float(data.get("revenue_growth")),
            "earnings_growth": _safe_float(data.get("earnings_growth")),
            "debt_to_equity": _safe_float(data.get("debt_to_equity")),
            "current_ratio": _safe_float(data.get("current_ratio")),
            "quick_ratio": _safe_float(data.get("quick_ratio")),
            "eps_trailing": _safe_float(data.get("eps_trailing")),
            "eps_forward": _safe_float(data.get("eps_forward")),
            "book_value": _safe_float(data.get("book_value")),
            "dividend_yield": _safe_float(data.get("dividend_yield")),
            "payout_ratio": _safe_float(data.get("payout_ratio")),
            "beta": _safe_float(data.get("beta")),
            "w52_high": _safe_float(data.get("52w_high")),
            "w52_low": _safe_float(data.get("52w_low")),
            "avg_volume": _safe_int(data.get("avg_volume")),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "company_name": data.get("company"),
        }

    # 3. yfinance fallback
    data = _fetch_yfinance(symbol)
    if data:
        return data

    return None


def fetch_profile(symbol: str) -> dict | None:
    """Fetch company profile (sector, industry, name)."""
    data = _fetch_company_profile(symbol)
    if data and isinstance(data, dict):
        return {
            "company_name": data.get("company") or data.get("longName"),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "description": (data.get("description") or data.get("longBusinessSummary", ""))[:500],
            "website": data.get("website"),
            "employees": _safe_int(data.get("employees")),
            "shares_outstanding": _safe_int(data.get("shares_outstanding")),
            "float_shares": _safe_int(data.get("float_shares")),
        }
    # Fallback: yfinance
    try:
        import yfinance as yf
        ticker, info = _yf_ticker(symbol)
        if not ticker or not info:
            return None
        return {
            "company_name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": (info.get("longBusinessSummary", ""))[:500],
            "website": info.get("website"),
            "employees": _safe_int(info.get("fullTimeEmployees")),
            "shares_outstanding": _safe_int(info.get("sharesOutstanding")),
            "float_shares": _safe_int(info.get("floatShares")),
        }
    except Exception:
        return None


def upsert_key_ratios(engine, symbol: str, data: dict) -> None:
    """Insert or update key_ratios table."""
    cols = [
        "pe_trailing", "pe_forward", "peg_ratio", "price_to_book", "price_to_sales",
        "ev_to_ebitda", "ev_to_revenue", "enterprise_value", "market_cap",
        "profit_margin", "operating_margin", "gross_margin", "ebitda_margin",
        "roe", "roa", "revenue_growth", "earnings_growth", "earnings_q_growth",
        "debt_to_equity", "current_ratio", "quick_ratio",
        "total_debt", "total_cash", "free_cash_flow",
        "eps_trailing", "eps_forward", "book_value", "revenue_per_share",
        "dividend_rate", "dividend_yield", "payout_ratio", "ex_div_date",
        "beta", "w52_high", "w52_low", "avg_volume",
    ]
    values = {c: data.get(c) for c in cols}
    values["symbol"] = symbol
    values["updated_at"] = datetime.utcnow()

    placeholders = ", ".join(f":{k}" for k in values)
    columns = ", ".join(values.keys())
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")

    sql = sa.text(
        f"INSERT INTO key_ratios ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {update_clause}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def upsert_company_profile(engine, symbol: str, data: dict) -> None:
    """Insert or update company_profile table."""
    values = {
        "symbol": symbol,
        "exchange": "NSE",
        "company_name": data.get("company_name"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "description": data.get("description"),
        "website": data.get("website"),
        "employees": data.get("employees"),
        "shares_outstanding": data.get("shares_outstanding"),
        "float_shares": data.get("float_shares"),
        "updated_at": datetime.utcnow(),
    }

    placeholders = ", ".join(f":{k}" for k in values)
    columns = ", ".join(values.keys())
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")

    sql = sa.text(
        f"INSERT INTO company_profile ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {update_clause}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def get_universe_symbols(engine) -> list[str]:
    """Get all NSE symbols from cached_signals or instruments."""
    with engine.connect() as conn:
        # Try cached_signals first
        try:
            result = conn.execute(sa.text(
                "SELECT DISTINCT symbol FROM cached_signals WHERE exchange = 'NSE' ORDER BY symbol"
            ))
            symbols = [r[0] for r in result.fetchall()]
            if symbols:
                return symbols
        except Exception:
            pass
        # Fall back to instruments
        try:
            result = conn.execute(sa.text(
                "SELECT symbol FROM instruments WHERE exchange = 'NSE' ORDER BY symbol"
            ))
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Ingest fundamental data into PostgreSQL")
    parser.add_argument("--symbol", help="Single symbol to ingest")
    parser.add_argument("--symbols", nargs="+", help="List of symbols to ingest")
    parser.add_argument("--recent", action="store_true", help="Only recently traded stocks (from cached_signals)")
    parser.add_argument("--batch-size", type=int, default=100, help="Symbols per batch")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between batches")
    parser.add_argument("--profile-only", action="store_true", help="Only fetch company profiles (sector/industry)")
    args = parser.parse_args()

    engine = get_pg_engine()

    # Get symbols
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        symbols = get_universe_symbols(engine)
        if not symbols:
            log.error("No symbols found. Run cache_signals.py first.")
            return

    log.info(f"Ingesting fundamentals for {len(symbols)} symbols")
    start = time.time()
    success = 0
    failed = 0
    skipped = 0

    for i, symbol in enumerate(symbols):
        try:
            # Fetch and store company profile
            if not args.profile_only:
                profile = fetch_profile(symbol)
                if profile:
                    upsert_company_profile(engine, symbol, profile)
                    success += 1
                else:
                    skipped += 1

                # Fetch and store key ratios
                ratios = fetch_fundamentals(symbol)
                if ratios:
                    upsert_key_ratios(engine, symbol, ratios)
            else:
                # Profile only
                profile = fetch_profile(symbol)
                if profile:
                    upsert_company_profile(engine, symbol, profile)
                    success += 1
                else:
                    skipped += 1

            # Progress
            if (i + 1) % args.batch_size == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(symbols) - i - 1) / rate if rate > 0 else 0
                log.info(f"  [{i+1}/{len(symbols)}] success={success} failed={failed} skipped={skipped} "
                         f"rate={rate:.1f}/s ETA={eta:.0f}s")
                time.sleep(args.sleep)

        except KeyboardInterrupt:
            log.info("Interrupted. Saving progress...")
            break
        except Exception as e:
            log.warning(f"Error processing {symbol}: {e}")
            failed += 1

    elapsed = time.time() - start
    log.info(f"\nDone in {elapsed:.1f}s: {success} success, {failed} failed, {skipped} skipped "
             f"out of {len(symbols)} symbols")


if __name__ == "__main__":
    main()
