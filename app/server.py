"""FastAPI application: REST API + WebSocket + static dashboard."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (alerts as alerts_mod, analytics, backtest, elite, ideas, indicators,
               knowledge, microstructure, pulse, research, scanner, storage, strategy, stats,
               universe, warmup, wfo)
from .risk import PROFILES, profile_summary
from .alpaca import get_broker
from .analyst import Analyst
from .bot import TradingBot
from .config import WEB_DIR, settings
from .risk import RiskLimits

_opt_jobs: dict[str, dict] = {}
_opt_lock = threading.Lock()
_opt_pool = None


def _get_opt_pool():
    """Lazy ProcessPoolExecutor - keeps CPU-bound WFO off the event loop."""
    global _opt_pool
    if _opt_pool is None:
        from concurrent.futures import ProcessPoolExecutor
        _opt_pool = ProcessPoolExecutor(max_workers=2)
    return _opt_pool


class AppState:
    broker = None
    analyst = None
    bot = None
    sockets: set[WebSocket] = set()


state = AppState()


async def _broadcast(snap: dict) -> None:
    if not state.sockets:
        return
    dead = []
    payload = json.dumps(snap, default=str)
    for ws in list(state.sockets):
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        state.sockets.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    # Restore the persisted market (stocks | forex) before wiring the broker.
    mode = storage.get_setting("market_mode", settings.market_mode) or settings.market_mode
    mode = "forex" if str(mode).lower() == "forex" else "stocks"
    settings.market_mode = mode
    storage.set_market(mode)
    elite.set_market(mode)
    state.broker = get_broker(mode)
    state.analyst = Analyst()
    try:
        await universe.ensure_universe(state.broker)
    except Exception:  # noqa: BLE001
        pass
    state.bot = TradingBot(state.broker, state.analyst, on_update=_broadcast)
    if settings.start_bot_on_launch:
        await state.bot.start()
    yield
    await state.bot.stop()
    await state.analyst.close()
    await state.broker.close()
    if _opt_pool is not None:
        try:
            _opt_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(title="AI Trader", version="1.0.0", lifespan=lifespan)


# ------------------------------------------------------------------ models
class BotConfig(BaseModel):
    universe: list[str] | None = None
    scan_interval: int | None = None
    risk_per_trade: float | None = None
    max_position_pct: float | None = None
    max_open_positions: int | None = None
    max_gross_exposure_pct: float | None = None
    daily_loss_limit_pct: float | None = None
    max_trades_per_day: int | None = None
    min_confidence: float | None = None
    rr: float | None = None
    atr_mult: float | None = None


class BacktestReq(BaseModel):
    symbol: str = "AAPL"
    timeframe: str = "5Min"
    limit: int = 600
    risk_pct: float = 0.01
    rr: float = 2.0
    atr_mult: float = 1.5
    min_conf: float = 0.55
    stride: int = 3


class OptimizeReq(BaseModel):
    symbol: str = "AAPL"
    timeframe: str = "5Min"
    limit: int = 360
    stride: int = 14
    folds: int = 4
    regime_method: str = "hybrid"


class AlertReq(BaseModel):
    symbol: str
    kind: str = "price"          # price | change_pct | volume
    op: str = ">="               # > >= < <= ==
    value: float
    note: str | None = None


class ModeReq(BaseModel):
    mode: str                    # "stocks" | "forex"


class TrainReq(BaseModel):
    market: str | None = None    # defaults to the active market
    timeframe: str = "5Min"


class JournalReq(BaseModel):
    symbol: str
    side: str | None = None
    entry: float | None = None
    exit: float | None = None
    qty: float | None = None
    pnl: float | None = None
    rating: int | None = None
    tags: list[str] | None = None
    note: str | None = None


# ------------------------------------------------------------------ api
@app.get("/api/status")
async def status():
    return await state.bot.build_snapshot()


@app.get("/api/news")
async def news(limit: int = 40):
    return storage.recent_news(limit=limit)


@app.get("/api/decisions")
async def decisions(limit: int = 80, symbol: str | None = None):
    return storage.recent_decisions(limit=limit, symbol=symbol)


@app.get("/api/trades")
async def trades(limit: int = 200):
    return storage.recent_trades(limit=limit)


@app.get("/api/portfolio")
async def portfolio():
    return {
        "account": await state.broker.get_account(),
        "positions": await state.broker.get_positions(),
        "orders": await state.broker.get_orders(limit=50),
    }


@app.get("/api/tape")
async def tape():
    return state.bot.tape.snapshot()


@app.get("/api/market/depth")
async def market_depth(symbol: str = "AAPL", frames: int = 90):
    return state.bot.tape.build_heatmap(symbol.upper(), frames=min(max(10, frames), 120))


@app.get("/api/optimize/runs")
async def optimize_runs(limit: int = 30):
    return storage.recent_optimize_runs(limit=min(max(1, limit), 200))


@app.get("/api/optimize/runs/{run_id}")
async def optimize_run_detail(run_id: int):
    run = storage.get_optimize_run(run_id)
    if not run:
        return JSONResponse({"error": "unknown run"}, status_code=404)
    return run


@app.get("/api/optimize/{job_id}")
async def optimize_status(job_id: str):
    with _opt_lock:
        job = _opt_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return job


@app.post("/api/optimize")
async def optimize(req: OptimizeReq):
    job_id = uuid.uuid4().hex[:12]
    meta = {"symbol": req.symbol, "timeframe": req.timeframe, "method": req.regime_method,
            "bar_limit": req.limit, "stride": max(3, req.stride),
            "folds": max(2, min(req.folds, 6))}
    with _opt_lock:
        _opt_jobs[job_id] = {"status": "running", "created": time.time(), **meta}
    try:
        fut = _get_opt_pool().submit(
            wfo.run_walk_forward_job, req.symbol, req.timeframe, req.limit,
            meta["stride"], meta["folds"], req.regime_method)
    except Exception as e:  # noqa: BLE001
        with _opt_lock:
            _opt_jobs[job_id].update({"status": "error", "error": repr(e)})
        return {"job_id": job_id, "status": "error"}

    def _done(f):
        try:
            res = f.result()
        except Exception as e:  # noqa: BLE001
            job = {"status": "error", "error": repr(e)}
        else:
            run_id = None
            try:
                run_id = storage.save_optimize_run(
                    meta["symbol"], meta["timeframe"], meta["method"],
                    meta["bar_limit"], meta["stride"], meta["folds"], res)
            except Exception as e:  # noqa: BLE001
                job = {"status": "done", "result": res, "save_error": repr(e)}
            else:
                job = {"status": "done", "result": res, "run_id": run_id}
        with _opt_lock:
            _opt_jobs[job_id].update(job)

    fut.add_done_callback(_done)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/market/bars")
async def market_bars(symbol: str = "AAPL", timeframe: str = "5Min", limit: int = 300):
    if timeframe not in ("1Min", "5Min", "15Min", "30Min", "1Hour", "1Day"):
        timeframe = "5Min"
    df = await state.broker.get_bars(symbol, timeframe, limit)
    if df is None or df.empty:
        return JSONResponse({"error": "no data", "symbol": symbol}, status_code=404)
    feat = indicators.compute_features(df)
    vprof = indicators.volume_profile(feat.tail(150))
    pools = microstructure.liquidity_pools(feat)

    def line(col):
        return [{"time": int(t.timestamp()), "value": round(float(v), 4)}
                for t, v in zip(feat.index, feat[col]) if v == v]

    candles, volume = [], []
    for t, r in feat.iterrows():
        ts = int(t.timestamp())
        candles.append({"time": ts, "open": round(float(r["open"]), 4), "high": round(float(r["high"]), 4),
                        "low": round(float(r["low"]), 4), "close": round(float(r["close"]), 4)})
        up = r["close"] >= r["open"]
        volume.append({"time": ts, "value": float(r["volume"]),
                       "color": "rgba(38,166,154,0.5)" if up else "rgba(239,83,80,0.5)"})

    ctx = strategy.analyze(symbol, df, news_sentiment=state.bot.sentiment.get(symbol, 0.0))
    return {
        "symbol": symbol, "timeframe": timeframe,
        "candles": candles, "volume": volume,
        "overlays": {
            "vwap": line("vwap"), "vwap_upper": line("vwap_up"), "vwap_lower": line("vwap_dn"),
            "ema9": line("ema9"), "ema21": line("ema21"), "ema50": line("ema50"),
        },
        "volume_profile": vprof,
        "levels": pools,
        "analysis": {k: ctx.get(k) for k in
                     ("action", "confidence", "regime", "signals", "features", "reasons",
                      "stop", "target", "entry", "price")},
    }


@app.get("/api/stats/overall")
async def stats_overall():
    return stats.compute_stats(storage.all_trades(), storage.equity_series(limit=20000))


@app.get("/api/stats/daily")
async def stats_daily(limit: int = 60):
    return storage.daily_stats_series(limit=limit)


@app.get("/api/stats/equity")
async def stats_equity(since: float | None = None, limit: int = 20000):
    return storage.equity_series(since=since, limit=limit)


@app.get("/api/log")
async def get_log():
    return list(state.bot.log)[:100]


# ------------------------------------------------------------------ bot control
@app.post("/api/bot/start")
async def bot_start():
    await state.bot.start()
    return {"running": state.bot.running}


@app.post("/api/bot/stop")
async def bot_stop():
    await state.bot.stop()
    return {"running": state.bot.running}


@app.post("/api/bot/scan")
async def bot_scan():
    snap = await state.bot.scan_once()
    return {"ok": True, "account": snap["account"]}


@app.post("/api/mind/resume")
async def mind_resume():
    state.bot.mind.resume()
    state.bot.symbol_cooldown.clear()
    return {"ok": True, "psyche": state.bot.mind.snapshot()}


@app.post("/api/bot/config")
async def bot_config(cfg: BotConfig):
    if cfg.universe is not None:
        state.bot.set_universe([s for s in cfg.universe if s.strip()])
    if cfg.scan_interval:
        state.bot.scan_interval = max(5, cfg.scan_interval)
    lim = state.bot.limits
    for field in ("risk_per_trade", "max_position_pct", "max_open_positions",
                  "max_gross_exposure_pct", "daily_loss_limit_pct", "max_trades_per_day",
                  "min_confidence", "rr", "atr_mult"):
        v = getattr(cfg, field)
        if v is not None:
            setattr(lim, field, v)
    return {"universe": state.bot.universe, "limits": lim.__dict__, "scan_interval": state.bot.scan_interval}


@app.post("/api/bot/close/{symbol}")
async def bot_close(symbol: str):
    return await state.bot.close_symbol(symbol.upper())


@app.post("/api/backtest")
async def run_bt(req: BacktestReq):
    df = await state.broker.get_bars(req.symbol, req.timeframe, req.limit)
    return backtest.run_backtest(req.symbol, df, risk_pct=req.risk_pct, rr=req.rr,
                                 atr_mult=req.atr_mult, min_conf=req.min_conf, stride=req.stride)


# -------------------------------------------------------------- universe
@app.get("/api/universe")
async def get_universe(q: str | None = None, sector: str | None = None,
                       limit: int = 500, offset: int = 0):
    rows = storage.get_universe()
    if q:
        qu = q.upper()
        rows = [r for r in rows if qu in (r.get("symbol") or "") or qu in (r.get("name") or "").upper()]
    if sector:
        rows = [r for r in rows if r.get("sector") == sector]
    total = len(rows)
    off = max(0, offset)
    return {"total": total, "offset": off, "rows": rows[off:off + max(1, min(limit, 2000))],
            "sectors": universe.sector_breakdown()}


@app.post("/api/universe/refresh")
async def refresh_universe():
    n = await universe.ensure_universe(state.broker, force=True)
    return {"ok": True, "count": n, "sectors": universe.sector_breakdown()}


# -------------------------------------------------------------- scanner
@app.get("/api/scanner")
async def api_scanner(full: bool = False, sort: str = "dollar_volume", limit: int = 100,
                      min_price: float | None = None, max_price: float | None = None,
                      min_change_pct: float | None = None, max_change_pct: float | None = None,
                      min_volume: float | None = None, min_rel_volume: float | None = None,
                      sector: str | None = None, q: str | None = None):
    usyms = [r["symbol"] for r in storage.get_universe()] if full else None
    filt = {"min_price": min_price, "max_price": max_price,
            "min_change_pct": min_change_pct, "max_change_pct": max_change_pct,
            "min_volume": min_volume, "min_rel_volume": min_rel_volume,
            "sector": sector, "q": q}
    try:
        return await scanner.scan(state.broker, universe_syms=usyms, watchlist=state.bot.universe,
                                  full=full, filters=filt, sort=sort, limit=limit)
    except Exception:  # noqa: BLE001 - transient data/network errors
        return {"rows": [], "total_matched": 0, "gainers": [], "losers": [],
                "most_active": [], "scanned": 0, "universe_size": storage.universe_count(),
                "full": full, "sectors": []}


@app.get("/api/movers")
async def api_movers(top: int = 25):
    return await scanner.movers(state.broker, top=min(max(5, top), 50))


# -------------------------------------------------------------- research
@app.get("/api/research")
async def api_research(symbol: str = "AAPL"):
    sent = state.bot.sentiment.get(symbol.upper(), 0.0)
    try:
        return await research.research(state.broker, symbol, sentiment=sent)
    except Exception as e:  # noqa: BLE001 - transient data/network errors
        return {"symbol": symbol.upper(), "error": f"research unavailable: {e}"}


# -------------------------------------------------------------- ideas
_ideas_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/ideas")
async def api_ideas(limit: int | None = None, refresh: bool = False):
    now = time.time()
    if (not refresh and limit is None and _ideas_cache["data"] is not None
            and now - _ideas_cache["ts"] < 45):
        return _ideas_cache["data"]
    cands: list[str] = list(state.bot.universe)
    try:
        mv = await scanner.movers(state.broker, top=30)
        cands += [m["symbol"] for m in mv.get("gainers", []) + mv.get("losers", [])]
        ma = await scanner.most_active(state.broker, top=40)
        cands += [m["symbol"] for m in ma]
    except Exception:  # noqa: BLE001
        pass
    try:
        res = await ideas.ideas(state.broker, candidates=cands, sentiment=state.bot.sentiment,
                                market=state.bot.market, limit=limit)
    except Exception:  # noqa: BLE001 - transient data/network errors
        res = {"setups": [], "total": 0, "tip": "", "briefing": {}}
    if limit is None:
        _ideas_cache.update({"ts": now, "data": res})
    return res


# -------------------------------------------------------------- analytics
@app.get("/api/analytics")
async def api_analytics():
    try:
        account = await state.broker.get_account()
        positions = await state.broker.get_positions()
        return await analytics.portfolio_analytics(state.broker, account, positions, market=state.bot.market)
    except Exception as e:  # noqa: BLE001 - transient data/network errors
        return {"error": f"analytics unavailable: {e}"}


# -------------------------------------------------------------- alerts
@app.get("/api/alerts")
async def get_alerts(limit: int = 200):
    return {"alerts": storage.recent_alerts(limit=min(max(1, limit), 500)),
            "fired": list(state.bot.alerts_fired)[:30]}


@app.post("/api/alerts")
async def add_alert(req: AlertReq):
    aid = storage.add_alert({"symbol": req.symbol.upper(), "kind": req.kind, "op": req.op,
                             "value": req.value, "note": req.note})
    return {"ok": True, "id": aid}


@app.delete("/api/alerts/{alert_id}")
async def del_alert(alert_id: int):
    storage.delete_alert(alert_id)
    return {"ok": True}


@app.post("/api/alerts/{alert_id}/toggle")
async def toggle_alert(alert_id: int):
    rows = [a for a in storage.recent_alerts(limit=1000) if a["id"] == alert_id]
    if not rows:
        return JSONResponse({"error": "unknown alert"}, status_code=404)
    a = rows[0]
    if a.get("triggered"):
        storage.update_alert(alert_id, {"triggered": 0, "active": 1, "triggered_ts": None})
    else:
        storage.update_alert(alert_id, {"active": 0 if a.get("active") else 1})
    return {"ok": True}


@app.post("/api/alerts/evaluate")
async def eval_alerts():
    fired = await alerts_mod.evaluate(state.broker, notify=state.bot._notify)
    for a in fired:
        state.bot.alerts_fired.appendleft(a)
    return {"ok": True, "fired": fired}


# -------------------------------------------------------------- journal
@app.get("/api/journal")
async def get_journal(limit: int = 200, symbol: str | None = None):
    return {"entries": storage.recent_journal(limit=min(max(1, limit), 500), symbol=symbol)}


@app.post("/api/journal")
async def add_journal(req: JournalReq):
    jid = storage.add_journal(req.model_dump())
    return {"ok": True, "id": jid}


@app.delete("/api/journal/{entry_id}")
async def del_journal(entry_id: int):
    storage.delete_journal(entry_id)
    return {"ok": True}


# -------------------------------------------------------------- knowledge / coach
@app.get("/api/knowledge")
async def api_knowledge(q: str | None = None, category: str | None = None, limit: int = 500):
    return knowledge.search(q=q, category=category, limit=min(max(1, limit), 1000))


@app.get("/api/knowledge/categories")
async def api_knowledge_categories():
    return {"categories": knowledge.categories(), "stats": knowledge.stats()}


@app.get("/api/coach")
async def api_coach():
    psy = state.bot.mind.snapshot()
    try:
        account = await state.broker.get_account()
        positions = await state.broker.get_positions()
    except Exception:  # noqa: BLE001 - transient data/network errors
        account, positions = {}, []
    eq = float(account.get("equity") or 0) or 1.0
    gross = sum(abs(float(p.get("market_value") or 0)) for p in positions) / eq * 100
    decs = storage.recent_decisions(limit=1)
    regime = (decs[0].get("regime") if decs else "") or state.bot.market.get("label", "")
    ctx = {
        "drawdown_pct": -abs(float(psy.get("drawdown") or 0)),
        "win_rate": psy.get("win_rate"),
        "loss_streak": psy.get("loss_streak"),
        "trades": psy.get("trades_seen"),
        "mood": psy.get("state"),
        "regime": regime,
        "open_positions": len(positions),
        "gross_pct": round(gross, 1),
    }
    return knowledge.coach(ctx)


# -------------------------------------------------------------- pulse / profile
@app.get("/api/pulse")
async def api_pulse():
    news = storage.recent_news(limit=30)
    movers, ma = {}, []
    try:
        movers = await scanner.movers(state.broker, top=12)
        ma = await scanner.most_active(state.broker, top=12)
    except Exception:  # noqa: BLE001 - transient data/network errors
        pass
    return pulse.digest(news, movers, ma, _ideas_cache.get("data"))


@app.get("/api/pulse/talks")
async def api_pulse_talks(q: str | None = None, limit: int = 12):
    return {"talks": pulse.talks(q=q, limit=limit)}


@app.get("/api/profile")
async def api_profile_get():
    return {"current": state.bot.risk_profile, "profiles": profile_summary(),
            "limits": state.bot.limits.__dict__}


class ProfileReq(BaseModel):
    profile: str


@app.post("/api/profile")
async def api_profile_set(req: ProfileReq):
    if req.profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"unknown profile '{req.profile}'")
    return state.bot.set_risk_profile(req.profile)


# ------------------------------------------------------------------ ws + static
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    state.sockets.add(websocket)
    try:
        snap = await state.bot.build_snapshot()
        await websocket.send_text(json.dumps({"type": "snapshot", "data": snap}, default=str))
        tape = state.bot.tape.snapshot()
        await websocket.send_text(json.dumps({"type": "tape", "data": tape}, default=str))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        state.sockets.discard(websocket)


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
