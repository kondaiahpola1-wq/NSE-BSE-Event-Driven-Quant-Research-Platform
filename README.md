# NSE-BSE Event-Driven Quant Research Platform

> **Live animated documentation:** https://kondaiahpola1-wq.github.io/NSE-BSE-Event-Driven-Quant-Research-Platform/

Indian quant research & market infrastructure built around three external systems:

| System | Role |
|---|---|
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | event-driven backtesting/simulation engine (dependency, never forked) |
| [nse-bse-mcp](https://github.com/bshada/nse-bse-mcp) | upstream research data source (historical, corporate actions, announcements, bhavcopy) |
| Upstox API | live market data feed + sandbox execution connectivity |

**Core principle:** *NSE/BSE tells us what happened. Our data layer makes it trustworthy.
Nautilus tells us how a strategy would have behaved. Upstox tells us how the system behaves
against a broker interface.*

## Architecture

```
NSE/BSE CDN + MCP ──► Ingestion ──► Raw Store (immutable, hashed)
                                            │
                                            ▼
                                     Normalization ──► Quality Engine
                                            │                │
                                            ▼                ▼
                                      Validated layer   Quality reports
                                            │
                                            ▼
                                  Nautilus ParquetDataCatalog
                                            │
                                            ▼
                            BacktestEngine + Strategy
```

- **Canonical contracts** (`src/indian_quant/schemas/`): `InstrumentIdentity`, `MarketBar`,
  `CorporateAction`, `Announcement`, `OptionInstrument`, `OptionQuote` — every record carries
  full lineage (`source`, `raw_hash`, timestamps).
- **Canonical instrument id**: `NSE_EQ|RELIANCE`, `BSE_EQ|500325`, `NSE_FO|BANKNIFTY-2026-09-24-CE-52000`.
- **Storage**: parquet lake (bars + delivery), PostgreSQL 16 (signals, metadata), Redis (hot cache).
- **Adapters**: Upstox REST historical V3 works today; WebSocket feed V3 and sandbox execution
  are scaffolded behind stable interfaces (see `docs/adapter.md`).

## Quickstart

```bash
make setup                 # uv venv + install
docker compose up -d mcp   # start nse-bse-mcp on :3000
make ingest SYMBOL=RELIANCE FROM=2025-01-01 TO=2026-08-20
make validate SYMBOL=RELIANCE
make sync SYMBOL=RELIANCE
make backtest SYMBOL=RELIANCE
```

## Data Ingestion

### Coverage

| Source | Exchange | Days | Stocks | Status |
|--------|----------|------|--------|--------|
| NSE UDiFF bhavcopy | NSE | 651 (2024-01-01 → 2026-08-27) | 3,483 | Current |
| NSE delivery CSV | NSE | 651 | 3,483 | Current |
| BSE bhavcopy | BSE | 651 | 7,239 | Current |
| NSE index CSVs | NSE | — | 450 (Nifty50/Next50/Midcap150/Smallcap250) | Current |

### Ingestion Commands

```bash
# Full update (NSE + BSE, bars + delivery)
make update FROM=2025-01-01 TO=2026-08-27

# Delivery only
python scripts/bulk_ingest.py --from 2025-01-01 --to 2026-08-27 --delivery-only

# BSE only
python scripts/bulk_ingest.py --from 2025-01-01 --to 2026-08-27 --exchange BSE
```

### Data Pipeline

```
NSE CDN (sec_bhavdata_full_*.csv) ──► BhavcopyIngester ──► parquet (delivery/NSE/*.parquet)
NSE CDN (BhavCopy_NSE_CM_*.zip)   ──► BhavcopyIngester ──► parquet (bars_1d/NSE/*.parquet)
BSE bhavcopy                       ──► BseBhavcopyIngester ──► parquet (bars_1d/BSE/*.parquet)
```

## Signal Generation

### Delivery Z-Score Signals

The core alpha signal is based on **delivery z-score** — a statistical measure of unusual delivery activity:

- **`dz_hi_up` (BUY)**: Delivery z-score ≥ 2.0 AND 1-day return ≥ 0.5%
  - Unusually high delivery percentage + positive price action = institutional accumulation
- **`dz_hi_dn` (AVOID)**: Delivery z-score ≤ -2.0 AND 1-day return ≤ -0.5%
  - Unusually low delivery + negative price action = distribution

### Market Cap Classification (SEBI thresholds + SME)

| Class | Threshold | Count |
|-------|-----------|-------|
| Large Cap | ≥ ₹20,000 Cr | 259 |
| Mid Cap | ₹5,000 – ₹20,000 Cr | 937 |
| Small Cap | ₹1,000 – ₹5,000 Cr | 1,829 |
| **SME** | NSE SME segment (overrides value) | **1,048** |
| Other | No data / Micro Cap | 1,470 |

SME stocks are identified by their listing segment (`segment="SME"`) on NSE Emerge,
not by market cap value. The `apply_sme_override()` function ensures SME stocks are
always classified as "SME" regardless of their market cap.

### Signal Cache

```bash
# Rebuild signal cache (PostgreSQL + Redis)
python scripts/cache_signals.py

# Rebuild market cap cache
python scripts/build_market_cap.py
```

**Pipeline**: `cache_signals.py` → scans all NSE + BSE parquets → computes delivery z-scores,
RSI, MACD, SMA, ATR → writes to PostgreSQL `cached_signals` table → warms Redis cache
(TTL=1h, refreshed every 15 min by APScheduler).

## Paper Trading

### GO-LIVE Gate

Before going live, the system must demonstrate:
- ≥ 20 settled paper trades
- Average net return ≥ +25 bps

### Commands

```bash
# Open new paper positions (reads dz_hi_up signals)
python scripts/paper_track.py snapshot

# Settle matured positions (past horizon or stop-hit)
python scripts/paper_track.py settle

# View paper trading report
python scripts/paper_track.py report
```

### Current Status

| Metric | Value |
|--------|-------|
| Open positions | 7 |
| Settled | 0 |
| GO-LIVE gate | PENDING (0/20 settled) |

### Recent Paper Trades (2026-08-27)

| Symbol | Exchange | Cap Class | Entry ₹ | deliv_z |
|--------|----------|-----------|---------|---------|
| SUVENPHAR | NSE | Mid Cap | 1,079 | 3.26 |
| ASIANHOTNR | NSE | Small Cap | 312 | 2.49 |
| WCIL | NSE | Micro Cap | 87 | 2.59 |
| BALPHARMA | NSE | Micro Cap | 85 | 2.19 |
| FRACTAL | NSE | Mid Cap | 840 | 2.16 |
| DCAL | NSE | Small Cap | 177 | 2.13 |
| IKS | NSE | Small Cap | 1,751 | 2.12 |
| CMRGREEN | NSE | Small Cap | 221 | 2.07 |

## Web Dashboard

### Running

```bash
# Start web server (port 8080)
setsid .venv/bin/uvicorn indian_quant.web.app:app --host 127.0.0.1 --port 8080

# Or via start script
./start_platform.sh
```

### Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Paper summary, gate progress, signals overview, suggestions |
| Signals | `/signals` | Interactive signal sheet with AJAX filtering/sorting/pagination |
| Positions | `/positions` | Paper trading positions and P&L |
| Watchlist | `/watchlist` | User watchlist with per-stock analysis |
| Suggestions | `/suggestions` | Historical suggestion accuracy tracking |

### Signals Page Features

- **Server-side filter/sort/pagination** via `/api/signals` JSON endpoint
- **Market Cap filter**: All | Large Cap | Mid Cap | Small Cap | SME | Other
- **Segment filter**: All | EQ | SME
- **Sort by**: Score, Z-Score, Delivery %, Return, Market Cap
- **Quick views**: Top 20 Good / Top 20 Bad
- **50-row pagination** with page controls
- **Response time**: <100ms (Redis cache + server-side processing)

### API

```
GET /api/signals?cap=SME&segment=SME&sort=score&order=desc&page=1&per_page=50
```

Parameters:
- `cap`: Market cap class filter (All, Large Cap, Mid Cap, Small Cap, SME, Other)
- `segment`: Segment filter (All, EQ, SME)
- `sort`: Sort field (score, deliv_z, deliv_pct, ret_1d_pct, market_cap_cr, rsi, symbol, close)
- `order`: Sort direction (asc, desc)
- `page`: Page number (1-indexed)
- `per_page`: Results per page (default 50)

## Infrastructure

### Services

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 16 | 5432 | Signal cache, metadata, watchlist |
| Redis | 6379 | Hot cache (signals, market cap) |
| nse-bse-mcp | 3000 | NSE/BSE data API (59 tools) |
| Web dashboard | 8080 | FastAPI + Jinja2 |

### Scheduler (APScheduler)

- **18:00 IST daily**: Full cache rebuild (`cache_signals.py`)
- **Every 15 min**: Warm Redis from PostgreSQL (fast, no parquet scan)

### Cron

```bash
# Install daily update cron (weekdays 18:45 IST)
./setup_cron.sh
```

## Tests

```bash
make test                    # Run all 215 tests
pytest tests/ -v             # Verbose output
pytest tests/unit/ -v        # Unit tests only
```

## Layout

```
src/indian_quant/
├── features/
│   ├── delivery.py          # Delivery z-score computation
│   └── market_cap.py        # Market cap classification (SEBI thresholds + SME)
├── ingestion/
│   ├── nse/bhavcopy.py      # NSE CDN bhavcopy ingestion
│   ├── bse/bhavcopy.py      # BSE bhavcopy ingestion
│   └── mcp/                 # MCP client (nse-bse-mcp)
├── storage/                 # PostgreSQL, Redis, SQLite
├── web/
│   ├── app.py               # FastAPI application
│   ├── fast_loader.py       # Redis → PostgreSQL signal loader
│   ├── scheduler.py         # APScheduler background jobs
│   └── templates/           # Jinja2 HTML templates
└── schemas/                 # Canonical data contracts

scripts/
├── bulk_ingest.py           # NSE/BSE data ingestion
├── cache_signals.py         # Signal cache builder
├── build_market_cap.py      # Market cap classification
├── paper_track.py           # Paper trading ledger
├── suggestion_manager.py    # Suggestion tracking
└── daily_update.sh          # Cron wrapper
```

## Live Verification Evidence (Aug 2026)

| Proof | Result |
|---|---|
| NSE bars | 651 days, 3,483 stocks (2024-01-01 → 2026-08-27) |
| NSE delivery | 651 days, 3,483 stocks (current) |
| BSE bars | 651 days, 7,239 stocks (current) |
| Total signals | 9,094 (9 buys, 30 avoids) |
| Market cap coverage | 8,019 / 9,094 (88%) |
| SME classification | 1,048 signals classified as SME |
| Paper trades | 7 open positions |
| Real RELIANCE history | 404 daily bars from NSE UDiFF bhavcopy CDN |
| Upstox REST V3 vs exchange closes | **30 days · drift 0.0000% · PASS** |
| Sandbox order lifecycle | place → modify → cancelled (order 260823192859042) |
| Broker reconciliation | orders/positions/funds IO live-verified · zero mismatches |
