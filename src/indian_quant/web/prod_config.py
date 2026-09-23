"""Production configuration for PostgreSQL + Redis.

This module re-exports from config.connections for backward compatibility.
New code should import from indian_quant.config.connections directly.
"""

from indian_quant.config.connections import (
    PG_DSN,
    REDIS_TTL,
    REDIS_URL,
    ensure_schema,
    get_engine,
    get_redis,
)

# Backward-compatible alias
get_pg_engine = get_engine
get_redis_client = get_redis

__all__ = [
    "PG_DSN",
    "REDIS_TTL",
    "REDIS_URL",
    "ensure_schema",
    "get_engine",
    "get_pg_engine",
    "get_redis",
    "get_redis_client",
]
