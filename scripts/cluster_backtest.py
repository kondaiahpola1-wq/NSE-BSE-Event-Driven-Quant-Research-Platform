"""Gate 1: cluster portfolio backtest on the real universe (dz_hi_up variant).

Usage:
    python scripts/cluster_backtest.py [--hold 10 --price-max 100 ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.research import ExperimentTracker
from indian_quant.research import portfolio_backtest as pb
from indian_quant.storage import MetadataStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate-1 cluster portfolio backtest")
    parser.add_argument("--signal", default="dz_hi_up")
    parser.add_argument("--hold", type=int, default=10)
    parser.add_argument("--stop-pct", type=float, default=0.07)
    parser.add_argument("--price-min", type=float, default=20.0)
    parser.add_argument("--price-max", type=float, default=100.0)
    parser.add_argument("--max-positions", type=int, default=8)
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--min-turnover", type=float, default=10_000_000.0)
    parser.add_argument("--no-cluster", action="store_true")
    parser.add_argument("--z-min", type=float, default=2.0)
    parser.add_argument("--use-conviction", action="store_true")
    parser.add_argument("--use-kelly", action="store_true")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    frames = pb.load_frames(settings.normalized_dir / "delivery" / "NSE",
                            min_rows=40)
    print(f"symbols loaded: {len(frames)}")

    cfg = pb.StrategyConfig(
        signal=args.signal,
        price_min=args.price_min,
        price_max=args.price_max,
        min_turnover=args.min_turnover,
        hold_days=args.hold,
        stop_pct=args.stop_pct,
        max_positions=args.max_positions,
        capital=args.capital,
        risk_pct=args.risk_pct,
        cluster_entries=not args.no_cluster,
        z_min=args.z_min,
        use_conviction=args.use_conviction,
        use_kelly=args.use_kelly,
    )
    result = pb.run_portfolio(frames, cfg)

    print(json.dumps(result.summary, indent=2, default=str))

    metadata = MetadataStore(settings.storage.metadata_dsn)
    tracker = ExperimentTracker(metadata)
    run_id = tracker.record(kind="cluster_backtest", config=result.config,
                            metrics=result.summary)
    metadata.close()

    out_dir = Path("docs/research/generated")
    trades_json = [
        {"symbol": t.symbol, "segment": t.segment,
         "entry": str(t.entry_date), "entry_px": t.entry_px, "qty": t.qty,
         "exit": str(t.exit_date), "exit_px": t.exit_px,
         "gross_bps": t.gross_bps, "net_bps": t.net_bps,
         "reason": t.reason, "days_held": t.days_held}
        for t in result.trades
    ]
    (out_dir / "cluster_backtest.json").write_text(json.dumps({
        "run_id": run_id,
        "summary": result.summary,
        "equity_curve": [[str(d), round(v, 2)] for d, v in result.equity_curve],
        "trades": trades_json,
    }, indent=1, default=str))

    gates = {
        "n_trades>=30": result.summary["n_trades"] >= 30,
        "net>0": (result.summary["net_expectancy_bps"] or -1) > 0,
        "maxDD<15%": result.summary["max_drawdown_pct"] < 15,
    }
    print("GATES:", json.dumps(gates))
    return 0 if all(gates.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
