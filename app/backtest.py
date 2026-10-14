"""Event-driven backtester + reusable engine for walk-forward optimization.

Split into two phases so parameter sweeps are cheap:
  1. build_plan()  - one pass over the bars that computes the entry decisions
                     (direction/confidence/ATR/price). Stops don't affect entries,
                     so this is independent of rr / atr_mult / min_confidence.
  2. simulate_plan() - cheap trade simulation for any parameter set.
"""
from __future__ import annotations

import pandas as pd

from . import indicators, strategy
from .risk import RiskLimits, kelly_fraction, position_size


def build_plan(symbol: str, df: pd.DataFrame, stride: int = 3,
               regime_method: str | None = None) -> list[dict]:
    plan: list[dict] = []
    if df is None or len(df) < 80:
        return plan
    params = {"regime_method": regime_method} if regime_method else None
    full_feat = indicators.compute_features(df)
    for i in range(60, len(df), max(1, stride)):
        ctx = strategy.analyze(symbol, df, params=params, feat=full_feat.iloc[: i + 1])
        if ctx.get("action") not in ("BUY", "SELL"):
            continue
        close = float(df.iloc[i]["close"])
        plan.append({
            "i": i,
            "ts": int(df.index[i].timestamp()),
            "close": close,
            "atr": ctx.get("atr_raw") or close * 0.01,
            "action": ctx["action"],
            "direction": ctx["direction"],
            "confidence": float(ctx["confidence"]),
            "symbol": symbol,
        })
    return plan


def simulate_plan(plan: list[dict], df: pd.DataFrame, initial: float = 100_000.0,
                  risk_pct: float = 0.01, rr: float = 2.0, atr_mult: float = 1.5,
                  min_conf: float = 0.55, limits: RiskLimits | None = None,
                  start: int = 60) -> dict:
    limits = limits or RiskLimits()
    times = [int(t.timestamp()) for t in df.index]
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(df)
    plan_by = {p["i"]: p for p in plan}
    cash = initial
    pos: dict | None = None
    trades: list[dict] = []
    curve = [None] * (n - start)

    for k, i in enumerate(range(start, n)):
        hi, lo, cl = highs[i], lows[i], closes[i]
        if pos is not None:
            d = pos["dir"]
            exit_price = None
            if d > 0:
                if lo <= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif hi >= pos["target"]:
                    exit_price, reason = pos["target"], "target"
            else:
                if hi >= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif lo <= pos["target"]:
                    exit_price, reason = pos["target"], "target"
            if exit_price is not None:
                cash += d * pos["qty"] * exit_price
                pnl = (exit_price - pos["entry"]) * pos["qty"] * d
                trades.append({
                    "symbol": pos["symbol"], "side": "long" if d > 0 else "short",
                    "qty": pos["qty"], "entry_price": round(pos["entry"], 4),
                    "exit_price": round(float(exit_price), 4), "pnl": round(pnl, 2),
                    "pnl_pct": round((exit_price / pos["entry"] - 1) * d, 4),
                    "reason": reason, "ts": times[i],
                })
                pos = None

        if pos is None and i in plan_by and plan_by[i]["confidence"] >= min_conf:
            p = plan_by[i]
            d = p["direction"]
            risk_ps = atr_mult * p["atr"]
            if risk_ps > 0:
                stop = p["close"] - d * risk_ps
                target = p["close"] + d * rr * risk_ps
                kelly = kelly_fraction(0.5, rr, cap=0.25)
                s = position_size(cash, p["close"], stop, risk_pct, kelly, limits.max_position_pct)
                qty = s["qty"]
                if qty >= 1:
                    cash -= d * qty * p["close"]
                    pos = {"symbol": p["symbol"], "dir": d, "qty": qty,
                           "entry": p["close"], "stop": stop, "target": target}

        curve[k] = {"ts": times[i], "equity": cash + (pos["dir"] * pos["qty"] * cl if pos else 0.0)}

    if pos is not None:
        last = closes[-1]
        cash += pos["dir"] * pos["qty"] * last
        pnl = (last - pos["entry"]) * pos["qty"] * pos["dir"]
        trades.append({"symbol": pos["symbol"], "side": "long" if pos["dir"] > 0 else "short",
                       "qty": pos["qty"], "entry_price": round(pos["entry"], 4),
                       "exit_price": round(float(last), 4), "pnl": round(pnl, 2),
                       "pnl_pct": round((last / pos["entry"] - 1) * pos["dir"], 4),
                       "reason": "end", "ts": times[-1]})
        curve.append({"ts": times[-1], "equity": cash})

    from .stats import compute_stats
    return {"trades": trades, "stats": compute_stats(trades, curve), "curve": curve}


def run_backtest(symbol: str, df: pd.DataFrame, initial: float = 100_000.0,
                 risk_pct: float = 0.01, rr: float = 2.0, atr_mult: float = 1.5,
                 min_conf: float = 0.55, stride: int = 3,
                 limits: RiskLimits | None = None) -> dict:
    plan = build_plan(symbol, df, stride)
    for p in plan:
        p["symbol"] = symbol
    res = simulate_plan(plan, df, initial, risk_pct, rr, atr_mult, min_conf, limits)
    res["symbol"] = symbol
    res["plan_size"] = len(plan)
    res["params"] = {"risk_pct": risk_pct, "rr": rr, "atr_mult": atr_mult, "min_conf": min_conf}
    return res
