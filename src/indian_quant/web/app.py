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
    with contextlib.suppress(Exception):
        start_scheduler()
    # Ensure default user exists for watchlist FK constraint
    try:
        ws = _ws()
        if not ws.get_user_by_username("admin"):
            ws.create_user("admin", "admin@local.dev", "dev-only-hash")
            logger.info("Created default admin user")
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
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "papers": papers,
        "gate": gate,
        "signals": signals,
        "sugg": sugg,
        "username": get_current_username(request),
        "watchlist_count": watchlist_count,
    })


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    signals = get_latest_signals_cached()
    return templates.TemplateResponse(request, "signals.html", {
        "request": request,
        "signals": signals,
        "username": get_current_username(request),
    })


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    papers = dl.get_paper_summary()
    gate = dl.get_gate_progress()
    return templates.TemplateResponse(request, "positions.html", {
        "request": request,
        "papers": papers,
        "gate": gate,
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
