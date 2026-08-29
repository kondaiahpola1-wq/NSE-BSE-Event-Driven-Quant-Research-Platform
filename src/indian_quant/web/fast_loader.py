"""Fast data loader with Redis hot cache + PostgreSQL fallback.

Architecture:
    Request → Redis (sub-ms) → PostgreSQL (5ms) → parquet (slow, last resort)

Redis keys:
    signals:all      - all signals JSON (TTL=1h)
    signals:buys     - dz_hi_up signals JSON
    signals:avoids   - dz_hi_dn signals JSON
    signals:by_symbol - hash map: symbol → signal JSON
    signals:date     - latest signal date
    signals:count    - total signal count
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from indian_quant.web.prod_config import (
    ensure_pg_schema,
    get_pg_engine,
    get_redis_client,
)


def _redis_get(key: str) -> str | None:
    try:
        r = get_redis_client()
        return r.get(key)
    except Exception:
        return None


def _redis_set(key: str, value: str, ttl: int = 3600) -> None:
    try:
        r = get_redis_client()
        r.set(key, value, ex=ttl)
    except Exception:
        pass


def get_latest_signals_cached() -> dict[str, Any]:
    """Fast: Redis → PostgreSQL → empty."""
    # 1) Try Redis
    cached = _redis_get("signals:all")
    if cached:
        signals = json.loads(cached)
        latest_date = signals[0]["signal_date"] if signals else ""
        buys = [s for s in signals if s.get("signal_type") == "dz_hi_up"]
        avoids = [s for s in signals if s.get("signal_type") == "dz_hi_dn"]
        return {
            "date": latest_date,
            "buys": buys,
            "avoids": avoids,
            "all": signals,
            "total_scanned": len(signals),
        }

    # 2) Fallback to PostgreSQL
    try:
        engine = get_pg_engine()
        ensure_pg_schema()
        df = pd.read_sql("SELECT * FROM cached_signals", engine)
        if not df.empty:
            # Warm Redis for next time
            signals = df.to_dict(orient="records")
            _redis_set("signals:all", json.dumps(signals, default=str))
            latest_date = df["signal_date"].max()
            today = df[df["signal_date"] == latest_date]
            buys = today[today["signal_type"] == "dz_hi_up"].to_dict(orient="records")
            avoids = today[today["signal_type"] == "dz_hi_dn"].to_dict(orient="records")
            return {
                "date": str(latest_date),
                "buys": buys,
                "avoids": avoids,
                "all": signals,
                "total_scanned": int(len(today)),
            }
    except Exception:
        pass

    return {"date": "", "buys": [], "avoids": [], "all": [], "total_scanned": 0}


def get_cached_signal_for_symbol(symbol: str) -> dict[str, Any] | None:
    """Get cached signal for a single symbol. Redis hash → PG fallback."""
    sym = symbol.upper()

    # 1) Try Redis hash
    try:
        r = get_redis_client()
        raw = r.hget("signals:by_symbol", sym)
        if raw:
            return json.loads(raw)
    except Exception:
        pass

    # 2) PostgreSQL
    try:
        engine = get_pg_engine()
        df = pd.read_sql(
            "SELECT * FROM cached_signals WHERE symbol = :sym",
            engine, params={"sym": sym},
        )
        if not df.empty:
            return df.iloc[0].to_dict()
    except Exception:
        pass

    return None


def get_cached_signals_summary() -> dict[str, Any]:
    """Summary stats for dashboard cards."""
    # Redis fast path
    count = _redis_get("signals:count")
    date = _redis_get("signals:date")
    buys_raw = _redis_get("signals:buys")
    avoids_raw = _redis_get("signals:avoids")

    if count is not None:
        return {
            "date": date or "",
            "total": int(count),
            "buys": len(json.loads(buys_raw)) if buys_raw else 0,
            "avoids": len(json.loads(avoids_raw)) if avoids_raw else 0,
        }

    # PostgreSQL fallback
    try:
        engine = get_pg_engine()
        df = pd.read_sql("SELECT * FROM cached_signals", engine)
        if not df.empty:
            latest = df["signal_date"].max()
            today = df[df["signal_date"] == latest]
            return {
                "date": str(latest),
                "total": int(len(today)),
                "buys": int((today["signal_type"] == "dz_hi_up").sum()),
                "avoids": int((today["signal_type"] == "dz_hi_dn").sum()),
            }
    except Exception:
        pass

    return {"total": 0, "buys": 0, "avoids": 0, "date": ""}
