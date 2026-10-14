"""Alerts: evaluate user-defined (and rule-based) alerts against live prices."""
from __future__ import annotations

import time
from typing import Callable

from . import storage
from .alpaca import Broker


def _f(v, d=0.0) -> float:
    try:
        f = float(v)
        return d if f != f else f
    except (TypeError, ValueError):
        return d


def _cmp(op: str, a: float, b: float) -> bool:
    return {
        ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "==": a == b,
    }.get(op, False)


async def evaluate(broker: Broker, notify: Callable[[str, str], None] | None = None) -> list[dict]:
    """Check active alerts against the latest market data; fire the ones hit."""
    alerts = storage.active_alerts()
    if not alerts:
        return []
    syms = sorted({a["symbol"] for a in alerts if a.get("symbol")})
    try:
        snaps = await broker.get_snapshots(syms)
    except Exception:  # noqa: BLE001
        return []

    fired: list[dict] = []
    for a in alerts:
        snap = snaps.get(a["symbol"])
        if not isinstance(snap, dict):
            continue
        price = _f((snap.get("latestTrade") or {}).get("p")) or _f((snap.get("dailyBar") or {}).get("c"))
        if price <= 0:
            continue
        prev = _f((snap.get("prevDailyBar") or {}).get("c")) or price
        change_pct = (price / prev - 1) * 100 if prev else 0.0
        vol = _f((snap.get("dailyBar") or {}).get("v"))

        kind = a.get("kind")
        op = a.get("op") or ">="
        val = _f(a.get("value"))
        hit = False
        if kind == "price":
            hit = _cmp(op, price, val)
        elif kind == "change_pct":
            hit = _cmp(op, change_pct, val)
        elif kind == "volume":
            hit = _cmp(op, vol, val)

        storage.update_alert(a["id"], {"last_price": round(price, 4)})
        if hit:
            row = {**a, "last_price": round(price, 4), "change_pct": round(change_pct, 2),
                   "triggered_ts": time.time()}
            storage.update_alert(a["id"], {"triggered": 1, "triggered_ts": time.time(),
                                           "last_price": round(price, 4)})
            fired.append(row)
            if notify:
                label = {"price": f"price {op} {val}", "change_pct": f"change {op} {val}%",
                         "volume": f"volume {op} {val:,.0f}"}.get(kind, kind)
                notify(f"ALERT {a['symbol']} triggered: {label} (now {price:.2f})", "trade")
    return fired
