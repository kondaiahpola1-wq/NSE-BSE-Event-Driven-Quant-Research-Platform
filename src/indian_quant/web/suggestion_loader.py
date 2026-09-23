"""Load suggestion data for web dashboard views.

Uses PostgreSQL (PgMetadataStore) instead of SQLite.
"""

from __future__ import annotations

from typing import Any


def get_suggestion_summary() -> dict[str, Any]:
    """Get aggregated suggestion stats from PostgreSQL."""
    from indian_quant.web.prod_config import get_pg_engine
    from indian_quant.storage.pg_metadata import PgMetadataStore
    pg = PgMetadataStore(get_pg_engine())
    try:
        s = pg.suggestions_summary()
        return s
    finally:
        pg.close()


def get_suggestion_loader():
    """Return the PgMetadataStore-based suggestion functions."""
    from indian_quant.web.prod_config import get_pg_engine
    from indian_quant.storage.pg_metadata import PgMetadataStore
    return PgMetadataStore(get_pg_engine())
