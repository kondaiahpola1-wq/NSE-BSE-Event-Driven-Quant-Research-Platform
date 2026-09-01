"""Production configuration for PostgreSQL + Redis.

Environment variables (or defaults):
    NSE_QUANT_PG_DSN    PostgreSQL connection string
    NSE_QUANT_REDIS_URL Redis connection string
"""

from __future__ import annotations

import contextlib
import os
from functools import lru_cache

import redis
import sqlalchemy as sa

PG_DSN = os.getenv("NSE_QUANT_PG_DSN", "postgresql://postgres:quant2026@127.0.0.1:5432/postgres")
REDIS_URL = os.getenv("NSE_QUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_TTL = int(os.getenv("REDIS_TTL", "3600"))


@lru_cache
def get_pg_engine():
    connect_args = {}
    if PG_DSN.startswith("postgresql"):
        connect_args["connect_timeout"] = 5
    return sa.create_engine(PG_DSN, pool_size=2, max_overflow=5, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_redis_client():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)


def ensure_pg_schema():
    """Create cached_signals table if not exists."""
    engine = get_pg_engine()
    meta = sa.MetaData()
    sa.Table(
        "cached_signals",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "exchange", name="cached_signals_pkey"),
        sa.Column("signal_date", sa.String(10)),
        sa.Column("segment", sa.String(8)),
        sa.Column("close", sa.Float),
        sa.Column("prev_close", sa.Float),
        sa.Column("ret_1d_pct", sa.Float),
        sa.Column("deliv_pct", sa.Float),
        sa.Column("deliv_z", sa.Float),
        sa.Column("vol_z", sa.Float),
        sa.Column("rsi", sa.Float),
        sa.Column("macd", sa.Float),
        sa.Column("macd_signal", sa.Float),
        sa.Column("sma_20", sa.Float),
        sa.Column("sma_50", sa.Float),
        sa.Column("atr_14", sa.Float),
        sa.Column("hi_streak", sa.Integer),
        sa.Column("signal_type", sa.String(16)),
        sa.Column("entry_zone_low", sa.Float),
        sa.Column("entry_zone_high", sa.Float),
        sa.Column("stop_loss", sa.Float),
        sa.Column("target_price", sa.Float),
        sa.Column("volume", sa.Float),
        sa.Column("cached_at", sa.String(32)),
        sa.Column("market_cap_class", sa.String(16)),
        sa.Column("market_cap_cr", sa.Float),
    )
    meta.create_all(engine)

    # Add columns to existing table if missing
    try:
        with engine.begin() as conn:
            with contextlib.suppress(Exception):
                conn.execute(
                    sa.text("ALTER TABLE cached_signals ADD COLUMN market_cap_class VARCHAR(16)")
                )
            with contextlib.suppress(Exception):
                conn.execute(sa.text("ALTER TABLE cached_signals ADD COLUMN market_cap_cr FLOAT"))
            # Fundamental columns
            for col, typedef in [
                ("pe_trailing", "FLOAT"), ("price_to_book", "FLOAT"),
                ("roe", "FLOAT"), ("debt_to_equity", "FLOAT"),
                ("profit_margin", "FLOAT"), ("revenue_growth", "FLOAT"),
                ("dividend_yield", "FLOAT"), ("ev_to_ebitda", "FLOAT"),
                ("current_ratio", "FLOAT"), ("sector", "VARCHAR(64)"),
                ("industry", "VARCHAR(128)"), ("company_name", "TEXT"),
                ("fundamental_score", "FLOAT"),
                # Institutional columns
                ("fii_pct", "FLOAT"), ("dii_pct", "FLOAT"),
                ("promoter_pct", "FLOAT"), ("fii_chg", "FLOAT"),
                ("dii_chg", "FLOAT"), ("promoter_chg", "FLOAT"),
                ("pledge_pct", "FLOAT"), ("institutional_score", "FLOAT"),
                # Professional score
                ("professional_score", "FLOAT"),
            ]:
                with contextlib.suppress(Exception):
                    conn.execute(sa.text(f"ALTER TABLE cached_signals ADD COLUMN {col} {typedef}"))
    except Exception:
        pass
