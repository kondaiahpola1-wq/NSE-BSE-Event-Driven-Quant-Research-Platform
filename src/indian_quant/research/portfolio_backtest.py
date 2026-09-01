"""Portfolio-level strategy backtest over delivery-lake frames.

Unlike the sweep (which sums every firing independently), this simulates a
real desk: finite slots, risk-based sizing, cluster-first entries,
horizon/stop exits, measured round-trip costs, daily equity curve.
Close-basis fills v1 (10-day holds; passive-fill refinement possible once
the B4 tick tape provides rates).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import date as Date
from pathlib import Path

import pandas as pd

from indian_quant.features.delivery import (
    SIGNAL_NAMES,
    add_features,
    cluster_entry_mask,
    conviction_score,
    horizon_fit,
    HORIZON_DAYS,
    HORIZON_STOP,
    prepare_frame,
    signal_mask,
)
from indian_quant.portfolio.kelly import kelly_fraction, kelly_position


@dataclass(frozen=True)
class StrategyConfig:
    signal: str = "dz_hi_up"
    price_min: float = 20.0
    price_max: float = 100.0
    min_turnover: float = 10_000_000.0
    hold_days: int = 10
    stop_pct: float = 0.07
    max_positions: int = 8
    capital: float = 25_000.0
    risk_pct: float = 1.0
    cost_bps: float = 107.0
    cluster_entries: bool = True
    z_min: float = 2.0
    use_conviction: bool = False
    use_kelly: bool = False


@dataclass
class Trade:
    symbol: str
    segment: str
    entry_date: Date
    entry_px: float
    qty: int
    exit_date: Date | None
    exit_px: float | None
    gross_bps: float | None
    net_bps: float | None
    reason: str
    days_held: int


@dataclass
class BacktestResult:
    config: StrategyConfig
    trades: list[Trade]
    equity_curve: list[tuple[Date, float]]
    summary: dict


def load_frames(delivery_dir: Path | str, min_rows: int = 40) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for path in sorted(Path(delivery_dir).glob("*.parquet")):
        raw = pd.read_parquet(path)
        prepared = prepare_frame(raw, min_rows=min_rows)
        if prepared is None or "segment" not in prepared.columns:
            continue
        featured = add_features(prepared)
        if featured.empty or "symbol" not in featured.columns:
            continue
        frames.append(featured)
    return frames


def _prepare_tables(frames: list[pd.DataFrame], config: StrategyConfig):
    """Return (tables, fires): date-indexed frames + firing masks."""
    tables: dict[str, pd.DataFrame] = {}
    fires: dict[str, pd.Series] = {}
    for f in frames:
        sym = str(f["symbol"].iloc[-1])
        table = f.copy()
        if "volume" in table.columns:
            table["turnover"] = table["close"] * table["volume"].fillna(0)
        else:
            table["turnover"] = 0.0
        table = table.set_index("date")

        raw_mask = signal_mask(table.reset_index(), config.signal,
                               z_min=config.z_min)
        if config.cluster_entries:
            raw_mask = cluster_entry_mask(pd.Series(raw_mask.values))
        fires[sym] = pd.Series(raw_mask.values, index=table.index)
        tables[sym] = table
    return tables, fires


def run_portfolio(frames: list[pd.DataFrame],
                  config: StrategyConfig) -> BacktestResult:
    if config.signal not in SIGNAL_NAMES:
        raise KeyError(f"unknown signal: {config.signal}")

    tables, fires = _prepare_tables(frames, config)
    all_dates = sorted({d for t in tables.values() for d in t.index})

    open_pos: dict[str, dict] = {}
    trades: list[Trade] = []
    cash = config.capital
    equity_curve: list[tuple[Date, float]] = []
    risk_rupees = config.capital * config.risk_pct / 100.0
    half_cost = config.cost_bps / 2 / 10_000  # fraction charged per side

    # Running stats for Kelly sizing
    kelly_win_rate = 0.43
    kelly_avg_win = 250.0
    kelly_avg_loss = 165.0

    def close_position(sym: str, day: Date, px: float, reason: str) -> None:
        nonlocal cash, kelly_win_rate, kelly_avg_win, kelly_avg_loss
        pos = open_pos.pop(sym)
        gross = (px / pos["entry_px"] - 1.0) * 10_000
        net = gross - config.cost_bps
        cash += pos["qty"] * px - pos["qty"] * pos["entry_px"] * half_cost * 1
        trades.append(Trade(
            symbol=sym, segment=pos["segment"], entry_date=pos["entry_date"],
            entry_px=pos["entry_px"], qty=pos["qty"], exit_date=day, exit_px=px,
            gross_bps=round(gross, 2), net_bps=round(net, 2),
            reason=reason, days_held=pos["days_held"],
        ))
        # Update Kelly stats
        if net > 0:
            kelly_avg_win = (kelly_avg_win + net) / 2
        else:
            kelly_avg_loss = (kelly_avg_loss + abs(net)) / 2
        closed = [t for t in trades if t.net_bps is not None]
        wins = sum(1 for t in closed if t.net_bps > 0)
        kelly_win_rate = wins / len(closed) if closed else 0.43

    for day in all_dates:
        # ---------- exits (per-position horizon and stop)
        for sym in list(open_pos):
            table = tables[sym]
            if day not in table.index:
                continue
            pos = open_pos[sym]
            pos["days_held"] += 1
            close = float(table.loc[day, "close"])
            if close <= pos["entry_px"] * (1 - pos["stop_pct"]):
                close_position(sym, day, close, "STOP")
            elif pos["days_held"] >= pos["hold_days"]:
                close_position(sym, day, close, "HORIZON")

        # ---------- mark to market
        market_value = 0.0
        for sym, pos in open_pos.items():
            table = tables[sym]
            px = float(table.loc[day, "close"]) if day in table.index \
                else pos["entry_px"]
            market_value += pos["qty"] * px
        equity_curve.append((day, cash + market_value))

        # ---------- entries
        if len(open_pos) >= config.max_positions:
            continue
        candidates: list[tuple[float, str, float, int, float]] = []
        for sym, table in tables.items():
            if sym in open_pos or day not in table.index:
                continue
            if not bool(fires[sym].get(day, False)):
                continue
            row = table.loc[day]
            close = float(row["close"])
            if not (config.price_min <= close <= config.price_max):
                continue
            if float(row.get("turnover", 0)) < config.min_turnover:
                continue
            z = row.get("deliv_z")
            if config.signal.startswith("dz_"):
                if pd.isna(z):
                    continue

            if config.use_conviction:
                score = conviction_score(row)
                candidates.append((score, sym, close, config.hold_days, config.stop_pct))
            else:
                candidates.append((float(z) if not pd.isna(z) else 0.0,
                                   sym, close, config.hold_days, config.stop_pct))

        candidates.sort(key=lambda c: (-c[0], c[1]))
        for score, sym, close, hold_d, stop in candidates:
            if len(open_pos) >= config.max_positions:
                break
            row = tables[sym].loc[day]

            if config.use_kelly:
                kf = kelly_fraction(kelly_win_rate, kelly_avg_win,
                                    kelly_avg_loss)
                qty = kelly_position(config.capital, config.risk_pct,
                                     close, stop, kf)
            else:
                stop_dist = close * config.stop_pct
                qty_by_risk = int(risk_rupees // stop_dist) if stop_dist > 0 else 0
                qty_by_capital = int((config.capital * 0.30) // close)
                qty = max(0, min(qty_by_risk, qty_by_capital))

            if qty < 1:
                continue
            open_pos[sym] = {
                "entry_date": day, "entry_px": close, "qty": qty,
                "segment": str(row.get("segment", "EQ")), "days_held": 0,
                "hold_days": hold_d, "stop_pct": stop, "conviction": score,
            }
            cash -= qty * close * half_cost

    # force-close leftovers at last known price
    for sym in list(open_pos):
        table = tables[sym]
        last_day = table.index.max()
        last_px = float(table.loc[last_day, "close"]) if last_day is not None \
            else open_pos[sym]["entry_px"]
        close_position(sym, last_day or date.today(), last_px, "DATA_END")

    summary = summarize(trades, equity_curve)
    return BacktestResult(config=config, trades=trades,
                          equity_curve=equity_curve, summary=summary)


def summarize(trades: list[Trade], equity_curve: list[tuple[Date, float]]) -> dict:
    closed = [t for t in trades if t.net_bps is not None]
    n = len(closed)
    nets = [float(t.net_bps or 0.0) for t in closed]
    mean_net = sum(nets) / n if n else None
    eq_values = [v for _, v in equity_curve]
    peak = float("-inf")
    max_dd = 0.0
    for v in eq_values:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak > 0 else 0.0)
    wins = sum(1 for t in closed if (t.net_bps is not None and t.net_bps > 0))
    reasons: dict[str, int] = {}
    for t in closed:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {
        "n_trades": n,
        "net_expectancy_bps": round(mean_net, 2) if mean_net is not None else None,
        "win_rate": round(wins / n, 3) if n else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "final_equity": round(eq_values[-1], 2) if eq_values else None,
        "avg_holding_days": round(
            sum(t.days_held for t in closed) / n, 1) if n else None,
        "exit_reasons": reasons,
    }


__all__ = [
    "BacktestResult",
    "StrategyConfig",
    "Trade",
    "load_frames",
    "run_portfolio",
    "summarize",
    "conviction_score",
    "horizon_fit",
]
