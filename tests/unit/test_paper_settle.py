"""Tests for paper trading settle logic with intraday stop detection."""

import sys
from pathlib import Path

import pandas as pd
import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.storage.pg_metadata import PgMetadataStore
from indian_quant.config.connections import get_engine

_TEST_SYMBOLS = ("SETHOR", "SETSTOP", "SETSHORT", "SETSUM", "SETOPEN", "SETJOURNAL")


@pytest.fixture
def pg_store():
    engine = get_engine()
    store = PgMetadataStore(engine)
    yield store
    with engine.begin() as conn:
        for sym in _TEST_SYMBOLS:
            conn.execute(sa.text(
                "DELETE FROM trade_journal WHERE symbol = :sym"), {"sym": sym})
            conn.execute(sa.text(
                "DELETE FROM paper_signals WHERE symbol = :sym"), {"sym": sym})
    store.close()


class TestPaperSettle:
    def test_settle_horizon(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETHOR", close_at_signal=100.0, qty=10,
            horizon_days=10, stop_pct=0.07, segment="EQ")
        result = pg_store.settle_paper_signal(
            pid, exit_date="2026-09-10", exit_close=105.0,
            realized_net_bps=393.0, exit_reason="HORIZON",
            days_held=7, return_pct=5.0, return_bps=500.0)
        assert result["status"] == "SETTLED"
        assert result["exit_reason"] == "HORIZON"

    def test_settle_stop(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETSTOP", close_at_signal=100.0, qty=10,
            horizon_days=10, stop_pct=0.07, segment="EQ")
        # Stop at 93 (7% below 100)
        result = pg_store.settle_paper_signal(
            pid, exit_date="2026-09-05", exit_close=93.0,
            realized_net_bps=-807.0, exit_reason="STOP",
            days_held=3, return_pct=-7.0, return_bps=-700.0)
        assert result["status"] == "SETTLED"
        assert result["exit_reason"] == "STOP"
        assert result["realized_net_bps"] < 0

    def test_settle_short_side(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETSHORT", close_at_signal=100.0, qty=5,
            horizon_days=5, stop_pct=0.05, segment="EQ",
            side="SELL")
        result = pg_store.settle_paper_signal(
            pid, exit_date="2026-09-03", exit_close=98.0,
            realized_net_bps=150.0, exit_reason="HORIZON",
            days_held=2, return_pct=2.0, return_bps=200.0)
        assert result["status"] == "SETTLED"

    def test_papers_summary(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETSUM", close_at_signal=100.0, qty=10,
            horizon_days=10, stop_pct=0.07, segment="EQ")
        pg_store.settle_paper_signal(
            pid, exit_date="2026-09-10", exit_close=105.0,
            realized_net_bps=393.0, exit_reason="HORIZON",
            days_held=7, return_pct=5.0, return_bps=500.0)
        summary = pg_store.papers_summary()
        assert summary["settled"] >= 1

    def test_open_papers(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETOPEN", close_at_signal=100.0, qty=10,
            horizon_days=10, stop_pct=0.07, segment="EQ")
        open_papers = pg_store.open_papers()
        assert any(p["id"] == pid for p in open_papers)

    def test_journal_auto_recorded_on_exit(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="SETJOURNAL", close_at_signal=100.0, qty=10,
            horizon_days=10, stop_pct=0.07, segment="EQ")
        pg_store.journal_record_on_entry(
            paper_trade_id=pid, symbol="SETJOURNAL",
            entry_date="2026-09-01", entry_price=100.0,
            entry_signal="dz_hi_up")

        pg_store.settle_paper_signal(
            pid, exit_date="2026-09-10", exit_close=105.0,
            realized_net_bps=393.0, exit_reason="HORIZON",
            days_held=7, return_pct=5.0, return_bps=500.0)

        pg_store.journal_record_on_exit(
            pid, exit_date="2026-09-10", exit_price=105.0,
            exit_reason="HORIZON", days_held=7,
            return_pct=5.0, return_bps=500.0, net_bps=393.0)

        entry = pg_store.journal_entry(pid)
        assert entry is not None
        assert entry["exit_price"] == 105.0
