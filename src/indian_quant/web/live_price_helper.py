"""Shared live price helper for all web routes.

Provides a single function to fetch live prices for any list of symbols,
with error handling and fallback. Used by every route that displays stock prices.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def fetch_live_prices(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch live prices for a list of symbols. Returns {} on failure.

    Returns {SYMBOL: {last_price, open, high, low, close, volume, net_change, ...}}
    """
    if not symbols:
        return {}
    try:
        from indian_quant.web.live_prices import LivePriceService
        lps = LivePriceService()
        return lps.get_live_prices(list(set(symbols)))
    except Exception as e:
        log.warning("Live prices fetch failed for %d symbols: %s", len(symbols), e)
        return {}


def get_live_price_map(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices, return simple {SYMBOL: last_price} map."""
    raw = fetch_live_prices(symbols)
    return {sym: data.get("last_price", 0) for sym, data in raw.items() if data.get("last_price")}
