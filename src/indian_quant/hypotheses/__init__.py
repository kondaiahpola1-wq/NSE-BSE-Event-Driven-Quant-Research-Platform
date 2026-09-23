"""Hypothesis framework — registry, base class, and built-in hypotheses."""

from __future__ import annotations

from indian_quant.hypotheses.base import BaseHypothesis
from indian_quant.hypotheses.registry import HypothesisRegistry

# Import all hypothesis classes to trigger @register_hypothesis
from indian_quant.hypotheses.delivery_momentum import DeliveryMomentum  # noqa: F401
from indian_quant.hypotheses.circuit_breakout import CircuitBreakout  # noqa: F401
from indian_quant.hypotheses.surveillance_recovery import SurveillanceRecovery  # noqa: F401
from indian_quant.hypotheses.announcement_alpha import AnnouncementAlpha  # noqa: F401

__all__ = ["BaseHypothesis", "HypothesisRegistry"]
