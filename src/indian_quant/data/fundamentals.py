"""Fundamental data access — PE, ROE, debt ratios, company profiles.

Source tables: key_ratios, company_profile (updated by pipeline.fundamentals)
"""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_fundamentals(symbol: str | None = None) -> dict | pd.DataFrame:
    """Get fundamental data from PostgreSQL.

    Args:
        symbol: Specific stock (e.g., "RELIANCE"). None = all stocks.

    Returns:
        dict for single symbol, DataFrame for all.
    """
    engine = get_engine()
    query = "SELECT * FROM key_ratios"
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


def get_company_profile(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get company name, sector, industry, description.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        dict for single symbol, DataFrame for all, None if not found.
    """
    engine = get_engine()
    query = "SELECT * FROM company_profile"
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


def get_market_cap(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get market cap data from key_ratios.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        dict with symbol, market_cap, pe_trailing, etc.
    """
    engine = get_engine()
    query = "SELECT symbol, market_cap, pe_trailing, price_to_book FROM key_ratios WHERE market_cap IS NOT NULL"
    params = {}
    if symbol:
        query += " AND symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY market_cap DESC"

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df
