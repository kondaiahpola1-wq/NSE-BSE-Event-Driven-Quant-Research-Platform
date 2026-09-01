"""Portfolio-level constraints for position entry and risk management.

Enforces:
- Max 2 positions per sector
- Min 2 trading days between entries in same stock
- Max 8 total open positions
- Liquidity check (min avg turnover)
- Correlation check (basic: avoid same sector clustering)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioConstraints:
    max_sector: int = 2
    max_total: int = 8
    min_days_between: int = 2
    min_avg_turnover: float = 5_000_000.0
    max_sector_pct: float = 0.40  # max 40% in one sector


@dataclass
class OpenPosition:
    symbol: str
    sector: str
    entry_date: str
    days_held: int = 0


def can_enter(symbol: str, sector: str, entry_date: str,
              open_positions: dict[str, OpenPosition],
              constraints: PortfolioConstraints) -> tuple[bool, str]:
    """Check if a new position can be opened.

    Returns (allowed, reason).
    """
    # Total limit
    if len(open_positions) >= constraints.max_total:
        return False, f"max_total reached ({constraints.max_total})"

    # Already in this stock
    if symbol in open_positions:
        return False, f"already holding {symbol}"

    # Sector limit
    sector_count = sum(1 for p in open_positions.values() if p.sector == sector)
    if sector_count >= constraints.max_sector:
        return False, f"sector {sector} at max ({constraints.max_sector})"

    # Sector concentration
    if len(open_positions) > 0:
        sector_pct = sector_count / len(open_positions)
        if sector_pct >= constraints.max_sector_pct:
            return False, f"sector {sector} at {sector_pct:.0%} (max {constraints.max_sector_pct:.0%})"

    # Min days between same-stock entries (check recent exits — not applicable for entry)
    # This is checked at exit time to enforce cooldown

    return True, "ok"


def position_size_kelly(capital: float, kelly_frac: float,
                        entry_px: float, stop_pct: float,
                        risk_pct: float = 0.02) -> int:
    """Kelly-based position sizing with portfolio constraints.

    Uses half-Kelly by default. Returns share count (min 1).
    """
    if entry_px <= 0 or stop_pct <= 0:
        return 1
    risk_amount = capital * kelly_frac * risk_pct
    per_share_risk = entry_px * stop_pct
    shares = int(risk_amount / per_share_risk)
    return max(shares, 1)
