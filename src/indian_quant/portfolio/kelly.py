"""Kelly criterion position sizing for conviction-scored signals.

Half-Kelly is used by default for safety margin.
"""

from __future__ import annotations


def kelly_fraction(win_rate: float, avg_win_bps: float,
                   avg_loss_bps: float, fraction: float = 0.5) -> float:
    """Compute fractional Kelly bet size.

    f* = (p * b - q) / b
    where p = win_rate, b = avg_win / avg_loss, q = 1 - p.

    Args:
        win_rate: historical win probability (0-1)
        avg_win_bps: average winning trade in bps
        avg_loss_bps: average losing trade in bps (positive value)
        fraction: Kelly fraction (0.5 = half-Kelly)

    Returns:
        Fraction of capital to risk per trade (0.0 if inputs invalid).
    """
    if avg_loss_bps <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win_bps / avg_loss_bps
    q = 1.0 - win_rate
    full_kelly = (win_rate * b - q) / b
    if full_kelly <= 0:
        return 0.0
    return round(full_kelly * fraction, 6)


def kelly_position(capital: float, risk_pct: float, entry_px: float,
                   stop_pct: float, kelly_frac: float) -> int:
    """Convert Kelly fraction to share count.

    Position size = (capital × kelly_frac × risk_pct) / (entry_px × stop_pct)

    Args:
        capital: total portfolio capital in INR
        risk_pct: max risk per trade as fraction (e.g. 0.02 = 2%)
        entry_px: expected entry price
        stop_pct: stop-loss as fraction (e.g. 0.07 = 7%)
        kelly_frac: output from kelly_fraction()

    Returns:
        Number of shares (rounded down, min 1).
    """
    if entry_px <= 0 or stop_pct <= 0 or kelly_frac <= 0:
        return 1
    risk_amount = capital * kelly_frac * risk_pct
    per_share_risk = entry_px * stop_pct
    shares = int(risk_amount / per_share_risk)
    return max(shares, 1)


# Default parameters for Indian equities
DEFAULT_WIN_RATE = 0.43
DEFAULT_AVG_WIN_BPS = 250.0
DEFAULT_AVG_LOSS_BPS = 165.0
DEFAULT_KELLY_FRAC = 0.5
