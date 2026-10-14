"""Performance analytics - turns raw trades + equity curve into the numbers that
actually decide whether an edge exists.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict


def _max_drawdown(equity: list[float]) -> tuple[float, float]:
    peak = -math.inf
    max_dd = 0.0
    max_dd_pct = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = peak - e
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd / peak
    return max_dd, max_dd_pct


def _sharpe(equity: list[float]) -> float:
    if len(equity) < 4:
        return 0.0
    rets = [(equity[i] / equity[i - 1] - 1) for i in range(1, len(equity)) if equity[i - 1]]
    if len(rets) < 3:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    return float(mean / sd * math.sqrt(len(rets))) if sd > 0 else 0.0


def compute_stats(trades: list[dict], equity_pts: list[dict]) -> dict:
    closed = [t for t in trades if t.get("pnl") is not None]
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    n = len(pnls)
    win_rate = len(wins) / n if n else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = -sum(losses) / len(losses) if losses else 0.0  # positive
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if n else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)

    equity = [float(e["equity"]) for e in equity_pts if e.get("equity") is not None]
    max_dd, max_dd_pct = _max_drawdown(equity) if equity else (0.0, 0.0)
    start_eq = equity[0] if equity else 0.0
    end_eq = equity[-1] if equity else 0.0

    by_sym: dict[str, float] = defaultdict(float)
    for t in closed:
        by_sym[t["symbol"]] += float(t["pnl"])
    best = max(by_sym, key=by_sym.get) if by_sym else None
    worst = min(by_sym, key=by_sym.get) if by_sym else None

    # avg R-multiple if we know risk (approx via pnl_pct / typical)
    return {
        "num_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor != math.inf else 999.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "total_pnl": round(sum(pnls), 2),
        "total_pnl_pct": round((end_eq - start_eq) / start_eq, 4) if start_eq else 0.0,
        "start_equity": round(start_eq, 2),
        "end_equity": round(end_eq, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "sharpe": round(_sharpe(equity), 3),
        "best_symbol": best,
        "worst_symbol": worst,
        "by_symbol": {k: round(v, 2) for k, v in sorted(by_sym.items(), key=lambda x: -x[1])},
    }


def daily_stats(date: str, day_trades: list[dict], day_equity: list[dict], notes: str = "") -> dict:
    s = compute_stats(day_trades, day_equity)
    return {
        "date": date,
        "start_equity": s["start_equity"],
        "end_equity": s["end_equity"],
        "pnl": s["total_pnl"],
        "pnl_pct": s["total_pnl_pct"],
        "num_trades": s["num_trades"],
        "wins": s["wins"],
        "losses": s["losses"],
        "win_rate": s["win_rate"],
        "gross_profit": s["gross_profit"],
        "gross_loss": s["gross_loss"],
        "profit_factor": s["profit_factor"],
        "avg_win": s["avg_win"],
        "avg_loss": s["avg_loss"],
        "expectancy": s["expectancy"],
        "max_drawdown": s["max_drawdown"],
        "sharpe": s["sharpe"],
        "best_symbol": s["best_symbol"],
        "worst_symbol": s["worst_symbol"],
        "notes": notes,
    }
