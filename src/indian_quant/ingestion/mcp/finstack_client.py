"""FinStack MCP client via direct Python API.

Calls FinStack tool functions directly (no subprocess overhead).
Provides market cap, fundamentals, shareholding, FII/DII, and more.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FinStackError(RuntimeError):
    pass


def _load_tools():
    from finstack.tools.analytics import register_analytics_tools
    from finstack.tools.fundamentals import register_fundamental_tools
    from finstack.tools.indian import register_indian_tools
    from finstack.tools.market_intelligence import register_market_intelligence_tools
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("indian-quant-finstack")
    register_indian_tools(mcp)
    register_analytics_tools(mcp)
    register_fundamental_tools(mcp)
    register_market_intelligence_tools(mcp)
    return mcp._tool_manager._tools


class FinStackClient:
    def __init__(self) -> None:
        self._tools = _load_tools()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._tools:
            raise FinStackError(f"unknown tool: {name}")
        try:
            result = self._tools[name].fn(**(arguments or {}))
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return result
            return result
        except Exception as exc:
            raise FinStackError(f"tool {name} failed: {exc}") from exc

    def close(self) -> None:
        pass


# Convenience wrappers

def get_market_cap(symbol: str) -> float | None:
    try:
        client = FinStackClient()
        result = client.call_tool("nse_quote", {"symbol": symbol})
        return result.get("market_cap")
    except Exception:
        return None


def get_key_ratios(symbol: str) -> dict[str, Any] | None:
    try:
        client = FinStackClient()
        return client.call_tool("key_ratios", {"symbol": symbol})
    except Exception:
        return None


def get_fii_dii() -> list[dict] | None:
    try:
        client = FinStackClient()
        result = client.call_tool("nse_fii_dii_data", {})
        return result.get("data", [])
    except Exception:
        return None
