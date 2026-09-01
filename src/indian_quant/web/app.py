"""FastAPI web dashboard for the NSE-BSE quant platform."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from indian_quant.config import load_settings
from indian_quant.web import data_loader as dl
from indian_quant.web import suggestion_loader as sl
from indian_quant.web.auth import (
    get_current_user_id,
    get_current_username,
    hash_password,
    require_login,
    verify_password,
)
from indian_quant.web.fast_loader import get_latest_signals_cached
from indian_quant.web.scheduler import get_scheduler_status, start_scheduler, stop_scheduler
from indian_quant.web.watchlist_store import WatchlistStore

app = FastAPI(title="NSE-BSE Quant Platform", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key="nse-bse-quant-9f8e7d6c5b4a3210-prod", max_age=86400 * 7)


@app.on_event("startup")
def _start_scheduler():
    import contextlib
    import threading
    def _delayed_start():
        import time
        time.sleep(5)
        with contextlib.suppress(Exception):
            start_scheduler()
    threading.Thread(target=_delayed_start, daemon=True).start()
    # Ensure default user exists for watchlist FK constraint
    try:
        ws = _ws()
        if not ws.get_user_by_username("admin"):
            ws.create_user("admin", "admin@local.dev", "dev-only-hash")
        ws.close()
    except Exception:
        pass


@app.on_event("shutdown")
def _stop_scheduler():
    stop_scheduler()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ws() -> WatchlistStore:
    settings = load_settings()
    db = Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))
    return WatchlistStore(db)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    papers = dl.get_paper_summary()
    gate = dl.get_gate_progress()
    signals = get_latest_signals_cached()
    sugg = sl.get_suggestion_summary()
    uid = get_current_user_id(request)
    watchlist_count = 0
    if uid:
        ws = _ws()
        watchlist_count = ws.symbol_count(uid)
        ws.close()
    # Per-horizon breakdown
    settings = load_settings()
    from indian_quant.storage import MetadataStore
    md = MetadataStore(settings.storage.metadata_dsn)
    sugg_by_hz = md.suggestions_by_horizon()
    md.close()
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "papers": papers,
        "gate": gate,
        "signals": signals,
        "sugg": sugg,
        "sugg_by_hz": sugg_by_hz,
        "username": get_current_username(request),
        "watchlist_count": watchlist_count,
    })


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    signals = get_latest_signals_cached()
    all_sigs = signals.get("all", [])
    # Pre-count market cap classes and segments for initial render
    from collections import Counter
    cap_counts = Counter(s.get("market_cap_class", "Other") for s in all_sigs)
    seg_counts = Counter(s.get("segment", "EQ") for s in all_sigs)
    return templates.TemplateResponse(request, "signals.html", {
        "request": request,
        "signals": {"date": signals.get("date", ""), "total": len(all_sigs)},
        "cap_counts": cap_counts,
        "seg_counts": seg_counts,
        "username": get_current_username(request),
    })


@app.get("/api/signals")
async def api_signals(
    cap: str = "All",
    sort: str = "score",
    order: str = "desc",
    signal_type: str = "All",
    segment: str = "All",
    page: int = 1,
    per_page: int = 50,
):
    from indian_quant.web.fast_loader import get_signals_for_api
    return get_signals_for_api(
        cap=cap, sort=sort, order=order,
        signal_type=signal_type, segment=segment,
        page=page, per_page=per_page,
    )


@app.get("/api/portfolio")
async def api_portfolio(
    horizon: str = "",
    status: str = "",
    limit: int = 200,
):
    settings = dl._settings()
    from indian_quant.storage import MetadataStore
    md = MetadataStore(settings.storage.metadata_dsn)
    pf = md.portfolio_summary()
    by_hz = md.paper_trades_by_horizon()
    trades = md.trade_log(
        horizon=horizon if horizon else None,
        status=status if status else None,
        limit=limit,
    )
    md.close()
    return {"portfolio": pf, "by_horizon": by_hz, "trades": trades}


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    horizon = request.query_params.get("horizon", "")
    status = request.query_params.get("status", "")
    settings = dl._settings()
    from indian_quant.storage import MetadataStore
    md = MetadataStore(settings.storage.metadata_dsn)
    pf = md.portfolio_summary()
    by_hz = md.paper_trades_by_horizon()
    trades = md.trade_log(
        horizon=horizon if horizon else None,
        status=status if status else None,
        limit=100,
    )
    md.close()
    papers = dl.get_paper_summary()
    return templates.TemplateResponse(request, "positions.html", {
        "request": request,
        "papers": papers,
        "pf": pf,
        "by_hz": by_hz,
        "trades": trades,
        "filter_horizon": horizon,
        "filter_status": status,
        "username": get_current_username(request),
    })


@app.get("/research", response_class=HTMLResponse)
async def research_page(request: Request):
    research = dl.get_research_results()
    return templates.TemplateResponse(request, "research.html", {
        "request": request,
        "research": research,
        "username": get_current_username(request),
    })


@app.get("/sectors", response_class=HTMLResponse)
async def sectors_page(request: Request):
    return templates.TemplateResponse(request, "sectors.html", {
        "request": request,
        "username": get_current_username(request),
    })


@app.get("/risk", response_class=HTMLResponse)
async def risk_page(request: Request):
    return templates.TemplateResponse(request, "risk.html", {
        "request": request,
        "username": get_current_username(request),
    })


@app.get("/suggestions", response_class=HTMLResponse)
async def suggestions_page(request: Request):
    settings = dl._settings()
    from indian_quant.storage import MetadataStore
    md = MetadataStore(settings.storage.metadata_dsn)
    summary = md.suggestions_summary()
    import sqlite3 as _sq
    con = _sq.connect(str(Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))))
    con.row_factory = _sq.Row
    recent = [dict(r) for r in con.execute(
        "SELECT * FROM daily_suggestions ORDER BY suggestion_date DESC, symbol LIMIT 100"
    ).fetchall()]
    by_type = [dict(r) for r in con.execute(
        """SELECT signal_type, COUNT(*) n, AVG(actual_return_bps) avg_net,
           SUM(hit)*1.0/COUNT(*)*100 accuracy
           FROM daily_suggestions WHERE status='REALIZED'
           GROUP BY signal_type ORDER BY avg_net DESC"""
    ).fetchall()]
    con.close()
    # Get cached signals for market cap breakdown
    cached_signals = get_latest_signals_cached()
    all_signals = cached_signals.get("all", [])
    return templates.TemplateResponse(request, "suggestions.html", {
        "request": request,
        "summary": summary,
        "recent": recent,
        "by_type": by_type,
        "signals": all_signals,
        "username": get_current_username(request),
    })


@app.get("/announcements/{symbol}", response_class=HTMLResponse)
async def announcements_page(request: Request, symbol: str):
    announcements = dl.get_announcements(symbol.upper())
    available = dl.get_available_announcement_symbols()
    return templates.TemplateResponse(request, "announcements.html", {
        "request": request,
        "symbol": symbol.upper(),
        "announcements": announcements,
        "available_symbols": available,
        "username": get_current_username(request),
    })


# ── Auth Routes ──────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if get_current_user_id(request):
        return RedirectResponse("/watchlist", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "request": request, "error": error,
    })


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ws = _ws()
    user = ws.get_user_by_username(username.strip())
    ws.close()
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {
            "request": request, "error": "Invalid username or password",
        }, status_code=401)
    request.session["user_id"] = user["user_id"]
    request.session["username"] = user["username"]
    return RedirectResponse("/watchlist", status_code=303)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    if get_current_user_id(request):
        return RedirectResponse("/watchlist", status_code=303)
    return templates.TemplateResponse(request, "register.html", {
        "request": request, "error": error,
    })


@app.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    username = username.strip()
    email = email.strip()

    if not re.match(r"^[a-zA-Z0-9_]{3,30}$", username):
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Username: 3-30 chars, letters/numbers/underscore only",
        }, status_code=400)
    if "@" not in email or "." not in email:
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Invalid email address",
        }, status_code=400)
    if len(password) < 8:
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Password must be at least 8 characters",
        }, status_code=400)
    if password != password2:
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Passwords do not match",
        }, status_code=400)

    ws = _ws()
    if ws.username_exists(username):
        ws.close()
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Username already taken",
        }, status_code=400)
    if ws.email_exists(email):
        ws.close()
        return templates.TemplateResponse(request, "register.html", {
            "request": request, "error": "Email already registered",
        }, status_code=400)

    ws.create_user(username, email, hash_password(password))
    ws.close()
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ── Watchlist Routes ────────────────────────────────────────────────

@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request):
    uid = require_login(request)
    ws = _ws()
    stocks = ws.list_stocks(uid)
    signals = ws.get_all_signals_for_user(uid)
    signal_map = {s["symbol"]: s for s in signals}
    ws.close()
    return templates.TemplateResponse(request, "watchlist.html", {
        "request": request,
        "username": get_current_username(request),
        "stocks": stocks,
        "signal_map": signal_map,
    })


@app.get("/stock/{symbol}", response_class=HTMLResponse)
async def stock_detail_page(request: Request, symbol: str):
    uid = get_current_user_id(request)
    from indian_quant.web.stock_analysis import get_stock_analysis
    analysis = get_stock_analysis(symbol.upper(), uid)
    if analysis is None:
        return templates.TemplateResponse(request, "stock_detail.html", {
            "request": request, "symbol": symbol.upper(),
            "analysis": None, "username": get_current_username(request),
        })
    return templates.TemplateResponse(request, "stock_detail.html", {
        "request": request,
        "symbol": symbol.upper(),
        "analysis": analysis,
        "username": get_current_username(request),
    })


# ── Watchlist API ───────────────────────────────────────────────────

@app.post("/api/watchlist/add")
async def api_watchlist_add(request: Request):
    uid = require_login(request)
    body = await request.json()
    symbol = body.get("symbol", "").strip().upper()
    notes = body.get("notes", "")
    if not symbol:
        return JSONResponse({"error": "symbol required"}, status_code=400)
    # Allow any valid NSE symbol (letters, numbers, ampersand, hyphen)
    if not all(c.isalnum() or c in ("&", "-", "_") for c in symbol):
        return JSONResponse({"error": "Invalid symbol format"}, status_code=400)
    ws = _ws()
    try:
        wl_id = ws.add_stock(uid, symbol, notes)
        ws.close()
        return JSONResponse({"ok": True, "watchlist_id": wl_id})
    except Exception as e:
        ws.close()
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/watchlist/remove")
async def api_watchlist_remove(request: Request):
    uid = require_login(request)
    body = await request.json()
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return JSONResponse({"error": "symbol required"}, status_code=400)
    ws = _ws()
    ws.remove_stock(uid, symbol)
    ws.close()
    return JSONResponse({"ok": True})


@app.get("/api/watchlist")
async def api_watchlist_list(request: Request):
    uid = require_login(request)
    ws = _ws()
    stocks = ws.list_stocks(uid)
    signals = ws.get_all_signals_for_user(uid)
    ws.close()
    return JSONResponse({"stocks": stocks, "signals": signals})


@app.get("/api/search")
async def api_search_stocks(q: str = "", limit: int = 20):
    q = q.strip().upper()
    if len(q) < 1:
        return JSONResponse([])
    settings = load_settings()
    seen = set()
    matches = []

    nse_dl_dir = settings.normalized_dir / "delivery" / "NSE"
    bse_dl_dir = settings.normalized_dir / "delivery" / "BSE"

    def has_delivery_data(sym: str) -> bool:
        return (
            (nse_dl_dir / f"{sym}.parquet").exists() if nse_dl_dir.exists() else False
        ) or (
            (bse_dl_dir / f"{sym}.parquet").exists() if bse_dl_dir.exists() else False
        )

    # 1) NSE delivery parquet files
    if nse_dl_dir.exists():
        for p in sorted(nse_dl_dir.glob("*.parquet")):
            sym = p.stem
            if q in sym and sym not in seen:
                matches.append({"symbol": sym, "exchange": "NSE", "segment": "EQ", "has_data": True})
                seen.add(sym)
            if len(matches) >= limit:
                break

    # 2) BSE delivery parquet files
    if bse_dl_dir.exists() and len(matches) < limit:
        for p in sorted(bse_dl_dir.glob("*.parquet")):
            sym = p.stem
            if q in sym and sym not in seen:
                matches.append({"symbol": sym, "exchange": "BSE", "segment": "EQ", "has_data": True})
                seen.add(sym)
            if len(matches) >= limit:
                break

    # 3) Universe registry (broader set, may not have data yet)
    reg_path = settings.data_root / "universe" / "registry.json"
    if reg_path.exists() and len(matches) < limit:
        try:
            import json as _json
            reg = _json.loads(reg_path.read_text())
            for sym, info in reg.get("symbols", {}).items():
                if q in sym and sym not in seen:
                    matches.append({
                        "symbol": sym,
                        "exchange": info.get("exchange", "NSE"),
                        "segment": info.get("segment", "EQ"),
                        "has_data": has_delivery_data(sym),
                    })
                    seen.add(sym)
                if len(matches) >= limit:
                    break
        except Exception:
            pass

    # 4) Instruments table (database)
    if len(matches) < limit:
        try:
            import sqlite3 as _sq
            db = Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))
            if db.exists():
                con = _sq.connect(str(db))
                rows = con.execute(
                    "SELECT DISTINCT symbol, exchange, segment FROM instruments WHERE symbol LIKE ? LIMIT ?",
                    (f"%{q}%", limit),
                ).fetchall()
                con.close()
                for sym, exch, seg in rows:
                    if sym not in seen:
                        matches.append({
                            "symbol": sym, "exchange": exch, "segment": seg,
                            "has_data": has_delivery_data(sym),
                        })
                        seen.add(sym)
        except Exception:
            pass

    return JSONResponse(matches[:limit])


# ── Professional Quant Layer API Endpoints ──

import math
from datetime import datetime, date

def _clean_nan(obj):
    """Convert NaN/Inf floats and datetime to JSON-safe values."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


@app.get("/api/fundamentals/{symbol}")
async def api_fundamentals(symbol: str):
    """Get fundamental data for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        # Key ratios
        kr = conn.execute(
            sa.text("SELECT * FROM key_ratios WHERE symbol = :s"), {"s": symbol}
        ).mappings().fetchone()

        # Company profile
        cp = conn.execute(
            sa.text("SELECT * FROM company_profile WHERE symbol = :s"), {"s": symbol}
        ).mappings().fetchone()

        # Quarterly financials
        qf = conn.execute(
            sa.text("SELECT * FROM quarterly_financials WHERE symbol = :s ORDER BY period DESC LIMIT 8"),
            {"s": symbol}
        ).mappings().fetchall()

    result = {
        "symbol": symbol,
        "key_ratios": dict(kr) if kr else None,
        "company_profile": dict(cp) if cp else None,
        "quarterly_financials": [dict(q) for q in qf],
    }
    return JSONResponse(_clean_nan(result))


@app.get("/api/institutional/{symbol}")
async def api_institutional(symbol: str):
    """Get institutional flow data for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        # Shareholding history
        sh = conn.execute(
            sa.text("SELECT * FROM shareholding_history WHERE symbol = :s ORDER BY quarter DESC LIMIT 4"),
            {"s": symbol}
        ).mappings().fetchall()

        # Insider trades
        it = conn.execute(
            sa.text("SELECT * FROM insider_trades WHERE symbol = :s ORDER BY trade_date DESC LIMIT 20"),
            {"s": symbol}
        ).mappings().fetchall()

        # Promoter pledge
        pp = conn.execute(
            sa.text("SELECT * FROM promoter_pledge WHERE symbol = :s"), {"s": symbol}
        ).mappings().fetchone()

        # Bulk deals
        bd = conn.execute(
            sa.text("SELECT * FROM bulk_deals WHERE symbol = :s ORDER BY deal_date DESC LIMIT 10"),
            {"s": symbol}
        ).mappings().fetchall()

    result = {
        "symbol": symbol,
        "shareholding": [dict(s) for s in sh],
        "insider_trades": [dict(i) for i in it],
        "promoter_pledge": dict(pp) if pp else None,
        "bulk_deals": [dict(b) for b in bd],
    }
    return JSONResponse(_clean_nan(result))


@app.get("/api/fii-dii")
async def api_fii_dii():
    """Get FII/DII daily flow data."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT * FROM fii_dii_daily ORDER BY trade_date DESC LIMIT 30")
        ).mappings().fetchall()

    return JSONResponse(_clean_nan({"data": [dict(r) for r in rows]}))


@app.get("/api/sectors")
async def api_sectors():
    """Get sector performance data."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()

    with engine.connect() as conn:
        # Sector map with stock counts
        sectors = conn.execute(
            sa.text("""
                SELECT s.sector, COUNT(*) as stock_count,
                       AVG(k.pe_trailing) as avg_pe,
                       AVG(k.roe) as avg_roe,
                       AVG(k.debt_to_equity) as avg_de
                FROM sector_map s
                LEFT JOIN key_ratios k ON s.symbol = k.symbol
                WHERE s.sector IS NOT NULL
                GROUP BY s.sector
                ORDER BY stock_count DESC
            """)
        ).mappings().fetchall()

        # Latest sector daily
        daily = conn.execute(
            sa.text("""
                SELECT sector, trade_date, avg_return, avg_deliv_z, stock_count
                FROM sector_daily
                WHERE trade_date = (SELECT MAX(trade_date) FROM sector_daily)
                ORDER BY avg_return DESC
            """)
        ).mappings().fetchall()

    return JSONResponse(_clean_nan({
        "sectors": [dict(s) for s in sectors],
        "daily": [dict(d) for d in daily],
    }))


@app.get("/api/portfolio/risk")
async def api_portfolio_risk():
    """Get portfolio risk metrics."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()

    with engine.connect() as conn:
        risk = conn.execute(
            sa.text("SELECT * FROM portfolio_risk ORDER BY snapshot_date DESC LIMIT 1")
        ).mappings().fetchone()

    return JSONResponse(_clean_nan({"risk": dict(risk) if risk else None}))


@app.get("/api/stock/{symbol}/risk")
async def api_stock_risk(symbol: str):
    """Get risk metrics for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine
    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        risk = conn.execute(
            sa.text("SELECT * FROM stock_risk WHERE symbol = :s"), {"s": symbol}
        ).mappings().fetchone()

    return JSONResponse(_clean_nan({"symbol": symbol, "risk": dict(risk) if risk else None}))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/admin/scheduler")
async def admin_scheduler_status():
    return get_scheduler_status()


@app.post("/api/admin/refresh-cache")
async def admin_refresh_cache():
    import threading

    from indian_quant.web.scheduler import _full_cache_rebuild
    t = threading.Thread(target=_full_cache_rebuild, daemon=True)
    t.start()
    return {"status": "started", "message": "Cache rebuild running in background"}
