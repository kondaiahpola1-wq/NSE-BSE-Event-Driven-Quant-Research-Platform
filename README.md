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
                                             │
                                             ▼
                                   Hypothesis Layer
                                    │       │       │       │
                                    ▼       ▼       ▼       ▼
                              DEL   CIRC   SURV   ANN  (4 hypotheses)
                                    │       │       │       │
                                    ▼       ▼       ▼       ▼
                              Paper Signals (₹10L each, 7 max/hypo)
                                    │       │       │       │
                                    ▼       ▼       ▼       ▼
                              Trade Journal (auto-synced on entry/exit)
                                    │
                                    ▼
                              Web Dashboard (positions, journal, risk, backtest)
```

- **Canonical contracts** (`src/indian_quant/schemas/`): `InstrumentIdentity`, `MarketBar`,
  `CorporateAction`, `Announcement`, `OptionInstrument`, `OptionQuote` — every record carries
  full lineage (`source`, `raw_hash`, timestamps).
- **Canonical instrument id**: `NSE_EQ|RELIANCE`, `BSE_EQ|500325`, `NSE_FO|BANKNIFTY-2026-09-24-CE-52000`.
- **Storage**: parquet lake (bars + delivery), PostgreSQL 16 (signals, metadata, journal), Redis (hot cache).
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

## Hypothesis System

4 hypotheses running concurrently, each with ₹10L allocated capital and max 7 open positions:

| ID | Name | Source | Entry Signals |
|---|---|---|---|
| 1 | **Delivery Momentum** | delivery_z + cluster_entry/continuation | cluster_entry, cluster_continuation |
| 2 | **Circuit Breakout** | circuit limits + live price feed | lower_reversal, upper_reversal |
| 3 | **Surveillance Recovery** | NSE/BSE surveillance data | debarment_lifted, stage_exited, caveating |
| 4 | **Announcement Alpha** | BSE announcements + sentiment | earnings_surprise, merger, board_change |

### Position Management

- **₹1L notional per trade** — enforced across all hypothesis trade creators
- **Max 7 open positions per hypothesis** — enforced in `hypothesis_signals.py`
- **Settlement** — auto-settled by horizon (1d/5d/15d), stop-loss, or manual exit
- **Trailing stop** — ATR-based, moved to breakeven at +2% unrealized

### Commands

```bash
# Generate today's hypothesis signals
python scripts/hypothesis_signals.py --date 2026-09-10

# Settle matured positions (horizon/stop/cap)
python scripts/hypothesis_settle.py

# Cap excess positions (enforce 7 per hypothesis)
python scripts/cap_hypothesis_positions.py

# Live paper update (check stops, horizons against live prices)
python scripts/live_paper_update.py

# Cluster backtest (per-signal metrics)
python scripts/cluster_backtest.py --signals dz_hi_up,dz_hi_dn,dz_lo_up,spike_70,streak3
```

## Paper Trading

### Current Status (Sept 2026)

| Metric | Value |
|--------|-------|
| Total Capital | ₹40,00,000 (₹10L × 4 hypotheses) |
| Total Equity | ₹40,30,037 (+₹30,037 realized) |
| Open positions | 7 |
| Settled | 35 |
| Avg Net BPS | -78.7 |
| Hit Rate | —% |
| GO-LIVE gate | PASSED (35/20 settled, ₹+30K realized) |

### Position Sizing

| Hypothesis | Capital | Deployed | Available | Realized | Open |
|---|---|---|---|---|---|
| Delivery Momentum | ₹10,00,000 | ₹2,99,411 | ₹7,00,589 | -₹7,691 | 3/7 |
| Circuit Breakout | ₹10,00,000 | ₹2,00,000 | ₹8,00,000 | +₹48,225 | 2/7 |
| Surveillance Recovery | ₹10,00,000 | ₹1,99,604 | ₹8,00,396 | -₹10,497 | 2/7 |
| Announcement Alpha | ₹10,00,000 | ₹0 | ₹10,00,000 | ₹0 | 0/7 |
| **Total** | **₹40,00,000** | **₹6,99,015** | **₹33,00,985** | **+₹30,037** | **7/28** |

### Paper Trade Commands

```bash
# Open new paper positions (reads hypothesis signals)
python scripts/paper_track.py snapshot --capital 250000

# Settle matured positions (past horizon or stop-hit)
python scripts/paper_track.py settle

# View paper trading report
python scripts/paper_track.py report
```

### Manual Exit

Every open position on `/positions` has a red **Exit** button:
- Click → confirm dialog → exits at live market price
- Settled with `exit_reason=MANUAL`, journal synced, capital cards update
- Requires live price available (Upstox); refuses if market closed

## Web Dashboard

### Running

```bash
# Start web server (port 8080)
setsid .venv/bin/python -m uvicorn indian_quant.web.app:app --host 0.0.0.0 --port 8080

# Or via start script
./start_platform.sh
```

### Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Paper summary, gate progress, signals overview |
| Signals | `/signals` | Interactive signal sheet with AJAX filtering/sorting/pagination |
| Positions | `/positions` | Live paper positions with capital allocation, manual exit, sync audit |
| Journal | `/journal` | Trade journal with per-hypothesis breakdown, review workflow |
| Hypotheses | `/hypotheses` | All 4 hypotheses with stats, stocks, signals |
| Hypothesis Detail | `/hypothesis/{id}` | Per-hypothesis: open/settled trades, stocks, signals, equity curve |
| Backtest | `/backtest` | Cluster backtest results, per-signal metrics, live paper by hypothesis |
| Risk | `/risk` | Portfolio risk metrics (VaR, Sharpe, max drawdown, beta) |
| Surveillance | `/surveillance` | Active surveillance stocks, signals, framework stats |
| Stock Detail | `/stock/{symbol}` | Per-stock technicals, signals, history |
| Watchlist | `/watchlist` | User watchlist with per-stock analysis |
| Analytics | `/analytics` | Portfolio analytics, equity curve |
| Health | `/healthz` | System health check |

### Positions Page Features

- **Capital Allocation cards**: Total Capital (₹40L) with equity/deployed/available/realized % + per-hypothesis breakdown
- **Sync audit badge**: ✓ synced (counts, entries, exits, orphans, bps — all verified on every page load)
- **Manual Exit button**: Red button per open position → live price exit, journal synced
- **Entry/Exit dates**: Date columns in positions table
- **Filters**: By hypothesis (DEL/CIRC/SURV/ANN), by horizon (1d/5d/15d)

### Journal Page Features

- **Per-hypothesis breakdown**: Entries count, win rate, avg net bps, realized P&L, reviewed status
- **Cross-links**: "View entries" filters journal, "Live trades" jumps to positions
- **Review workflow**: Rating, what went right/wrong, lessons learned, would repeat

### API Endpoints

```
GET  /api/signals?cap=SME&segment=SME&sort=score&order=desc&page=1&per_page=50
GET  /api/portfolio_risk
GET  /api/hypothesis/{id}/signals?date=2026-09-10
GET  /api/hypothesis/{id}/trades?status=OPEN
POST /positions/exit/{trade_id}
POST /api/hypothesis/{id}/trade/open
POST /api/hypothesis/{id}/trade/close
POST /api/hypothesis/{id}/clone
POST /api/hypothesis/{id}/toggle
```

### Scheduler (APScheduler)

| Time (IST) | Task | Description |
|---|---|---|
| 08:00 | Morning cycle | Generate hypothesis signals for today |
| 08:30–15:30 | Market refresh | Every 30 min: live update, check stops/horizons |
| 16:00 | Market close | Final settle of day's positions |
| 18:00 | Evening cycle | cluster_backtest, cache_rebuild, compute_risk, snapshot |
| 21:00 | Night stop | Stop scheduler |

## Infrastructure

### Services

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 16 | 5432 | Signal cache, metadata, paper signals, trade journal |
| Redis | 6379 | Hot cache (signals, market cap) |
| nse-bse-mcp | 3000 | NSE/BSE data API (59 tools) |
| Web dashboard | 8080 | FastAPI + Jinja2 |

### Key Database Tables

| Table | Purpose |
|---|---|
| `paper_signals` | All paper trades (source of truth) |
| `trade_journal` | Auto-synced journal entries/exits |
| `hypotheses` | Hypothesis definitions (4 active) |
| `hypothesis_signals` | Generated signals per hypothesis |
| `hypothesis_trades` | Audit trail of hypothesis trades |
| `cached_signals` | Cached signal data |
| `portfolio_risk` | Risk metrics snapshots |
| `surveillance_stocks` | Active surveillance stocks |
| `surveillance_signals` | Surveillance buy/sell signals |

## Tests

```bash
make test                    # Run all 228+ tests
pytest tests/ -v             # Verbose output
pytest tests/unit/ -v        # Unit tests only
```

## Layout

```
src/indian_quant/
├── features/
│   ├── delivery.py          # Delivery z-score computation
│   ├── market_cap.py        # Market cap classification (SEBI thresholds + SME)
│   └── calendar_utils.py    # Trading calendar utilities
├── hypotheses/
│   ├── registry.py          # HypothesisRegistry (open/close/signal/trade lifecycle)
│   ├── delivery_momentum.py # Hypothesis 1: delivery z-score + cluster entry
│   ├── circuit_breakout.py  # Hypothesis 2: circuit limit reversals
│   ├── surveillance_recovery.py # Hypothesis 3: surveillance debarment lift
│   └── announcement_alpha.py    # Hypothesis 4: BSE announcement alpha
├── ingestion/
│   ├── nse/bhavcopy.py      # NSE CDN bhavcopy ingestion
│   ├── bse/bhavcopy.py      # BSE bhavcopy ingestion
│   ├── bse/shareholding.py   # BSE shareholding pattern ingestion
│   └── web/                  # Web scraping (surveillance, ASM/GSM)
├── storage/
│   ├── pg_metadata.py       # PostgreSQL metadata store (paper_signals, trade_journal)
│   └── metadata.py          # SQLite metadata store (legacy)
├── web/
│   ├── app.py               # FastAPI application (all routes + API endpoints)
│   ├── auth.py              # Authentication (bcrypt, session)
│   ├── fast_loader.py       # Redis → PostgreSQL signal loader
│   ├── live_prices.py       # Live price service (Upstox)
│   ├── portfolio_analytics.py # Portfolio analytics, equity curve
│   ├── scheduler.py         # APScheduler background jobs
│   └── templates/           # Jinja2 HTML templates
│       ├── positions.html   # Live paper positions + capital allocation
│       ├── journal.html     # Trade journal + per-hypothesis breakdown
│       ├── backtest.html    # Cluster backtest results
│       ├── hypotheses.html  # All hypotheses overview
│       ├── hypothesis_detail.html # Per-hypothesis detail
│       ├── risk.html        # Portfolio risk dashboard
│       ├── surveillance.html # Surveillance stocks + signals
│       └── ...
├── adapters/
│   ├── upstox/rest.py       # Upstox REST V3 adapter
│   └── announcements/       # BSE announcement adapter
└── schemas/                 # Canonical data contracts

scripts/
├── hypothesis_signals.py    # Generate hypothesis signals (entry logic)
├── hypothesis_settle.py     # Settle matured hypothesis positions
├── live_paper_update.py     # Live paper update (check stops/horizons)
├── cap_hypothesis_positions.py # Enforce max 7 per hypothesis
├── paper_track.py           # Paper trading ledger (snapshot/settle)
├── cache_signals.py         # Signal cache builder
├── cluster_backtest.py      # Cluster backtest (per-signal metrics)
├── compute_risk.py          # Portfolio risk metrics
├── detect_live_circuits.py  # Live circuit detection + trading
├── surveillance_paper_trade.py # Surveillance-based paper trading
├── platform_scheduler.py    # Automated scheduler (morning/market/evening/night)
├── upstox_auto_login.py     # Upstox token refresh (Selenium)
├── upstox_token_watchdog.py # Token expiry watchdog
├── bulk_ingest.py           # NSE/BSE data ingestion
├── suggestion_manager.py    # Suggestion tracking + gate logic
├── signal_decay.py          # Signal decay analysis
├── friction_report.py       # Transaction cost analysis
└── daily_update.sh          # Cron wrapper
```

## Live Verification Evidence (Sept 2026)

| Proof | Result |
|---|---|
| NSE bars | 651 days, 3,483 stocks (2024-01-01 → 2026-08-27) |
| NSE delivery | 651 days, 3,483 stocks (current) |
| BSE bars | 651 days, 7,239 stocks (current) |
| Total signals | 9,094 (9 buys, 30 avoids) |
| Market cap coverage | 8,019 / 9,094 (88%) |
| SME classification | 1,048 signals classified as SME |
| Paper trades | 7 open, 35 settled |
| Capital deployed | ₹6,99,015 / ₹40,00,000 (17.5%) |
| Realized P&L | +₹30,037 (+0.8%) |
| Journal sync | 35/35 settled, 0 missing, 0 orphans, 0 bps mismatch |
| Sync audit | ✓ synced (verified on every page load) |
| Tests | 228+ passing |
| Real RELIANCE history | 404 daily bars from NSE UDiFF bhavcopy CDN |
| Upstox REST V3 vs exchange closes | **30 days · drift 0.0000% · PASS** |
| Sandbox order lifecycle | place → modify → cancelled (order 260823192859042) |
| Broker reconciliation | orders/positions/funds IO live-verified · zero mismatches |
