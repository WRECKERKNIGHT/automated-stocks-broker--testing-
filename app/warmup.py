"""Learning-pipeline warm-up ("train").

The bot learns from three places at runtime:

  * the Gaussian-HMM regime model, fitted per symbol/timeframe (app/regime.py),
  * alpha-decay signal weights derived from realised outcomes (app/alpha.py),
  * the per-symbol feature/strategy caches the first scan otherwise builds cold.

Cool-start means the first scans fall back to the heuristic regime and pay the
fitting cost inline. This module pre-fits those models for the *active* market's
universe so the engine is warm the moment it starts trading - and exposes a
single ``POST /api/train`` entry point for the dashboard button.
"""
from __future__ import annotations

import asyncio
import json
import time

from . import regime, storage
from .alpaca import get_broker
from .config import settings

_STATUS_KEY = "warmup_status"


async def _timeout_apply(coro, seconds: float):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        return None


async def _warm_symbol(broker, sym: str, timeframe: str, limit: int,
                       per_symbol_timeout: float) -> tuple[str, dict]:
    try:
        df = await broker.get_bars(sym, timeframe, limit)
    except Exception as e:  # noqa: BLE001
        return sym, {"status": "error", "error": f"bars: {e}"}
    if df is None or df.empty or len(df) < 60:
        return sym, {"status": "skipped", "error": "insufficient history"}

    # Kick off the HMM fit (runs in the regime executor thread).
    regime.classify(df, method="hybrid", symbol=sym, timeframe=timeframe)
    deadline = time.time() + per_symbol_timeout
    status = "fitting"
    while time.time() < deadline:
        _, _, status = regime._get_hmm(df, sym, timeframe)  # noqa: SLF001
        if status in ("ready", "failed"):
            break
        await asyncio.sleep(0.4)
    out = regime.classify(df, method="hybrid", symbol=sym, timeframe=timeframe)
    return sym, {"status": status, "regime": out.get("regime"),
                 "method": out.get("method")}


async def warmup(market: str | None = None, symbols: list[str] | None = None,
                 timeframe: str = "5Min", limit: int = 260,
                 per_symbol_timeout: float = 30.0) -> dict:
    """Pre-fit the learning pipeline for one market and record the result."""
    mk = "forex" if str(market or settings.market()).lower() == "forex" else "stocks"
    universe = list(symbols or settings.watchlist_for(mk))
    broker = get_broker(mk)
    started = time.time()

    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(4)

    async def run(sym: str):
        async with sem:
            return await _warm_symbol(broker, sym, timeframe, limit, per_symbol_timeout)

    pairs = await asyncio.gather(*(run(s) for s in universe))
    for sym, info in pairs:
        results[sym] = info

    ready = sum(1 for v in results.values() if v.get("status") == "ready")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    skipped = sum(1 for v in results.values() if v.get("status") in ("skipped", "error"))
    timeout = sum(1 for v in results.values() if v.get("status") == "fitting")

    # Prime the alpha-decay weights so the first entries are already weighted.
    try:
        from . import alpha

        alpha.get_alpha_tracker().reset()
        weights = alpha.get_alpha_tracker().edge_weights(ttl=0)
    except Exception:  # noqa: BLE001
        weights = {}

    report = {
        "ts": time.time(),
        "market": mk,
        "timeframe": timeframe,
        "universe": len(universe),
        "ready": ready,
        "failed": failed,
        "skipped": skipped,
        "timeout": timeout,
        "elapsed": round(time.time() - started, 2),
        "combined_weights": weights,
        "symbols": results,
    }
    storage.set_setting(_STATUS_KEY, json.dumps(report, default=str))
    return report


def last_report() -> dict:
    raw = storage.get_setting(_STATUS_KEY, "{}") or "{}"
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}
