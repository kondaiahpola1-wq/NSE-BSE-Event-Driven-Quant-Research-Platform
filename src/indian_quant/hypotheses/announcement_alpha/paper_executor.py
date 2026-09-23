from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from indian_quant.adapters.upstox.execution import UpstoxExecutionClient


class AnnouncementAlphaExecutor:
    """Places paper (sandbox) orders using the platform's UpstoxExecutionClient.

    The sandbox endpoint physically cannot route live orders, so no real
    money is ever at risk.
    """

    def __init__(self, execution_client: "UpstoxExecutionClient | None" = None):
        self._client = execution_client

    def _get_client(self) -> "UpstoxExecutionClient":
        if self._client is not None:
            return self._client
        from indian_quant.config.settings import UpstoxConfig
        from indian_quant.adapters.upstox.execution import UpstoxExecutionClient

        config = UpstoxConfig(sandbox=True)
        self._client = UpstoxExecutionClient(config)
        return self._client

    def place_order(self, symbol: str, exchange: str, instrument_key: str, quantity: int, price: float, tag: str = "") -> dict:
        client = self._get_client()
        from indian_quant.adapters.upstox.execution import SandboxOrderRequest, OrderSide, OrderType, ProductType, Validity

        request = SandboxOrderRequest(
            instrument_key=instrument_key,
            quantity=max(quantity, 1),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            product=ProductType.DELIVERY,
            validity=Validity.DAY,
            limit_price=round(price, 2),
            trigger_price=0.0,
            tag=tag or f"announcement_alpha_{symbol}",
        )
        import asyncio
        report = asyncio.run(client.submit_order(request))
        return {"order_id": report.order_id, "status": report.status, "symbol": symbol}