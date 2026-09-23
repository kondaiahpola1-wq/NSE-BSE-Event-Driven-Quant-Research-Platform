"""Announcement Alpha hypothesis — integrates with platform hypothesis registry."""
from __future__ import annotations

from indian_quant.hypotheses.base import BaseHypothesis, Signal
from indian_quant.hypotheses.registry import register_hypothesis


@register_hypothesis
class AnnouncementAlpha(BaseHypothesis):
    """Buy on BSE announcement signals using paper/sandbox orders."""

    name = "announcement_alpha"
    description = "BSE announcement alpha signals → paper order placement"
    max_positions = 7
    default_stop_pct = 0.05
    default_horizon_days = 5
    price_min = 50.0
    price_max = 5000.0
    min_turnover = 10_000_000.0
    market_cap_min = 500.0
    market_cap_max = 50000.0

    def compute_signals(self, df, *, signal_date=None, announcements=None):
        return []

    def compute_signals_batch(self, frames, *, signal_date=None):
        return []


def register_announcement_alpha() -> None:
    """No-op; @register_hypothesis on the class handles registration."""
    pass


__all__ = ["AnnouncementAlpha", "register_announcement_alpha"]