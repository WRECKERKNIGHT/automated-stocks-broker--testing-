"""Walk-forward optimization + Combinatorially Symmetric Cross-Validation (CSCV).

Honest overfitting diagnostics on top of the plan/simulate backtester:
  * walk_forward() - rolling train/test folds; report walk-forward efficiency
                     (out-of-sample objective / in-sample objective).
  * cscv()         - Lopez de Prado style PBO estimate: split the timeline into
                     S blocks, use every S/2 subset as "in-sample", rank the
                     in-sample winner out-of-sample. A high PBO means the
                     parameter search is fitting noise.

Everything is computed from a single build_plan() pass, so sweeps are cheap.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from .backtest import build_plan, simulate_plan
from .risk import RiskLimits

DEFAULT_GRID: list[dict] = [
    {"rr": rr, "atr_mult": am, "min_conf": mc, "risk_pct": 0.01}
    for rr in (1.5, 2.0, 3.0)
    for am in (1.0, 2.0)
    for mc in (0.4, 0.55, 0.7)
]

WARMUP = 60


def _slice(plan: list[dict], df: pd.DataFrame, i0: int, i1: int):
    sub = df.iloc[i0:i1]
    sub_plan = []
    for p in plan:
        if i0 <= p["i"] < i1:
            q = dict(p)
            q["i"] = p["i"] - i0
            sub_plan.append(q)
    return sub_plan, sub


def _evaluate(plan, df, i0, i1, params, initial, limits):
    sub_plan, sub = _slice(plan, df, i0, i1)
    if len(sub) < 10:
        return {"trades": [], "stats": {"num_trades": 0, "expectancy": 0.0,
                                        "total_pnl": 0.0, "win_rate": 0.0}, "curve": []}
    return simulate_plan(sub_plan, sub, initial, params.get("risk_pct", 0.01),
                         params["rr"], params["atr_mult"], params["min_conf"],
                         limits, start=1)


def _objective(stats: dict, min_trades: int) -> float:
    if stats.get("num_trades", 0) < min_trades:
        return -1e9
    return float(stats.get("expectancy", 0.0))


def _optimize(plan, df, i0, i1, grid, initial, limits, min_trades):
    best = None
    for params in grid:
        res = _evaluate(plan, df, i0, i1, params, initial, limits)
        score = _objective(res["stats"], min_trades)
        if best is None or score > best["score"]:
            best = {"params": params, "score": score, "stats": res["stats"]}
    return best


def walk_forward(symbol: str, df: pd.DataFrame, n_folds: int = 4, train_frac: float = 0.5,
                 stride: int = 3, initial: float = 100_000.0, grid: list[dict] | None = None,
                 min_trades: int = 4, regime_method: str | None = None,
                 limits: RiskLimits | None = None) -> dict:
    limits = limits or RiskLimits()
    grid = grid or DEFAULT_GRID
    plan = build_plan(symbol, df, stride, regime_method)
    for p in plan:
        p["symbol"] = symbol

    n = len(df)
    start = WARMUP
    span = n - start
    if span < n_folds * 40:
        return {"symbol": symbol, "error": "not enough data for walk-forward",
                "bars": n, "folds": []}

    step = span // n_folds
    folds = []
    is_scores, oos_scores = [], []
    for k in range(n_folds):
        w0 = start + k * step
        w1 = n if k == n_folds - 1 else w0 + step
        split = w0 + int((w1 - w0) * train_frac)
        best = _optimize(plan, df, w0, split, grid, initial, limits, min_trades)
        oos = _evaluate(plan, df, split, w1, best["params"], initial, limits)
        is_scores.append(best["score"])
        oos_scores.append(_objective(oos["stats"], min_trades))
        folds.append({
            "fold": k + 1,
            "train": [int(df.index[w0].timestamp()), int(df.index[split - 1].timestamp())],
            "test": [int(df.index[split].timestamp()), int(df.index[w1 - 1].timestamp())],
            "train_bars": split - w0,
            "test_bars": w1 - split,
            "best_params": best["params"],
            "is_expectancy": round(best["stats"].get("expectancy", 0.0), 2),
            "is_pnl": round(best["stats"].get("total_pnl", 0.0), 2),
            "is_trades": best["stats"].get("num_trades", 0),
            "oos_expectancy": round(oos["stats"].get("expectancy", 0.0), 2),
            "oos_pnl": round(oos["stats"].get("total_pnl", 0.0), 2),
            "oos_trades": oos["stats"].get("num_trades", 0),
        })

    valid_is = [s for s in is_scores if s > -1e8]
    valid_oos = [s for s in oos_scores if s > -1e8]
    mean_is = float(np.mean(valid_is)) if valid_is else 0.0
    mean_oos = float(np.mean(valid_oos)) if valid_oos else 0.0
    wfe = (mean_oos / mean_is) if mean_is > 0 else (0.0 if mean_oos <= 0 else None)
    oos_pnl = sum(f["oos_pnl"] for f in folds)

    full_best = _optimize(plan, df, start, n, grid, initial, limits, min_trades)
    cscv_res = cscv(plan, df, grid, initial, limits, 1, n)

    return {
        "symbol": symbol,
        "bars": n,
        "folds": folds,
        "summary": {
            "n_folds": n_folds,
            "mean_is_expectancy": round(mean_is, 2),
            "mean_oos_expectancy": round(mean_oos, 2),
            "walk_forward_efficiency": (round(wfe, 3) if wfe is not None else None),
            "oos_total_pnl": round(oos_pnl, 2),
            "degradation": (round(1 - wfe, 3) if wfe is not None else None),
            "best_full_sample_params": full_best["params"],
            "best_full_sample_expectancy": round(full_best["stats"].get("expectancy", 0.0), 2),
            "pbo": cscv_res["pbo"],
            "pbo_combos": cscv_res["n_combos"],
            "verdict": _verdict(wfe, cscv_res["pbo"], mean_oos),
        },
        "grid_size": len(grid),
    }


def cscv(plan, df, grid, initial=100_000.0, limits: RiskLimits | None = None,
         min_trades: int = 1, n: int | None = None, max_blocks: int = 4) -> dict:
    """Probability of Backtest Overfitting (approximation)."""
    limits = limits or RiskLimits()
    n = n if n is not None else len(df)
    start = WARMUP
    span = n - start
    S = max(4, min(max_blocks, span // 40))
    if S % 2 == 1:
        S -= 1
    if S < 4:
        return {"pbo": None, "n_combos": 0}

    edges = [start + round(i * span / S) for i in range(S + 1)]
    blocks = [(edges[i], edges[i + 1]) for i in range(S)]

    R = np.full((len(grid), S), 0.0)
    for ci, params in enumerate(grid):
        for bi, (b0, b1) in enumerate(blocks):
            res = _evaluate(plan, df, b0, b1, params, initial, limits)
            R[ci, bi] = float(res["stats"].get("expectancy", 0.0))

    half = S // 2
    combos = list(combinations(range(S), half))
    overfit = 0
    valid = 0
    for combo in combos:
        oos_blocks = [b for b in range(S) if b not in combo]
        is_scores = R[:, list(combo)].mean(axis=1)
        oos_sc = R[:, oos_blocks].mean(axis=1)
        if np.allclose(is_scores, is_scores[0]) or np.allclose(oos_sc, oos_sc[0]):
            continue
        best_ci = int(np.argmax(is_scores))
        order = np.argsort(oos_sc)
        rank = int(np.where(order == best_ci)[0][0]) / max(1, len(oos_sc) - 1)
        valid += 1
        if rank < 0.5:
            overfit += 1

    pbo = round(overfit / valid, 3) if valid else None
    return {"pbo": pbo, "n_combos": valid}


def _verdict(wfe, pbo, mean_oos) -> str:
    if pbo is None:
        return "insufficient data"
    if pbo >= 0.6:
        return "OVERFIT RISK - parameter selection likely fitting noise"
    if mean_oos <= 0 and wfe is not None and wfe <= 0:
        return "NO OUT-OF-SAMPLE EDGE - do not trust these parameters"
    if wfe is not None and wfe >= 0.6:
        return "PROMISING - edge holds out-of-sample (still paper-trade)"
    return "WEAK / MIXED - marginal out-of-sample robustness"


def run_walk_forward_job(symbol: str, timeframe: str, limit: int, stride: int,
                         folds: int, regime_method: str) -> dict:
    """Process-safe entrypoint: fetch data in a fresh event loop and run the WFO.

    Runs in a separate OS process (see server.py) so CPU-bound optimization never
    blocks the server's event loop / websocket broadcasts.
    """
    import asyncio

    from .alpaca import get_broker

    async def _go():
        broker = get_broker()
        try:
            df = await broker.get_bars(symbol, timeframe, limit)
        finally:
            try:
                await broker.close()
            except Exception:  # noqa: BLE001
                pass
        if df is None or df.empty:
            return {"error": "no data", "symbol": symbol}
        return walk_forward(symbol, df, n_folds=max(2, min(folds, 6)),
                            stride=max(3, stride), regime_method=regime_method)

    return asyncio.run(_go())
