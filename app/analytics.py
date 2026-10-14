"""Portfolio & risk analytics: exposure, sector allocation, concentration,
P&L attribution and drawdown / correlation risk.
"""
from __future__ import annotations

import math

import numpy as np

from . import storage, universe as universe_mod
from .alpaca import Broker


def _f(v, d=0.0) -> float:
    try:
        f = float(v)
        return d if f != f else f
    except (TypeError, ValueError):
        return d


def _trades_stats(trades: list[dict]) -> dict:
    done = [t for t in trades if t.get("pnl") is not None]
    if not done:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "net_pnl": 0.0}
    wins = [t for t in done if _f(t["pnl"]) > 0]
    losses = [t for t in done if _f(t["pnl"]) < 0]
    gp = sum(_f(t["pnl"]) for t in wins)
    gl = -sum(_f(t["pnl"]) for t in losses)
    net = gp - gl
    return {
        "trades": len(done),
        "win_rate": round(len(wins) / len(done), 4),
        "profit_factor": round(gp / gl, 3) if gl else (round(gp, 2) if gp else 0.0),
        "expectancy": round(net / len(done), 2),
        "avg_win": round(gp / len(wins), 2) if wins else 0.0,
        "avg_loss": round(gl / len(losses), 2) if losses else 0.0,
        "gross_profit": round(gp, 2), "gross_loss": round(gl, 2), "net_pnl": round(net, 2),
    }


def _equity_metrics(series: list[dict], daily: list[dict]) -> dict:
    eq = [_f(r.get("equity")) for r in series if _f(r.get("equity")) > 0]
    out = {"max_drawdown_pct": 0.0, "sharpe": 0.0, "volatility_pct": 0.0, "points": len(eq)}
    if len(eq) >= 2:
        peak, mdd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        out["max_drawdown_pct"] = round(mdd * 100, 2)
        rets = np.diff(eq) / np.array(eq[:-1])
        if len(rets) > 1 and rets.std() > 0:
            out["sharpe"] = round(float(rets.mean() / rets.std() * math.sqrt(252 * 390)), 2)
            out["volatility_pct"] = round(float(rets.std() * math.sqrt(252 * 390) * 100), 1)
    # prefer closed-day sharpe if we have daily stats
    dvals = [_f(r.get("pnl_pct")) for r in daily if r.get("pnl_pct") is not None]
    if len(dvals) >= 3:
        d = np.array(dvals)
        if d.std() > 0:
            out["sharpe_daily"] = round(float(d.mean() / d.std() * math.sqrt(252)), 2)
    return out


async def portfolio_analytics(broker: Broker, account: dict, positions: list[dict],
                              *, market: dict | None = None) -> dict:
    equity = _f(account.get("equity"))
    meta = storage.universe_meta()

    gross = 0.0
    net = 0.0
    by_symbol = []
    by_sector: dict[str, float] = {}
    for p in positions:
        mv = _f(p.get("market_value"))
        gross += abs(mv)
        net += mv
        sec = (meta.get(p["symbol"]) or {}).get("sector") or universe_mod.classify(p["symbol"])
        by_sector[sec] = by_sector.get(sec, 0.0) + abs(mv)
        by_symbol.append({
            "symbol": p["symbol"], "sector": sec,
            "market_value": round(mv, 2),
            "weight": round(abs(mv) / equity * 100, 2) if equity else 0.0,
            "unrealized_pl": round(_f(p.get("unrealized_pl")), 2),
            "unrealized_plpc": round(_f(p.get("unrealized_plpc")) * 100, 2),
            "qty": p.get("qty"),
        })
    by_symbol.sort(key=lambda x: -abs(x["market_value"]))

    weights = [abs(_f(p.get("market_value"))) / gross for p in positions] if gross else []
    hhi = round(sum(w * w for w in weights), 3)
    top_weight = round(max(weights) * 100, 2) if weights else 0.0
    top3 = round(sum(sorted(weights, reverse=True)[:3]) * 100, 2) if weights else 0.0

    sectors = [{"sector": s, "exposure": round(v, 2),
                "pct": round(v / gross * 100, 1) if gross else 0.0}
               for s, v in sorted(by_sector.items(), key=lambda kv: -kv[1])]

    # realized stats
    all_tr = storage.all_trades()
    daily = storage.daily_stats_series(limit=400)
    eq_series = storage.equity_series(limit=20000)
    tstats = _trades_stats(all_tr)
    emetrics = _equity_metrics(eq_series, daily)

    realized_by_sym: dict[str, float] = {}
    for t in all_tr:
        realized_by_sym[t["symbol"]] = realized_by_sym.get(t["symbol"], 0.0) + _f(t.get("pnl"))
    realized_top = [{"symbol": s, "pnl": round(v, 2)}
                    for s, v in sorted(realized_by_sym.items(), key=lambda kv: -abs(kv[1]))[:10]]

    # correlation among held symbols
    corr = {"labels": [], "matrix": []}
    syms = [p["symbol"] for p in positions][:12]
    if len(syms) >= 2:
        frames = await broker.get_bars_multi(syms, "1Day", 90)
        series = {}
        for s in syms:
            df = frames.get(s)
            if df is not None and len(df) > 20:
                series[s] = np.log(df["close"] / df["close"].shift(1)).dropna()
        if len(series) >= 2:
            import pandas as pd
            mat = pd.DataFrame(series).dropna()
            if len(mat) > 15:
                c = mat.corr()
                corr = {"labels": list(c.columns),
                        "matrix": [[round(float(x), 2) for x in row] for row in c.values]}

    return {
        "equity": round(equity, 2),
        "cash": round(_f(account.get("cash")), 2),
        "cash_pct": round(_f(account.get("cash")) / equity * 100, 1) if equity else 0.0,
        "gross_exposure": round(gross, 2),
        "net_exposure": round(net, 2),
        "gross_pct": round(gross / equity * 100, 1) if equity else 0.0,
        "net_pct": round(net / equity * 100, 1) if equity else 0.0,
        "day_pnl": round(_f(account.get("day_pnl")), 2),
        "open_positions": len(positions),
        "concentration": {"hhi": hhi, "top_weight_pct": top_weight, "top3_pct": top3},
        "positions": by_symbol,
        "sectors": sectors,
        "realized_top": realized_top,
        "trade_stats": tstats,
        "equity_metrics": emetrics,
        "correlation": corr,
        "market": market or {},
    }
