"""Indian Quant Data Pipeline Orchestrators.

Automated ingestion pipelines that fetch data from multiple sources,
normalize it, and store it in PostgreSQL/parquet.

Usage:
    from indian_quant.pipeline import ingest_fundamentals, ingest_sectors

    # Ingest one stock
    ingest_fundamentals("RELIANCE")

    # Ingest all recently traded stocks
    ingest_all_fundamentals(recent=True)
"""

from indian_quant.pipeline.fundamentals import (
    ingest_all_fundamentals,
    ingest_fundamentals,
)
from indian_quant.pipeline.sectors import ingest_all_sectors, ingest_sectors

__all__ = [
    "ingest_all_fundamentals",
    "ingest_all_sectors",
    "ingest_fundamentals",
    "ingest_sectors",
]
