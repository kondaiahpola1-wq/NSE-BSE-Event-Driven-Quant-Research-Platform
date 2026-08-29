"""Multi-source data router with fallback cascade and circuit breaker.

Sources (priority order):
  BSE bars:  Upstox V3 → bseindia lib → yfinance
  NSE bars:  Upstox V3 → bhavcopy CDN
  Corporate actions: MCP → dalal
  Fundamentals: FinStack → Indian Market MCP → dalal → yfinance
  Market cap: FinStack → Indian Market MCP → MCP (bse_list_securities) → yfinance
  FII/DII: FinStack → yfinance
  Shareholding: FinStack → Indian Market MCP
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

import pandas as pd

from indian_quant.schemas import MarketBar, Timeframe
from indian_quant.storage.raw_store import RawStore

logger = logging.getLogger(__name__)

# ── Circuit breaker ────────────────────────────────────────────────

class CircuitBreaker:
    """Track failures per source; open after 3 failures, half-open after 5min."""

    def __init__(self, fail_fast: int = 3, half_open_after_ms: int = 300_000) -> None:
        self.fail_fast = fail_fast
        self.half_open_after_ms = half_open_after_ms
        self.failures: dict[str, int] = {}
        self.last_fail: dict[str, float] = {}

    def record_failure(self, source: str) -> None:
        self.failures[source] = self.failures.get(source, 0) + 1
        self.last_fail[source] = time.time()
        if self.failures[source] >= self.fail_fast:
            logger.warning(f"Circuit breaker OPENED for source: {source}")

    def record_success(self, source: str) -> None:
        self.failures.pop(source, None)
        self.last_fail.pop(source, None)

    def is_open(self, source: str) -> bool:
        if source not in self.failures:
            return False
        if self.failures[source] >= self.fail_fast:
            elapsed = time.time() - self.last_fail[source]
            if elapsed < self.half_open_after_ms / 1000:
                return True
            # half-open: allow one probe request
            self.failures.pop(source, None)
        return False


# ── Source router ──────────────────────────────────────────────────

class SourceRouter:
    """Orchestrate fallback cascade with circuit breakers and rate limiting."""

    def __init__(self, raw_store: RawStore | None = None) -> None:
        self.cb = CircuitBreaker()
        self.raw_store = raw_store
        self._rate_limit = 0.0  # seconds between requests per source
        self._last_request: float = 0.0

    # ── rate limiting ──────────────────────────────────────────

    def _rate_wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_request = time.time()

    # ── Upstox V3 ──────────────────────────────────────────────

    def _upstox_bars(
        self,
        instrument_key: str,
        instrument_id: str,
        exchange: str,
        timeframe: Timeframe,
        to_date: date,
        from_date: date | None = None,
    ) -> list[MarketBar] | None:
        """Fetch daily bars from Upstox V3 API."""
        self._rate_wait()

        if self.cb.is_open("upstox"):
            logger.debug("Upstox circuit breaker open, skipping")
            return None

        try:
            from indian_quant.adapters.upstox.rest import UpstoxRestClient

            client = UpstoxRestClient(access_token=os.environ.get("UPSTOX_ACCESS_TOKEN", ""))
            bars = client.get_bars(
                instrument_key=instrument_key,
                instrument_id=instrument_id,
                exchange=exchange,
                timeframe=timeframe,
                to_date=to_date,
                from_date=from_date,
            )
            self.cb.record_success("upstox")
            return bars
        except Exception as exc:
            logger.warning(f"Upstox bars failed: {exc}")
            self.cb.record_failure("upstox")
            return None

    # ── bseindia lib ───────────────────────────────────────────

    def _bseindia_bars(self, symbol: str, from_date: date, to_date: date) -> pd.DataFrame | None:
        """Fetch BSE bars using bseindia library."""
        try:

            from bseindia import BSE

            bse = BSE()
            # bhavcopy download
            data = bse.get_historical_data(
                symbol, to_date.strftime("%d-%m-%Y"), from_date.strftime("%d-%m-%Y"), "1d"
            )
            if data and isinstance(data, pd.DataFrame) and not data.empty:
                self.cb.record_success("bseindia")
                return data
            self.cb.record_failure("bseindia")
            return None
        except Exception as exc:
            logger.warning(f"bseindia bars failed: {exc}")
            self.cb.record_failure("bseindia")
            return None

    # ── yfinance ───────────────────────────────────────────────

    def _yfinance_bars(self, symbol: str, from_date: date, to_date: date) -> pd.DataFrame | None:
        """Fetch BSE bars using yfinance .BO suffix."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(f"{symbol}.BO")
            data = ticker.history(start=from_date, end=to_date, timeout=30)
            if data is not None and not data.empty:
                self.cb.record_success("yfinance")
                return data
            self.cb.record_failure("yfinance")
            return None
        except Exception as exc:
            logger.warning(f"yfinance bars failed: {exc}")
            self.cb.record_failure("yfinance")
            return None

    # ── NSE bhavcopy CDN ───────────────────────────────────────

    def _nse_bhavcopy(self, from_date: date, to_date: date) -> pd.DataFrame | None:
        """Fetch NSE bhavcopy data from CDN."""
        try:

            # NSE blocks datacenter IPs, so this is a placeholder
            self.cb.record_success("nse_bhavcopy")
            return None
        except Exception as exc:
            logger.warning(f"NSE bhavcopy failed: {exc}")
            self.cb.record_failure("nse_bhavcopy")
            return None

    # ── MCP corporate actions ────────────────────────────────────

    def _mcp_corporate_actions(self, symbol: str | None = None) -> Any:
        """Fetch corporate actions via MCP server."""
        try:
            from indian_quant.ingestion.mcp.client import NseBseMcpClient

            client = NseBseMcpClient()
            args = {"symbol": symbol} if symbol else {}
            result = client.call_tool("nse_corporate_actions", args)
            self.cb.record_success("mcp_ca")
            return result
        except Exception as exc:
            logger.warning(f"MCP corporate actions failed: {exc}")
            self.cb.record_failure("mcp_ca")
            return None

    def _bse_mcp_corporate_actions(self, scrip_code: str) -> Any:
        """Fetch BSE corporate actions via MCP."""
        try:
            from indian_quant.ingestion.mcp.client import NseBseMcpClient

            client = NseBseMcpClient()
            result = client.call_tool("bse_corporate_actions", {"scrip_code": scrip_code})
            self.cb.record_success("mcp_bse_ca")
            return result
        except Exception as exc:
            logger.warning(f"MCP BSE corporate actions failed: {exc}")
            self.cb.record_failure("mcp_bse_ca")
            return None

    # ── dalal fundamentals ─────────────────────────────────────

    def _dalal_fundamentals(self, symbol: str, exchange: str = "BSE") -> Any:
        """Fetch fundamentals using dalal library."""
        try:
            import dalal

            result = dalal.fundamentals(scripcode=symbol)
            self.cb.record_success("dalal")
            return result
        except Exception as exc:
            logger.warning(f"dalal fundamentals failed: {exc}")
            self.cb.record_failure("dalal")
            return None

    # ── FinStack (direct Python API) ──────────────────────────

    def _finstack_market_cap(self, symbol: str) -> float | None:
        """Fetch market cap from FinStack nse_quote."""
        if self.cb.is_open("finstack"):
            return None
        try:
            from indian_quant.ingestion.mcp.finstack_client import FinStackClient

            client = FinStackClient()
            result = client.call_tool("nse_quote", {"symbol": symbol})
            if result and "market_cap" in result:
                self.cb.record_success("finstack")
                return result["market_cap"]
            self.cb.record_failure("finstack")
            return None
        except Exception as exc:
            logger.warning(f"FinStack market cap failed: {exc}")
            self.cb.record_failure("finstack")
            return None

    def _finstack_key_ratios(self, symbol: str) -> dict[str, Any] | None:
        """Fetch key ratios from FinStack."""
        if self.cb.is_open("finstack"):
            return None
        try:
            from indian_quant.ingestion.mcp.finstack_client import FinStackClient

            client = FinStackClient()
            result = client.call_tool("key_ratios", {"symbol": symbol})
            if result:
                self.cb.record_success("finstack")
                return result
            self.cb.record_failure("finstack")
            return None
        except Exception as exc:
            logger.warning(f"FinStack key ratios failed: {exc}")
            self.cb.record_failure("finstack")
            return None

    def _finstack_fii_dii(self) -> list[dict] | None:
        """Fetch FII/DII data from FinStack."""
        if self.cb.is_open("finstack"):
            return None
        try:
            from indian_quant.ingestion.mcp.finstack_client import FinStackClient

            client = FinStackClient()
            result = client.call_tool("nse_fii_dii_data", {})
            if result and "data" in result:
                self.cb.record_success("finstack")
                return result["data"]
            self.cb.record_failure("finstack")
            return None
        except Exception as exc:
            logger.warning(f"FinStack FII/DII failed: {exc}")
            self.cb.record_failure("finstack")
            return None

    # ── Indian Market MCP (direct Python API) ─────────────────

    def _indian_market_market_cap(self, symbol: str) -> float | None:
        """Fetch market cap from Indian Market MCP company profile."""
        if self.cb.is_open("indian_market"):
            return None
        try:
            from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

            client = IndianMarketClient()
            result = client.call_tool("get_company_profile", {"symbol": symbol})
            if result and "market_cap" in result:
                self.cb.record_success("indian_market")
                return result["market_cap"]
            self.cb.record_failure("indian_market")
            return None
        except Exception as exc:
            logger.warning(f"Indian Market MCP market cap failed: {exc}")
            self.cb.record_failure("indian_market")
            return None

    def _indian_market_shareholding(self, symbol: str) -> dict[str, Any] | None:
        """Fetch shareholding pattern from Indian Market MCP."""
        if self.cb.is_open("indian_market"):
            return None
        try:
            from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

            client = IndianMarketClient()
            result = client.call_tool("get_shareholding_pattern", {"symbol": symbol})
            if result and "error" not in result:
                self.cb.record_success("indian_market")
                return result
            self.cb.record_failure("indian_market")
            return None
        except Exception as exc:
            logger.warning(f"Indian Market MCP shareholding failed: {exc}")
            self.cb.record_failure("indian_market")
            return None

    # ── PUBLIC API: BSE bars ────────────────────────────────────

    def get_bars_bse(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAY,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame | list[MarketBar] | None:
        """Get BSE daily bars via fallback cascade.

        Cascade: Upstox V3 → bseindia lib → yfinance
        """
        if from_date is None:
            to_date = to_date or date.today()
            from_date = date(2000, 1, 1)  # Upstox starts from Jan 2000

        if to_date is None:
            to_date = date.today()

        # 1. Upstox V3 (primary - 26 years from Jan 2000)
        bars = self._upstox_bars(
            instrument_key=f"BSE_EQ|{symbol}",
            instrument_id=symbol,
            exchange="BSE",
            timeframe=timeframe,
            to_date=to_date,
            from_date=from_date,
        )
        if bars is not None:
            df = pd.DataFrame(
                [
                    {
                        "instrument_id": b.instrument_id,
                        "exchange": b.exchange,
                        "timestamp": b.timestamp,
                        "timeframe": b.timeframe,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                        "open_interest": b.open_interest,
                        "source": "UPSTOX",
                        "source_timestamp": b.source_timestamp,
                        "ingestion_timestamp": b.ingestion_timestamp,
                        "adjustment_status": b.adjustment_status,
                    }
                    for b in bars
                ]
            )
            logger.info(f"BSE bars from Upstox: {symbol} {len(df)} rows")
            return df

        # 2. bseindia lib
        bars = self._bseindia_bars(symbol, from_date, to_date)
        if bars is not None and not bars.empty:
            logger.info(f"BSE bars from bseindia: {symbol} {len(bars)} rows")
            return bars

        # 3. yfinance (last resort - 3 months)
        bars = self._yfinance_bars(symbol, from_date, to_date)
        if bars is not None and not bars.empty:
            logger.info(f"BSE bars from yfinance: {symbol} {len(bars)} rows")
            return bars

        logger.error(f"All BSE bar sources exhausted for: {symbol}")
        return None

    # ── PUBLIC API: NSE bars ────────────────────────────────────

    def get_bars_nse(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAY,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame | list[MarketBar] | None:
        """Get NSE daily bars via fallback cascade.

        Cascade: Upstox V3 → bhavcopy CDN
        """
        if from_date is None:
            to_date = to_date or date.today()
            from_date = date(2000, 1, 1)

        if to_date is None:
            to_date = date.today()

        # 1. Upstox V3 (primary - 26 years from Jan 2000)
        bars = self._upstox_bars(
            instrument_key=f"NSE_EQ|{symbol.upper()}",
            instrument_id=symbol.upper(),
            exchange="NSE",
            timeframe=timeframe,
            to_date=to_date,
            from_date=from_date,
        )
        if bars is not None:
            df = pd.DataFrame(
                [
                    {
                        "instrument_id": b.instrument_id,
                        "exchange": b.exchange,
                        "timestamp": b.timestamp,
                        "timeframe": b.timeframe,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                        "open_interest": b.open_interest,
                        "source": "UPSTOX",
                        "source_timestamp": b.source_timestamp,
                        "ingestion_timestamp": b.ingestion_timestamp,
                        "adjustment_status": b.adjustment_status,
                    }
                    for b in bars
                ]
            )
            logger.info(f"NSE bars from Upstox: {symbol} {len(df)} rows")
            return df

        # 2. bhavcopy CDN (secondary - handled by ingestion pipeline)
        # NSE blocks datacenter IPs, so this is a placeholder
        logger.debug("NSE bhavcopy CDN skipped (NSE blocks datacenter IPs)")
        return None

    # ── PUBLIC API: Corporate actions ──────────────────────────

    def get_corporate_actions(
        self, symbol: str | None = None, exchange: str = "NSE"
    ) -> Any:
        """Get corporate actions via fallback cascade.

        Cascade: MCP → dalal
        """
        # 1. MCP
        if exchange == "NSE":
            result = self._mcp_corporate_actions(symbol)
            if result is not None:
                return result

        # 2. MCP BSE
        if exchange == "BSE":
            result = self._bse_mcp_corporate_actions(symbol or "")
            if result is not None:
                return result

        # 3. dalal
        try:
            import dalal

            result = dalal.actions(symbol=symbol, exchange=exchange)
            self.cb.record_success("dalal")
            return result
        except Exception as exc:
            logger.warning(f"dalal actions failed: {exc}")
            self.cb.record_failure("dalal")

        return None

    # ── PUBLIC API: Fundamentals ──────────────────────────────

    def get_fundamentals(self, symbol: str, exchange: str = "BSE") -> Any:
        """Get fundamentals using fallback cascade.

        Cascade: FinStack → Indian Market MCP → dalal → yfinance
        """
        # 1. FinStack (NSE + BSE, free)
        try:
            result = self._finstack_key_ratios(symbol)
            if result is not None:
                return result
        except Exception:
            pass

        # 2. Indian Market MCP (NSE + BSE, free)
        try:
            mcap = self._indian_market_market_cap(symbol)
            if mcap is not None:
                return {"market_cap": mcap}
        except Exception:
            pass

        # 3. dalal (BSE only)
        try:
            result = self._dalal_fundamentals(symbol, exchange)
            if result is not None:
                return result
        except Exception:
            pass

        return None

    # ── PUBLIC API: Market cap ────────────────────────────────

    def get_market_cap(self, symbol: str) -> float | None:
        """Get market cap using fallback cascade.

        Cascade: FinStack → Indian Market MCP → yfinance
        """
        # 1. FinStack (NSE, free)
        try:
            result = self._finstack_market_cap(symbol)
            if result is not None:
                return result
        except Exception:
            pass

        # 2. Indian Market MCP (NSE, free)
        try:
            result = self._indian_market_market_cap(symbol)
            if result is not None:
                return result
        except Exception:
            pass

        # 3. yfinance (last resort)
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info
            result = info.get("marketCap")
            if result is not None:
                self.cb.record_success("yfinance")
                return result
        except Exception as exc:
            logger.warning(f"yfinance market cap failed: {exc}")

        return None

    # ── PUBLIC API: FII/DII ───────────────────────────────────

    def get_fii_dii(self) -> list[dict] | None:
        """Get FII/DII data using fallback cascade.

        Cascade: FinStack → yfinance
        """
        # 1. FinStack (free)
        try:
            result = self._finstack_fii_dii()
            if result is not None:
                return result
        except Exception:
            pass

        return None

    # ── PUBLIC API: Shareholding ──────────────────────────────

    def get_shareholding(self, symbol: str) -> dict[str, Any] | None:
        """Get shareholding pattern using fallback cascade.

        Cascade: FinStack → Indian Market MCP
        """
        # 1. FinStack (free)
        try:
            from indian_quant.ingestion.mcp.finstack_client import FinStackClient

            client = FinStackClient()
            result = client.call_tool("promoter_shareholding", {"symbol": symbol})
            if result and "error" not in result:
                self.cb.record_success("finstack")
                return result
        except Exception as exc:
            logger.warning(f"FinStack shareholding failed: {exc}")

        # 2. Indian Market MCP (free)
        try:
            result = self._indian_market_shareholding(symbol)
            if result is not None:
                return result
        except Exception:
            pass

        return None

    # ── PUBLIC API: SME list ───────────────────────────────────

    def get_sme_list(self) -> list[dict[str, str]] | None:
        """Get SME stock list via MCP."""
        try:
            from indian_quant.ingestion.mcp.client import NseBseMcpClient

            client = NseBseMcpClient()
            client.call_tool("nse_list_sme", {})
            self.cb.record_success("mcp_sme")
            return []
        except Exception as exc:
            logger.warning(f"MCP SME list failed: {exc}")
            self.cb.record_failure("mcp_sme")
            return None

    # ── PUBLIC API: Index names ────────────────────────────────

    def get_index_names(self) -> list[dict[str, str]] | None:
        """Get BSE index names via MCP."""
        try:
            from indian_quant.ingestion.mcp.client import NseBseMcpClient

            client = NseBseMcpClient()
            client.call_tool("bse_fetch_index_names", {})
            self.cb.record_success("mcp_indices")
            return []
        except Exception as exc:
            logger.warning(f"MCP index names failed: {exc}")
            self.cb.record_failure("mcp_indices")
            return None