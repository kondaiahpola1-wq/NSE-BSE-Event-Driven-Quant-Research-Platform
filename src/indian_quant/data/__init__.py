"""Indian Quant Data Access Layer.

Public API for reading data from the pipeline. All functions are read-only
queries against PostgreSQL and parquet files — no side effects.

Usage:
    from indian_quant.data import get_fundamentals, get_signals, get_bars

    # Get fundamentals for a stock
    data = get_fundamentals("RELIANCE")

    # Get all trading signals
    signals = get_signals(min_score=0.45)

    # Get historical bars
    bars = get_bars("RELIANCE", days=30)
"""

from indian_quant.data.bars import get_bars, get_delivery
from indian_quant.data.concall import (
    get_concall_calendar,
    get_concall_details,
    get_concall_peers,
    get_concall_ratios,
)
from indian_quant.data.fundamentals import (
    get_company_profile,
    get_fundamentals,
    get_market_cap,
)
from indian_quant.data.institutional import (
    get_bulk_deals,
    get_fii_dii,
    get_insider_trades,
    get_promoter_pledge,
    get_shareholding,
)
from indian_quant.data.risk import get_portfolio_risk, get_stock_risk
from indian_quant.data.sectors import get_sector_daily, get_sectors
from indian_quant.data.signals import get_stock_signal, get_signals

__all__ = [
    "get_bars",
    "get_bulk_deals",
    "get_company_profile",
    "get_concall_calendar",
    "get_concall_details",
    "get_concall_peers",
    "get_concall_ratios",
    "get_delivery",
    "get_fii_dii",
    "get_fundamentals",
    "get_insider_trades",
    "get_market_cap",
    "get_portfolio_risk",
    "get_promoter_pledge",
    "get_sector_daily",
    "get_sectors",
    "get_shareholding",
    "get_signals",
    "get_stock_risk",
    "get_stock_signal",
]
