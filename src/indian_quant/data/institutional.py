"""Institutional flow data — FII/DII, shareholding, bulk deals, insider trades.

Source tables: fii_dii_daily, shareholding_history, bulk_deals,
               insider_trades, promoter_pledge
               (updated by pipeline.institutional)
"""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_fii_dii(date: str | None = None) -> pd.DataFrame:
    """Get FII/DII daily flow data.

    Args:
        date: Specific date (YYYY-MM-DD). None = all dates.

    Returns:
        DataFrame with trade_date, fii_buy, fii_sell, fii_net, dii_buy, etc.
    """
    engine = get_engine()
    query = "SELECT * FROM fii_dii_daily"
    params = {}
    if date:
        query += " WHERE trade_date = :date"
        params["date"] = date
    query += " ORDER BY trade_date DESC"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_shareholding(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get shareholding pattern (promoter, FII, DII, public).

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, quarter, promoter_pct, fii_pct, dii_pct, public_pct.
    """
    engine = get_engine()
    query = "SELECT * FROM shareholding_history"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY symbol, quarter DESC"

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df


def get_bulk_deals(date: str | None = None) -> pd.DataFrame:
    """Get bulk deal transactions.

    Args:
        date: Specific date (YYYY-MM-DD). None = all dates.

    Returns:
        DataFrame with deal_date, symbol, client, deal_type, quantity, price, value.
    """
    engine = get_engine()
    query = "SELECT * FROM bulk_deals"
    params = {}
    if date:
        query += " WHERE deal_date = :date"
        params["date"] = date
    query += " ORDER BY deal_date DESC, symbol"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_insider_trades(symbol: str | None = None) -> pd.DataFrame:
    """Get insider trading activity.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, trade_date, insider_name, transaction_type, shares_traded.
    """
    engine = get_engine()
    query = "SELECT * FROM insider_trades"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY trade_date DESC"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_promoter_pledge(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get promoter pledge data.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, pledge_pct, risk_signal, qoq_change.
    """
    engine = get_engine()
    query = "SELECT * FROM promoter_pledge"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df
