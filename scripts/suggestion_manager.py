"""Daily suggestion manager: auto-record signals at 1d/5d/10d horizons, settle, report.

Each dz_hi_up signal is recorded 3 times (one per horizon) with appropriate
stop-loss and target levels for each holding period.

Subcommands:
    record      Record today's signals as suggestions (x3 horizons)
    settle      Settle PENDING suggestions whose horizon has passed
    report      Show accuracy metrics by horizon + combined
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, prepare_frame
from indian_quant.storage import MetadataStore

HORIZONS = [
    {"days": 1, "label": "1d", "stop_pct": 0.03, "target_pct": 0.02,
     "capital_pct": 0.25, "predicted_bps": 30.0},
    {"days": 5, "label": "5d", "stop_pct": 0.05, "target_pct": 0.05,
     "capital_pct": 0.35, "predicted_bps": 60.0},
    {"days": 10, "label": "10d", "stop_pct": 0.07, "target_pct": 0.08,
     "capital_pct": 0.40, "predicted_bps": 80.0},
]


def _scan_today(settings) -> pd.DataFrame:
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    rows = []
    for path in sorted(dl_dir.glob("*.parquet")):
        raw = pd.read_parquet(path)
        if raw.empty:
            continue
        frame = prepare_frame(raw, min_rows=min(20, len(raw)))
        if frame is None or frame.empty:
            continue
        frame = add_features(frame)
        if frame.empty:
            continue
        last = frame.iloc[-1]
        rows.append({
            "symbol": str(last["symbol"]),
            "segment": str(last["segment"]),
            "close": float(last["close"]),
            "volume": float(last["volume"]) if "volume" in frame.columns and pd.notna(last.get("volume")) else 0,
            "deliv_pct": float(last["deliv_pct"]) if not pd.isna(last["deliv_pct"]) else None,
            "deliv_z": float(last["deliv_z"]) if not pd.isna(last["deliv_z"]) else None,
            "vol_z": float(last.get("vol_z", 0)) if not pd.isna(last.get("vol_z", np.nan)) else None,
            "ret_1d": float(last["ret_1d"]),
            "sma_20": float(last["sma_20"]) if not pd.isna(last.get("sma_20", np.nan)) else None,
            "date": last["date"].date().isoformat(),
            "_atr": float(last.get("atr_14", 0)) if not pd.isna(last.get("atr_14", np.nan)) else 0,
        })
    return pd.DataFrame(rows)


def cmd_record(settings, *, capital: float, risk_pct: float) -> int:
    df = _scan_today(settings)
    if df.empty:
        print("no delivery data")
        return 1

    latest = df["date"].max()
    day = df[df["date"] == latest]

    metadata = MetadataStore(settings.storage.metadata_dsn)

    existing = set()
    for s in metadata.suggestions_by_date(latest):
        existing.add(s["symbol"])

    created = 0

    buys = day[
        (day["deliv_z"] >= 2)
        & (day["ret_1d"] >= 0.005)
    ]

    from indian_quant.features.market_cap import get_market_cap, load_mcap_cache, save_mcap_cache
    from indian_quant.ingestion.router import SourceRouter
    router = SourceRouter()
    cache = load_mcap_cache()

    for _, r in buys.iterrows():
        if r["symbol"] in existing:
            continue

        mcap_info = get_market_cap(router, r["symbol"], "NSE", cache)

        for hz in HORIZONS:
            hz_capital = capital * hz["capital_pct"]
            risk_rupees = hz_capital * risk_pct / 100.0

            stop_dist = r["close"] * hz["stop_pct"]
            qty_by_risk = int(risk_rupees // stop_dist) if stop_dist > 0 else 0
            qty_by_capital = int((hz_capital * 0.90) // r["close"])
            qty = max(0, min(qty_by_risk, qty_by_capital))
            if qty < 1:
                continue

            atr = r.get("_atr", r["close"] * 0.03)
            entry_low = round(r["close"] - atr * 0.5, 2)
            entry_high = round(r["close"], 2)
            stop_loss = round(r["close"] * (1 - hz["stop_pct"]), 2)
            target = round(r["close"] * (1 + hz["target_pct"]), 2)

            sid = metadata.record_daily_suggestion(
                suggestion_date=latest,
                symbol=r["symbol"],
                segment=str(r["segment"]),
                signal_type="dz_hi_up",
                close_at_signal=float(r["close"]),
                deliv_pct=float(r["deliv_pct"]) if r["deliv_pct"] else None,
                deliv_z=float(r["deliv_z"]) if not pd.isna(r["deliv_z"]) else None,
                vol_z=float(r["vol_z"]) if r["vol_z"] and not pd.isna(r["vol_z"]) else None,
                entry_zone_low=entry_low,
                entry_zone_high=entry_high,
                stop_loss=stop_loss,
                target_price=target,
                horizon_days=hz["days"],
                qty=qty,
                predicted_return_bps=hz["predicted_bps"],
                note=f"z={r['deliv_z']:.2f} mcap={mcap_info['market_cap_class']}",
            )
            created += 1
            print(f"  #{sid} {r['symbol']} [{hz['label']}] @\u20b9{r['close']:.2f} "
                  f"qty={qty} stop=\u20b9{stop_loss} target=\u20b9{target} "
                  f"z={r['deliv_z']:.2f} [{mcap_info['market_cap_class']}]")

    save_mcap_cache(cache)
    summary = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()
    metadata.close()
    print(json.dumps({"created_today": created, **summary,
                       "by_horizon": by_hz}, indent=1))
    return 0


def cmd_settle(settings) -> int:
    metadata = MetadataStore(settings.storage.metadata_dsn)
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    settled_count = skipped = 0

    pending = metadata.pending_suggestions()

    for s in pending:
        sym = s["symbol"]
        path = dl_dir / f"{sym}.parquet"
        if not path.exists():
            continue

        df = pd.read_parquet(path, columns=["date", "close"])
        suggestion_date = s["suggestion_date"]

        after = df[pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d") > suggestion_date]
        if len(after) < s["horizon_days"]:
            skipped += 1
            continue

        exit_row = after.iloc[s["horizon_days"] - 1] if len(after) >= s["horizon_days"] else after.iloc[-1]
        exit_date = str(pd.to_datetime(exit_row["date"]).date())
        exit_close = float(exit_row["close"])

        result = metadata.settle_daily_suggestion(
            s["id"], exit_date=exit_date, exit_close=exit_close
        )
        hz = f"{s['horizon_days']}d"
        print(f"  SETTLED {sym} [{hz}]: net {result['actual_net_bps']}bps "
              f"ret={result['return_pct']:.1f}% days={result['days_held']} "
              f"hit={result['hit']}")
        settled_count += 1

    summary = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()
    metadata.close()
    print(json.dumps({"settled_now": settled_count,
                       "skipped_insufficient_data": skipped,
                       **summary, "by_horizon": by_hz}, indent=1))
    return 0


def cmd_report(settings) -> int:
    metadata = MetadataStore(settings.storage.metadata_dsn)
    s = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()

    gate_pass = (s["realized"] or 0) >= 20 and \
                (s["avg_realized_net_bps"] is not None and s["avg_realized_net_bps"] > 25)

    verdict = "PASS — ready for live consideration" if gate_pass else (
        f"PENDING — need >= 20 realized with avg_net >= +25bps "
        f"(currently {s['realized']} realized)"
    )

    con_str = settings.storage.metadata_dsn.removeprefix("sqlite:///")
    import sqlite3
    con = sqlite3.connect(con_str)
    by_type = con.execute("""
        SELECT signal_type, horizon_days, COUNT(*),
               AVG(actual_return_bps), SUM(hit)*1.0/COUNT(*)
        FROM daily_suggestions WHERE status='REALIZED'
        GROUP BY signal_type, horizon_days
        ORDER BY AVG(actual_return_bps) DESC
    """).fetchall()
    con.close()

    print(json.dumps({"summary": s, "golive_gate": verdict,
                       "by_horizon": by_hz,
                       "by_type_and_horizon": [
                           {"type": t[0], "horizon": f"{t[1]}d", "n": t[1],
                            "avg_net_bps": round(t[3], 1) if t[3] else None,
                            "accuracy": round(t[4], 3) if t[4] else None}
                           for t in by_type
                       ]}, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily suggestion manager")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--capital", type=float, default=25_000.0)
    rec.add_argument("--risk-pct", type=float, default=1.0)

    sub.add_parser("settle")

    sub.add_parser("report")

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "record":
        return cmd_record(settings, capital=args.capital, risk_pct=args.risk_pct)
    elif args.command == "settle":
        return cmd_settle(settings)
    elif args.command == "report":
        return cmd_report(settings)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
