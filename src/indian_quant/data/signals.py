"""Pre-computed delivery signals and professional scores.

Source table: cached_signals (updated by cache_signals.py)
"""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_signals(
    exchange: str | None = None,
    signal_type: str | None = None,
    min_score: float | None = None,
    security_type: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Get cached signals with conviction scores.

    Returns DataFrame with 30+ columns including:
        symbol, close, deliv_pct, deliv_z, vol_z, rsi, macd,
        fundamental_score, institutional_score, professional_score,
        conviction_score, kelly_fraction, horizon, sector, pe, roe, ...

    Args:
        exchange: Filter by "NSE" or "BSE". None = all.
        signal_type: Filter by "BUY", "AVOID", etc. None = all.
        min_score: Minimum professional_score. None = no filter.
        security_type: Filter by "EQUITY", "ETF", "DEBT", "INDEX", "SME", "UNKNOWN". None = all.
        limit: Max rows to return. None = all.
    """
    engine = get_engine()
    query = "SELECT * FROM cached_signals WHERE 1=1"
    params = {}
    if exchange:
        query += " AND exchange = :exchange"
        params["exchange"] = exchange.upper()
    if signal_type:
        query += " AND signal_type = :signal_type"
        params["signal_type"] = signal_type.upper()
    if min_score is not None:
        query += " AND professional_score >= :min_score"
        params["min_score"] = min_score
    if security_type:
        query += " AND security_type = :security_type"
        params["security_type"] = security_type.upper()
    query += " ORDER BY professional_score DESC NULLS LAST"
    if limit:
        query += f" LIMIT {int(limit)}"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_stock_signal(symbol: str) -> dict | None:
    """Get signal data for a single stock.

    Returns dict with all cached signal columns, or None if not found.
    """
    engine = get_engine()
    result = engine.execute(
        sa.text("SELECT * FROM cached_signals WHERE symbol = :symbol"),
        {"symbol": symbol.upper()},
    )
    row = result.mappings().first()
    return dict(row) if row else None
