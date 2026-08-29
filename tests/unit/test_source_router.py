"""Fault-injection tests for SourceRouter circuit breaker and fallback cascade."""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from indian_quant.ingestion.router import CircuitBreaker, SourceRouter


class TestCircuitBreaker:
    def test_opens_after_three_failures(self):
        cb = CircuitBreaker(fail_fast=3)
        cb.record_failure("src")
        cb.record_failure("src")
        assert not cb.is_open("src")
        cb.record_failure("src")
        assert cb.is_open("src")

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(fail_fast=3)
        cb.record_failure("src")
        cb.record_failure("src")
        cb.record_success("src")
        assert not cb.is_open("src")

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(fail_fast=2, half_open_after_ms=100)
        cb.record_failure("src")
        cb.record_failure("src")
        assert cb.is_open("src")
        time.sleep(0.15)
        assert not cb.is_open("src")

    def test_different_sources_independent(self):
        cb = CircuitBreaker(fail_fast=2)
        cb.record_failure("a")
        cb.record_failure("a")
        assert cb.is_open("a")
        assert not cb.is_open("b")


class TestSourceRouterFaultInjection:
    def test_bse_cascades_to_yfinance_on_upstox_failure(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_bseindia_bars", return_value=None),
            patch.object(
                router,
                "_yfinance_bars",
                return_value=pd.DataFrame({"close": [100]}),
            ) as mock_yf,
        ):
            result = router.get_bars_bse(
                "TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2)
            )
            assert result is not None
            mock_yf.assert_called_once()

    def test_nse_cascades_to_yfinance_on_all_failures(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_nse_bhavcopy", return_value=None),
            patch.object(
                router,
                "_yfinance_bars",
                return_value=pd.DataFrame({"close": [100]}),
            ) as mock_yf,
        ):
            result = router.get_bars_nse(
                "TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2)
            )
            assert result is not None
            mock_yf.assert_called_once_with(
                "TEST", date(2025, 1, 1), date(2025, 1, 2), suffix=".NS"
            )

    def test_returns_none_when_all_sources_exhausted(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_bseindia_bars", return_value=None),
            patch.object(router, "_yfinance_bars", return_value=None),
        ):
            result = router.get_bars_bse(
                "TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2)
            )
            assert result is None

    def test_circuit_breaker_skips_source_when_open(self):
        router = SourceRouter()
        router.cb.record_failure("upstox")
        router.cb.record_failure("upstox")
        router.cb.record_failure("upstox")
        # With CB open, _upstox_bars returns None before importing the client.
        # get_bars_nse should cascade past Upstox to bhavcopy and yfinance.
        with (
            patch.object(router, "_nse_bhavcopy", return_value=None),
            patch.object(
                router, "_yfinance_bars", return_value=pd.DataFrame({"c": [1]})
            ) as mock_yf,
        ):
            result = router.get_bars_nse(
                "TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2)
            )
            assert result is not None
            mock_yf.assert_called_once()

    def test_fundamentals_cascade(self):
        router = SourceRouter()
        with (
            patch.object(router, "_finstack_key_ratios", return_value=None),
            patch.object(router, "_indian_market_market_cap", return_value=None),
            patch.object(
                router,
                "_dalal_fundamentals",
                return_value={"pe": 25.0},
            ) as mock_dalal,
        ):
            result = router.get_fundamentals("TEST")
            assert result == {"pe": 25.0}
            mock_dalal.assert_called_once()

    def test_market_cap_cascade(self):
        router = SourceRouter()
        with (
            patch.object(router, "_finstack_market_cap", return_value=None),
            patch.object(router, "_indian_market_market_cap", return_value=None),
            patch("yfinance.Ticker") as mock_ticker_cls,
        ):
            mock_ticker = MagicMock()
            mock_ticker.info = {"marketCap": 1_000_000_000}
            mock_ticker_cls.return_value = mock_ticker
            result = router.get_market_cap("TEST")
            assert result == 1_000_000_000
