"""OHLCV bar data from parquet files.

Source: data/normalized/bars_1d/{exchange}/{symbol}.parquet
        data/normalized/delivery/{exchange}/{symbol}.parquet
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "normalized"


def get_bars(
    symbol: str,
    exchange: str = "NSE",
    timeframe: str = "1d",
    days: int | None = None,
) -> pd.DataFrame:
    """Get historical bars from normalized parquet.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE").
        exchange: "NSE" or "BSE".
        timeframe: "1d", "5m", "15m", etc.
        days: Last N days. None = all available.

    Returns:
        DataFrame with date, open, high, low, close, volume.
    """
    path = _DATA_ROOT / "bars_1d" / exchange / f"{symbol.upper()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No bar data for {symbol} on {exchange}: {path}")

    df = pd.read_parquet(path)
    if days and len(df) > days:
        df = df.tail(days)
    return df


def get_delivery(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    """Get delivery data from normalized parquet.

    Args:
        symbol: Stock symbol.
        exchange: "NSE" or "BSE".

    Returns:
        DataFrame with date, close, volume, deliv_qty, deliv_pct, etc.
    """
    path = _DATA_ROOT / "delivery" / exchange / f"{symbol.upper()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No delivery data for {symbol} on {exchange}: {path}")

    return pd.read_parquet(path)
