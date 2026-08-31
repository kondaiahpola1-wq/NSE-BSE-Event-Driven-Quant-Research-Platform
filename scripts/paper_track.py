"""Paper-trading ledger: snapshot today's candidates, settle, report.

Subcommands:
    snapshot   write current dz_hi_up BUY candidates as OPEN paper rows
    settle     close OPEN rows past horizon or stop-hit (latest delivery closes)
    report     predicted-vs-realized summary + GO-LIVE gate verdict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, prepare_frame
from indian_quant.storage import MetadataStore

GO_LIVE_MIN_SETTLED = 20
GO_LIVE_REALIZED_FLOOR_BPS = 25.0  # >=50% of researched ~50bps net expectancy


def _scan_today(settings) -> pd.DataFrame:
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    rows = []
    for path in sorted(dl_dir.glob("*.parquet")):
        raw = pd.read_parquet(path)
        frame = prepare_frame(raw, min_rows=40)
        if frame is None:
            continue
        frame = add_features(frame)
        if frame is None or frame.empty:
            continue
        last = frame.iloc[-1]
        rows.append({
            "symbol": str(last["symbol"]),
            "segment": str(last["segment"]),
            "close": float(last["close"]),
            "deliv_pct": last["deliv_pct"],
            "deliv_z": last["deliv_z"],
            "ret_1d": last["ret_1d"],
            "date": last["date"].date().isoformat(),
        })
    return pd.DataFrame(rows)


def cmd_snapshot(settings, *, capital: float, risk_pct: float) -> int:
    df = _scan_today(settings)
    if df.empty:
        print("no delivery data")
        return 1
    latest = df["date"].max()
    day = df[df["date"] == latest]

    # NO price filter — scan ALL stocks
    buys = day[(day["deliv_z"] >= 2) & (day["ret_1d"] >= 0.005)]

    # Classify by market cap
    from indian_quant.features.market_cap import get_market_cap, load_mcap_cache, save_mcap_cache
    from indian_quant.ingestion.router import SourceRouter
    router = SourceRouter()
    cache = load_mcap_cache()

    metadata = MetadataStore(settings.storage.metadata_dsn)
    open_syms = {p["symbol"] for p in metadata.open_papers()}
    created = 0
    for _, r in buys.iterrows():
        if r["symbol"] in open_syms:
            continue

        mcap_info = get_market_cap(router, r["symbol"], "NSE", cache)
        risk_rupees = capital * risk_pct / 100.0
        stop_dist = r["close"] * 0.07
        qty_by_risk = int(risk_rupees // stop_dist) if stop_dist > 0 else 0
        qty_by_capital = int((capital * 0.30) // r["close"])
        qty = max(0, min(qty_by_risk, qty_by_capital))
        if qty < 1:
            continue
        metadata.record_paper_signal(
            symbol=r["symbol"], close_at_signal=float(r["close"]), qty=qty,
            horizon_days=10, stop_pct=0.07, segment=str(r["segment"]),
            note=f"dz={r['deliv_z']:.2f} mcap={mcap_info['market_cap_class']}",
        )
        created += 1
        print(f"OPEN {r['symbol']} @{r['close']:.2f} qty {qty} "
              f"(z {r['deliv_z']}) [{mcap_info['market_cap_class']}]")

    save_mcap_cache(cache)
    summary = metadata.papers_summary()
    metadata.close()
    print(json.dumps({"created": created, **summary}, indent=1))
    return 0


def cmd_settle(settings) -> int:
    metadata = MetadataStore(settings.storage.metadata_dsn)
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    settled = skipped = 0
    for paper in metadata.open_papers():
        path = dl_dir / f"{paper['symbol']}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        latest_date = str(df["date"].iloc[-1])[:10]
        latest_close = float(df["close"].iloc[-1])

        opened = pd.to_datetime(paper["created_at"]).date()
        sessions_held = len(pd.date_range(opened, pd.to_datetime(latest_date).date(),
                                          freq="B"))
        hit_stop = latest_close <= paper["close_at_signal"] * (1 - paper["stop_pct"])
        past_horizon = sessions_held > paper["horizon_days"]
        if not (hit_stop or past_horizon):
            skipped += 1
            continue
        reason = "STOP" if hit_stop else "HORIZON"
        result = metadata.settle_paper_signal(
            paper["id"], exit_date=latest_date, exit_close=latest_close)
        print(f"SETTLE {paper['symbol']} ({reason}): net "
              f"{result['realized_net_bps']}bps")
        settled += 1
    summary = metadata.papers_summary()
    metadata.close()
    print(json.dumps({"settled_now": settled, "skipped_still_open": skipped,
                      **summary}, indent=1))
    return 0


def cmd_report(settings, *, min_settled: int, floor_bps: float) -> int:
    metadata = MetadataStore(settings.storage.metadata_dsn)
    s = metadata.papers_summary()
    metadata.close()
    passed = (s["settled"] or 0) >= min_settled and (
        s["avg_net_bps"] is not None and s["avg_net_bps"] >= floor_bps)
    verdict = ("PASS — GO-LIVE CHECKLIST may be generated"
               if passed else
               f"PENDING — need ≥{min_settled} settled with avg_net ≥ {floor_bps}bps")
    print(json.dumps({"summary": s, "golive_gate": verdict}, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper trading ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--capital", type=float, default=25_000.0)
    snap.add_argument("--risk-pct", type=float, default=1.0)

    sub.add_parser("settle")

    rep = sub.add_parser("report")
    rep.add_argument("--min-settled", type=int, default=GO_LIVE_MIN_SETTLED)
    rep.add_argument("--floor-bps", type=float, default=GO_LIVE_REALIZED_FLOOR_BPS)

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "snapshot":
        return cmd_snapshot(settings, capital=args.capital,
                            risk_pct=args.risk_pct)
    if args.command == "settle":
        return cmd_settle(settings)
    if args.command == "report":
        return cmd_report(settings, min_settled=args.min_settled,
                          floor_bps=args.floor_bps)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
