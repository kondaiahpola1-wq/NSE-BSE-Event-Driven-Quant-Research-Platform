"""PostgreSQL-backed metadata store for paper signals and suggestions.

Replaces SQLite-based MetadataStore for portfolio operations.
All other metadata (instruments, jobs, runs) stays in SQLite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa


def _to_float(val):
    """Convert Decimal/numeric to float for JSON serialization."""
    if isinstance(val, Decimal):
        return float(val) if val else None
    return val


def _clean_row(d: dict) -> dict:
    """Clean a row dict — convert Decimals to floats."""
    return {k: _to_float(v) for k, v in d.items()}


class PgMetadataStore:
    """PostgreSQL-backed store for paper_signals + daily_suggestions."""

    def __init__(self, engine: sa.engine.Engine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass  # engine manages connections

    # ── Paper Signals ──

    def open_papers(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT * FROM paper_signals WHERE status = 'OPEN'")
            ).mappings().fetchall()
            return [_clean_row(dict(r)) for r in rows]

    def record_paper_signal(self, *, symbol: str, close_at_signal: float, qty: int,
                            horizon_days: int, stop_pct: float, segment: str | None = None,
                            side: str = "BUY", note: str | None = None,
                            entry_date: str | None = None,
                            position_value: float = 0.0,
                            risk_amount: float = 0.0,
                            horizon_label: str = "10d",
                            capital_allocated: float = 0.0,
                            conviction_score: float = 0.0,
                            kelly_fraction: float = 0.0) -> int:
        values = {
            "created_at": datetime.now(UTC).isoformat(),
            "symbol": symbol,
            "segment": segment,
            "side": side,
            "close_at_signal": close_at_signal,
            "qty": qty,
            "horizon_days": horizon_days,
            "stop_pct": stop_pct,
            "status": "OPEN",
            "entry_date": entry_date,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "horizon_label": horizon_label,
            "capital_allocated": capital_allocated,
            "conviction_score": conviction_score,
            "kelly_fraction": kelly_fraction,
            "note": note,
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO paper_signals ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.scalar()

    def settle_paper_signal(self, paper_id: int, *, exit_date: str, exit_close: float,
                            realized_net_bps: float, note: str | None = None,
                            exit_reason: str = "HORIZON",
                            days_held: int = 0, return_pct: float = 0.0,
                            return_bps: float = 0.0,
                            max_drawdown_bps: float = 0.0,
                            peak_return_bps: float = 0.0) -> dict:
        values = {
            "id": paper_id,
            "exit_date": exit_date,
            "exit_close": exit_close,
            "realized_net_bps": realized_net_bps,
            "status": "SETTLED",
            "note": note,
            "exit_reason": exit_reason,
            "days_held": days_held,
            "return_pct": return_pct,
            "return_bps": return_bps,
            "max_drawdown_bps": max_drawdown_bps,
            "peak_return_bps": peak_return_bps,
        }
        sql = sa.text("""
            UPDATE paper_signals SET
                exit_date = :exit_date, exit_close = :exit_close,
                realized_net_bps = :realized_net_bps, status = :status,
                note = COALESCE(:note, note), exit_reason = :exit_reason,
                days_held = :days_held, return_pct = :return_pct,
                return_bps = :return_bps, max_drawdown_bps = :max_drawdown_bps,
                peak_return_bps = :peak_return_bps
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            row = result.mappings().fetchone()
            return _clean_row(dict(row)) if row else {}

    def papers_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = conn.execute(sa.text("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
                    SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END) as settled,
                    SUM(CASE WHEN status = 'OPEN' THEN position_value ELSE 0 END) as total_position_value,
                    SUM(CASE WHEN status = 'OPEN' THEN risk_amount ELSE 0 END) as total_risk,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'SETTLED' AND realized_net_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END), 0) as hit_rate,
                    AVG(CASE WHEN status = 'SETTLED' THEN days_held END) as avg_days_held
                FROM paper_signals
            """)).mappings().fetchone()
            return _clean_row(dict(r)) if r else {}

    def paper_trades_by_horizon(self) -> dict[str, dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.text("""
                SELECT
                    horizon_label,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END) as settled,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'SETTLED' AND realized_net_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END), 0) as hit_rate,
                    AVG(CASE WHEN status = 'SETTLED' THEN days_held END) as avg_days_held
                FROM paper_signals GROUP BY horizon_label
            """)).mappings().fetchall()
            return {r["horizon_label"]: _clean_row(dict(r)) for r in rows}

    def portfolio_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = conn.execute(sa.text("""
                SELECT
                    SUM(CASE WHEN status = 'OPEN' THEN position_value ELSE 0 END) as total_position_value,
                    SUM(CASE WHEN status = 'OPEN' THEN risk_amount ELSE 0 END) as total_risk,
                    COUNT(CASE WHEN status = 'OPEN' THEN 1 END) as open_positions,
                    COUNT(CASE WHEN status = 'SETTLED' THEN 1 END) as total_trades,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps
                FROM paper_signals
            """)).mappings().fetchone()
            return _clean_row(dict(r)) if r else {}

    def trade_log(self, *, horizon: str | None = None, status: str | None = None,
                  limit: int = 50) -> list[dict]:
        conditions = []
        params = {}
        if horizon:
            conditions.append("horizon_label = :horizon")
            params["horizon"] = horizon
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params["limit"] = limit

        with self._engine.connect() as conn:
            rows = conn.execute(sa.text(
                f"SELECT * FROM paper_signals {where} ORDER BY created_at DESC LIMIT :limit"
            ), params).mappings().fetchall()
            return [_clean_row(dict(r)) for r in rows]

    # ── Daily Suggestions ──

    def suggestions_by_date(self, date: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT * FROM daily_suggestions WHERE suggestion_date = :d ORDER BY symbol"),
                {"d": date}
            ).mappings().fetchall()
            return [_clean_row(dict(r)) for r in rows]

    def record_daily_suggestion(self, *, suggestion_date: str, symbol: str,
                                segment: str | None = None,
                                signal_type: str | None = None,
                                direction: str = "BUY",
                                close_at_signal: float = 0.0,
                                deliv_pct: float | None = None,
                                deliv_z: float | None = None,
                                vol_z: float | None = None,
                                entry_zone_low: float = 0.0,
                                entry_zone_high: float = 0.0,
                                stop_loss: float = 0.0,
                                target_price: float = 0.0,
                                horizon_days: int = 10,
                                qty_suggested: int = 0,
                                note: str | None = None,
                                position_value: float = 0.0,
                                risk_amount: float = 0.0,
                                horizon_label: str = "10d",
                                capital_allocated: float = 0.0,
                                conviction_score: float = 0.0,
                                kelly_fraction: float = 0.0) -> int:
        values = {
            "suggestion_date": suggestion_date,
            "symbol": symbol,
            "segment": segment,
            "signal_type": signal_type,
            "direction": direction,
            "close_at_signal": close_at_signal,
            "deliv_pct": deliv_pct,
            "deliv_z": deliv_z,
            "vol_z": vol_z,
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "horizon_days": horizon_days,
            "qty_suggested": qty_suggested,
            "status": "PENDING",
            "note": note,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "horizon_label": horizon_label,
            "capital_allocated": capital_allocated,
            "conviction_score": conviction_score,
            "kelly_fraction": kelly_fraction,
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO daily_suggestions ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.scalar()

    def pending_suggestions(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT * FROM daily_suggestions WHERE status = 'PENDING' ORDER BY suggestion_date, symbol")
            ).mappings().fetchall()
            return [_clean_row(dict(r)) for r in rows]

    def settle_daily_suggestion(self, suggestion_id: int, *, actual_exit_date: str,
                                actual_exit_close: float,
                                actual_return_bps: float,
                                note: str | None = None) -> dict:
        values = {
            "id": suggestion_id,
            "actual_exit_date": actual_exit_date,
            "actual_exit_close": actual_exit_close,
            "actual_return_bps": actual_return_bps,
            "status": "REALIZED",
            "note": note,
        }
        sql = sa.text("""
            UPDATE daily_suggestions SET
                actual_exit_date = :actual_exit_date,
                actual_exit_close = :actual_exit_close,
                actual_return_bps = :actual_return_bps,
                status = :status,
                note = COALESCE(:note, note)
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            row = result.mappings().fetchone()
            return _clean_row(dict(row)) if row else {}

    def suggestions_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = conn.execute(sa.text("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END) as realized,
                    AVG(CASE WHEN status = 'REALIZED' THEN actual_return_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'REALIZED' AND actual_return_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END), 0) as hit_rate
                FROM daily_suggestions
            """)).mappings().fetchone()
            return _clean_row(dict(r)) if r else {}

    def suggestions_by_horizon(self) -> dict[str, dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.text("""
                SELECT
                    horizon_label,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END) as realized,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                    AVG(CASE WHEN status = 'REALIZED' THEN actual_return_bps END) as avg_net_bps
                FROM daily_suggestions GROUP BY horizon_label
            """)).mappings().fetchall()
            return {r["horizon_label"]: _clean_row(dict(r)) for r in rows}
