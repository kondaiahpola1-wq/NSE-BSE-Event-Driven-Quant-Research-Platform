# Data Pipeline Documentation

**Last updated:** 2026-09-02

## What Is This?

A modular, automated data pipeline for Indian stock market (NSE/BSE) research. Other projects on the same system can import it as a Python library:

```python
from indian_quant.data import get_fundamentals, get_signals, get_sectors
from indian_quant.pipeline import ingest_fundamentals
```

No REST API needed — direct in-process access, as fast as real quants.

---

## Present Capabilities (as of 2026-09-02)

### Data Coverage

| Data Type | Table | Rows | Coverage | Status |
|-----------|-------|------|----------|--------|
| **Signals** | `cached_signals` | 9,096 | All NSE+BSE stocks | **Complete** |
| **Bars (OHLCV)** | Parquet | 3,845 NSE + 7,239 BSE | 26+ years daily | **Complete** |
| **Delivery data** | Parquet | 3,854 NSE + 7,254 BSE | Daily since 2019 | **Complete** |
| **Company profiles** | `company_profile` | 991 | ~28% of universe | **In progress** (background) |
| **Key ratios (PE, ROE)** | `key_ratios` | 876 | ~25% of universe | **In progress** (background) |
| **Sector classification** | `sector_map` | 1,638 | ~47% of universe | **In progress** (background) |
| **Sector daily aggregates** | `sector_daily` | 5 | Limited | **Partial** |
| **Paper trading** | `paper_signals` | 113 | Active trades | **Complete** |
| **Daily suggestions** | `daily_suggestions` | 119 | Strategy output | **Complete** |
| FII/DII flows | `fii_dii_daily` | 0 | None | **Not yet ingested** |
| Shareholding patterns | `shareholding_history` | 0 | None | **Not yet ingested** |
| Bulk deals | `bulk_deals` | 0 | None | **Not yet ingested** |
| Insider trades | `insider_trades` | 0 | None | **Not yet ingested** |
| Promoter pledge | `promoter_pledge` | 0 | None | **Not yet ingested** |
| Portfolio risk | `portfolio_risk` | 0 | None | **Not yet computed** |
| Stock risk | `stock_risk` | 0 | None | **Not yet computed** |

### What Works Right Now

**Fully functional:**
- Read 9,096 stock signals with professional scores, conviction, Kelly sizing
- Read 11,084 parquet files (OHLCV bars + delivery data for NSE+BSE)
- Read 991 company profiles (sector, industry, name)
- Read 876 fundamental ratios (PE, ROE, debt, margins, growth)
- Read 1,638 sector classifications
- Trigger single-stock or batch ingestion
- Paper trading with automated settlement
- Daily signal generation and suggestion recording

**In progress (background processes running):**
- Full universe fundamentals ingestion (~876/3,445 = 25% done)
- Full universe sector classification (~1,638/3,445 = 47% done)
- Estimated completion: ~6 hours

**Not yet available:**
- Institutional data (FII/DII, shareholding, bulk deals, insiders, pledge)
- Risk metrics (VaR, beta, drawdown)
- Real-time data (all data is T-1, updated after market close)

---

## How to Use

### Prerequisites

```bash
# 1. Install the package (from project root)
pip install -e .

# 2. PostgreSQL must be running (port 5432)
#    Default: postgres:quant2026@localhost:5432/postgres

# 3. For bar/delivery data: parquet files must exist in data/normalized/
```

### Reading Data

```python
from indian_quant.data import (
    # Fundamentals
    get_fundamentals,        # PE, ROE, debt, margins, growth
    get_company_profile,     # sector, industry, name, description
    get_market_cap,          # market cap rankings

    # Sectors
    get_sectors,             # sector classification
    get_sector_daily,        # sector daily aggregates

    # Institutional (NOT YET POPULATED)
    get_fii_dii,             # FII/DII daily flows
    get_shareholding,        # shareholding patterns
    get_bulk_deals,          # bulk deal transactions
    get_insider_trades,      # insider trading activity
    get_promoter_pledge,     # promoter pledge data

    # Signals
    get_signals,             # cached signals with scores
    get_stock_signal,        # single stock signal

    # Risk (NOT YET POPULATED)
    get_portfolio_risk,      # portfolio-level VaR, beta
    get_stock_risk,          # per-stock risk metrics

    # Bars
    get_bars,                # historical OHLCV
    get_delivery,            # delivery data
)

# Example: Get top 10 BUY signals by professional score
buy_signals = get_signals(signal_type="BUY", limit=10)
print(buy_signals[["symbol", "close", "professional_score", "sector"]])

# Example: Get RELIANCE fundamentals
data = get_fundamentals("RELIANCE")
print(f"PE: {data['pe_trailing']}, ROE: {data['roe']}, Sector: {data['sector']}")

# Example: Get all banking stocks
sectors = get_sectors()
banks = sectors[sectors["sector"] == "Banking"]
```

### Triggering Ingestion

```python
from indian_quant.pipeline import (
    ingest_fundamentals,      # Single stock
    ingest_all_fundamentals,  # Batch
    ingest_sectors,           # Single stock
    ingest_all_sectors,       # Batch
)

# Ingest one stock
ingest_fundamentals("RELIANCE")

# Ingest all recently traded stocks (takes hours)
result = ingest_all_fundamentals(recent=True, batch_size=50)
# Returns: {"success": 800, "failed": 120, "skipped": 2500, "total": 3445}

# Ingest sector classification
ingest_sectors("RELIANCE")
```

### CLI Usage

```bash
# Single stock
python scripts/ingest_fundamentals.py --symbol RELIANCE
python scripts/ingest_sectors.py --symbol RELIANCE

# Batch (all stocks)
python scripts/ingest_fundamentals.py --recent --batch-size 50
python scripts/ingest_sectors.py --batch-size 50
```

---

## Data Sources & Fallback Chain

```
Priority 1: FinStack MCP (local Python library)
    ↓ fallback
Priority 2: Indian Market MCP (local Python library, 68 tools)
    ↓ fallback
Priority 3: Free hosted MCP endpoints (3 servers, merit-order)
    ↓ fallback
Priority 4: yfinance (Yahoo Finance, ~2s per symbol)
```

**For OHLCV bars:**
```
Priority 1: NSE Bhavcopy CDN (same-day data by 18:30 IST)
    ↓ fallback
Priority 2: BSE India library
    ↓ fallback
Priority 3: yfinance
```

---

## Limitations

### Data Limitations

1. **T-1 data only**: NSE delivery data is published next day. OHLCV bars available same day by 18:00-18:30 IST.

2. **yfinance is slow and incomplete**: ~2 seconds per symbol. Many SME stocks, ETFs, and debt instruments return 404. Only works for stocks listed on Yahoo Finance.

3. **FinStack/IndianMarket MCP must be running**: These are local Python libraries that need to be installed and configured. If not available, falls back to yfinance (slow).

4. **Free MCP endpoints are unreliable**: Rate-limited (429 errors), sometimes down, limited tool coverage.

5. **Institutional data not yet ingested**: FII/DII, shareholding, bulk deals, insider trades, promoter pledge tables are empty. The `ingest_institutional.py` script exists but hasn't been run for the full universe.

6. **Risk metrics not computed**: Portfolio risk and stock risk tables are empty. `compute_risk.py` needs to be run.

7. **Sector daily aggregates limited**: Only 5 rows. The `sector_daily` table needs more historical data.

### Technical Limitations

8. **PostgreSQL required**: All query functions need a running PostgreSQL instance. No SQLite fallback for the data layer.

9. **Parquet files required for bars**: `get_bars()` and `get_delivery()` read from local parquet files. If files don't exist, you get `FileNotFoundError`.

10. **No real-time data**: Everything is batch-processed after market close. No streaming or live quotes.

11. **India-only**: Currently supports NSE and BSE exchanges only. Architecture is extensible but no other markets implemented.

12. **Single-system access**: Data is stored locally. Other projects must be on the same machine to import the library. No REST API for remote access.

### Coverage Gaps

13. **~72% of universe missing fundamentals**: Only 876/3,445 stocks have key ratios. Background ingestion is running but will take ~6 hours.

14. **~53% of universe missing sector classification**: 1,638/3,445 stocks have sector data. Background ingestion running.

15. **No quarterly financials**: The `quarterly_financials` table exists but is not populated by any pipeline.

16. **No earnings data**: No earnings calendar or results data.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NSE_QUANT_PG_DSN` | `postgresql://postgres:quant2026@127.0.0.1:5432/postgres` | PostgreSQL connection |
| `NSE_QUANT_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis connection |
| `REDIS_TTL` | `3600` | Cache TTL in seconds |

### Programmatic Configuration

```python
from indian_quant.config.connections import get_engine, get_redis

# Use custom DSN
engine = get_engine("postgresql://user:pass@host:5432/db")
redis = get_redis("redis://host:6379/1")
```

---

## Architecture

```
LAYER 5: SCHEDULER (platform_scheduler.py)
  Daily lifecycle: morning → market hours → evening → night

LAYER 4: SCRIPTS (scripts/*.py)
  Thin CLI wrappers, just parse args → call Layer 3

LAYER 3: PIPELINE (src/indian_quant/pipeline/)
  Orchestrators: ingest_fundamentals, ingest_sectors
  Use SourceRouter + storage abstractions

LAYER 2: DATA ACCESS (src/indian_quant/data/)
  Public API: get_fundamentals(), get_signals(), etc.
  Reads from PostgreSQL/Parquet, no side effects

LAYER 1: CORE (src/indian_quant/)
  MCP clients, SourceRouter, Storage, Schemas
```

---

## Adding New Data Sources

### Step 1: Add Pipeline Function

```python
# src/indian_quant/pipeline/earnings.py
from indian_quant.config.connections import get_engine
from indian_quant.utils import safe_float

def ingest_earnings(symbol: str) -> bool:
    """Ingest earnings data for a stock."""
    data = _fetch_earnings(symbol)  # Your fetch logic
    if data:
        _upsert_earnings(get_engine(), symbol, data)
        return True
    return False
```

### Step 2: Add Data Access Function

```python
# src/indian_quant/data/earnings.py
import pandas as pd
import sqlalchemy as sa
from indian_quant.config.connections import get_engine

def get_earnings(symbol: str | None = None) -> pd.DataFrame:
    """Read earnings data from PostgreSQL."""
    engine = get_engine()
    query = "SELECT * FROM earnings"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()
    return pd.read_sql(sa.text(query), engine, params=params)
```

### Step 3: Export from `data/__init__.py`

```python
from indian_quant.data.earnings import get_earnings
```

### Step 4: Add CLI Wrapper (optional)

```python
# scripts/ingest_earnings.py
import argparse
from indian_quant.pipeline.earnings import ingest_earnings

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    ok = ingest_earnings(args.symbol.upper())
    print(f"{'OK' if ok else 'NO DATA'}: {args.symbol}")

if __name__ == "__main__":
    main()
```

---

## Database Tables

| Table | Source Script | Rows | Description |
|-------|--------------|------|-------------|
| `cached_signals` | cache_signals.py | 9,096 | Pre-computed signals with 30+ columns |
| `key_ratios` | ingest_fundamentals.py | 876 | PE, ROE, debt, margins, growth |
| `company_profile` | ingest_fundamentals.py | 991 | Sector, industry, company name |
| `sector_map` | ingest_sectors.py | 1,638 | Sector classification |
| `sector_daily` | ingest_sectors.py | 5 | Sector daily aggregates |
| `paper_signals` | paper_track.py | 113 | Paper trading positions |
| `daily_suggestions` | suggestion_manager.py | 119 | Daily strategy suggestions |
| `fii_dii_daily` | ingest_institutional.py | 0 | FII/DII flows (empty) |
| `shareholding_history` | ingest_institutional.py | 0 | Ownership patterns (empty) |
| `bulk_deals` | ingest_institutional.py | 0 | Bulk transactions (empty) |
| `insider_trades` | ingest_institutional.py | 0 | Insider activity (empty) |
| `promoter_pledge` | ingest_institutional.py | 0 | Pledge data (empty) |
| `portfolio_risk` | compute_risk.py | 0 | Portfolio VaR/beta (empty) |
| `stock_risk` | compute_risk.py | 0 | Per-stock risk (empty) |

---

## Background Processes (as of 2026-09-02)

| Process | PID | Purpose | ETA |
|---------|-----|---------|-----|
| Fundamentals ingestion | 22702 | Fetching PE/ROE/etc. for 3,445 stocks | ~6 hours |
| Sectors ingestion | 22703 | Classifying sectors for 3,445 stocks | ~2 hours |
| OpenViking server | 17713 | Knowledge RAG for project memory | Running |
| Ollama (nomic-embed-text) | 3040 | Embedding model for OpenViking | Running |
