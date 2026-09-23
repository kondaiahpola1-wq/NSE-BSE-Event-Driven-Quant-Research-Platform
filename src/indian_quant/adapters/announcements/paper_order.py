from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from indian_quant.adapters.announcements.models import Signal
from indian_quant.config.settings import UpstoxConfig

if TYPE_CHECKING:
    from indian_quant.adapters.upstox.execution import UpstoxExecutionClient


class PaperOrderExecutor:
    """Places paper (sandbox) orders via Upstox sandbox API.

    Uses the platform's UpstoxExecutionClient so no real money is ever
    at risk; the sandbox endpoint physically cannot route live orders.
    """

    def __init__(
        self,
        config: UpstoxConfig | None = None,
        execution_client: "UpstoxExecutionClient | None" = None,
    ):
        self.config = config or UpstoxConfig()
        self._client = execution_client

    def _get_client(self) -> "UpstoxExecutionClient":
        if self._client is not None:
            return self._client
        from indian_quant.adapters.upstox.execution import UpstoxExecutionClient

        self._client = UpstoxExecutionClient(self.config)
        return self._client

    def place_order(
        self,
        signal: Signal,
        quantity: int,
        price: float,
        instrument_key: str = "",
        tag: str = "",
    ) -> dict:
        client = self._get_client()
        request = {
            "instrument_key": instrument_key or signal.exchange,
            "quantity": max(quantity, 1),
            "side": "BUY",
            "order_type": "LIMIT",
            "product": "D",
            "validity": "DAY",
            "limit_price": round(price, 2),
            "trigger_price": 0.0,
            "disclosed_quantity": 0,
            "is_amo": False,
            "slice": False,
            "tag": tag or f"announcement_alpha_{signal.symbol}",
        }
        resp = httpx.post(
            "https://api-sandbox.upstox.com/v3/order/place",
            headers=self._get_client()._headers(),
            json=request,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()