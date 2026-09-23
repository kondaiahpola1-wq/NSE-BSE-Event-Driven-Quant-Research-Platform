"""Portfolio and per-stock risk metrics.

Source tables: portfolio_risk, stock_risk (updated by pipeline.risk)
"""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_portfolio_risk() -> dict | None:
    """Get latest portfolio-level risk metrics.

    Returns dict with:
        snapshot_date, total_value, var_95, var_99, cvar_95,
        portfolio_beta, max_drawdown, sharpe_ratio, concentration_hhi,
        n_positions, n_sectors, top_sector_pct
    """
    engine = get_engine()
    result = engine.execute(
        sa.text("SELECT * FROM portfolio_risk ORDER BY snapshot_date DESC LIMIT 1")
    )
    row = result.mappings().first()
    return dict(row) if row else None


def get_stock_risk(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get per-stock risk metrics.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, beta, vol_30d, vol_annual, var_95,
        max_drawdown_1y, correlation_nifty, avg_daily_volume, impact_cost.
    """
    engine = get_engine()
    query = "SELECT * FROM stock_risk"
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
