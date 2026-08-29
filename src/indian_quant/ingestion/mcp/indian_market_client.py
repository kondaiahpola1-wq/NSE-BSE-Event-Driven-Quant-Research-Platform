"""Indian Market MCP client via direct Python API.

Calls Indian Market MCP tool functions directly (no subprocess overhead).
68 tools: stocks, derivatives, indices, mutual funds, ETFs, commodities,
currency, IPOs, bonds, market data, technicals, screener, news, financials,
candlestick patterns, shareholding, MF analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class IndianMarketError(RuntimeError):
    pass


class IndianMarketClient:
    def __init__(self) -> None:
        from indian_market_mcp.server import mcp
        self._tools = mcp._tool_manager._tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._tools:
            raise IndianMarketError(f"unknown tool: {name}")
        try:
            result = self._tools[name].fn(**(arguments or {}))
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return result
            return result
        except Exception as exc:
            raise IndianMarketError(f"tool {name} failed: {exc}") from exc

    def close(self) -> None:
        pass


def get_market_cap(symbol: str) -> float | None:
    try:
        client = IndianMarketClient()
        result = client.call_tool("get_company_profile", {"symbol": symbol})
        return result.get("market_cap")
    except Exception:
        return None


def get_shareholding(symbol: str) -> dict[str, Any] | None:
    try:
        client = IndianMarketClient()
        return client.call_tool("get_shareholding_pattern", {"symbol": symbol})
    except Exception:
        return None
