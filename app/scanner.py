"""Market scanner: gainers / losers / most-active + full-universe filtering.

Uses Alpaca's free screeners (movers, most-actives) as a cheap seed and batch
snapshots for breadth; a full-universe scan snapshots every tradable symbol in
chunks. Results are cached briefly so the dashboard can poll freely.
"""
from __future__ import annotations

import time
from typing import Any

from . import indicators, storage, universe as universe_mod
from .alpaca import AlpacaBroker, Broker
from .config import settings

_cache: dict[str, Any] = {"key": None, "ts": 0.0, "rows": [], "extra": {}}


def _f(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _metrics(sym: str, snap: dict, meta: dict) -> dict | None:
    daily = snap.get("dailyBar") or {}
    prev = snap.get("prevDailyBar") or {}
    trade = snap.get("latestTrade") or {}
    price = _f(trade.get("p")) or _f(daily.get("c"))
    if price <= 0:
        return None
    prev_c = _f(prev.get("c")) or _f(daily.get("c")) or price
    change = price - prev_c
    change_pct = (change / prev_c * 100) if prev_c else 0.0
    vol = _f(daily.get("v"))
    prev_vol = _f(prev.get("v")) or vol
    return {
        "symbol": sym,
        "name": (meta or {}).get("name") or sym,
        "sector": (meta or {}).get("sector") or universe_mod.classify(sym),
        "exchange": (meta or {}).get("exchange"),
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 3),
        "prev_close": round(prev_c, 4),
        "open": round(_f(daily.get("o")), 4),
        "day_high": round(_f(daily.get("h")), 4),
        "day_low": round(_f(daily.get("l")), 4),
        "vwap": round(_f(daily.get("vw")), 4),
        "volume": int(vol),
        "dollar_volume": round(vol * price, 0),
        "rel_volume": round(vol / prev_vol, 2) if prev_vol else 1.0,
        "trade_count": int(_f(daily.get("n"))),
        "spread": round(max(0.0, _f((snap.get("latestQuote") or {}).get("ap"))
                            - _f((snap.get("latestQuote") or {}).get("bp"))), 4),
    }


async def _alpaca_get(broker: Broker, path: str, **params) -> Any:
    if not isinstance(broker, AlpacaBroker):
        return {}
    from .config import settings as s
    try:
        return await broker._get(s.data_base, path, **params)
    except Exception:  # noqa: BLE001
        return {}


async def movers(broker: Broker, top: int = 30) -> dict:
    j = await _alpaca_get(broker, "/v1beta1/screener/stocks/movers", top=top)
    meta = storage.universe_meta()

    def pack(items):
        out = []
        for m in items or []:
            sym = m.get("symbol")
            out.append({"symbol": sym, "price": round(_f(m.get("price")), 4),
                        "change": round(_f(m.get("change")), 4),
                        "change_pct": round(_f(m.get("percent_change")), 3),
                        "sector": (meta.get(sym) or {}).get("sector") or universe_mod.classify(sym),
                        "name": (meta.get(sym) or {}).get("name") or sym})
        return out

    return {"gainers": pack(j.get("gainers")), "losers": pack(j.get("losers")),
            "updated": j.get("last_updated")}


async def most_active(broker: Broker, top: int = 30, by: str = "volume") -> list[dict]:
    j = await _alpaca_get(broker, "/v1beta1/screener/stocks/most-actives", top=top, by=by)
    meta = storage.universe_meta()
    out = []
    for m in (j.get("most_actives") or []):
        sym = m.get("symbol")
        out.append({"symbol": sym, "volume": int(_f(m.get("volume"))),
                    "trade_count": int(_f(m.get("trade_count"))),
                    "sector": (meta.get(sym) or {}).get("sector") or universe_mod.classify(sym),
                    "name": (meta.get(sym) or {}).get("name") or sym})
    return out


async def _gather_rows(broker: Broker, symbols: list[str], use_cache: bool = True) -> tuple[list[dict], dict]:
    """Snapshot a set of symbols -> metric rows (cached)."""
    key = "|".join(sorted(symbols))[:200] + f"#{len(symbols)}"
    now = time.time()
    if use_cache and _cache["key"] == key and (now - _cache["ts"] < settings.scanner_cache_sec):
        return _cache["rows"], _cache["extra"]

    snaps = {}
    try:
        snaps = await broker.get_snapshots(symbols)
    except Exception:  # noqa: BLE001 - transient data/network errors
        return [], {"scanned": len(symbols), "with_data": 0}
    meta = storage.universe_meta()
    rows = []
    for sym, snap in snaps.items():
        if not isinstance(snap, dict):
            continue
        m = _metrics(sym, snap, meta.get(sym))
        if m:
            rows.append(m)
    extra = {"scanned": len(symbols), "with_data": len(rows)}
    _cache.update({"key": key, "ts": now, "rows": rows, "extra": extra})
    return rows, extra


def _apply_filters(rows: list[dict], f: dict) -> list[dict]:
    q = (f.get("q") or "").strip().upper()
    sector = (f.get("sector") or "").strip()
    out = []
    for r in rows:
        if f.get("min_price") is not None and r["price"] < f["min_price"]:
            continue
        if f.get("max_price") is not None and r["price"] > f["max_price"]:
            continue
        if f.get("min_change_pct") is not None and r["change_pct"] < f["min_change_pct"]:
            continue
        if f.get("max_change_pct") is not None and r["change_pct"] > f["max_change_pct"]:
            continue
        if f.get("min_volume") is not None and r["volume"] < f["min_volume"]:
            continue
        if f.get("min_rel_volume") is not None and r["rel_volume"] < f["min_rel_volume"]:
            continue
        if sector and r.get("sector") != sector:
            continue
        if q and q not in (r["symbol"] or "") and q not in (r.get("name") or "").upper():
            continue
        out.append(r)
    return out


def _sort(rows: list[dict], sort: str) -> list[dict]:
    keys = {
        "change_pct": ("change_pct", True), "change_pct_asc": ("change_pct", False),
        "volume": ("volume", True), "dollar_volume": ("dollar_volume", True),
        "rel_volume": ("rel_volume", True), "price": ("price", True),
    }
    k, rev = keys.get(sort or "dollar_volume", ("dollar_volume", True))
    return sorted(rows, key=lambda r: r.get(k, 0), reverse=rev)


async def _enrich(broker: Broker, rows: list[dict], top: int) -> None:
    """Attach RSI / ATR% / trend to the top slice using one multi-bars call."""
    syms = [r["symbol"] for r in rows[:top]]
    if not syms:
        return
    data = await broker.get_bars_multi(syms, "1Day", 60)
    for r in rows[:top]:
        df = data.get(r["symbol"])
        if df is None or len(df) < 15:
            continue
        feat = indicators.compute_features(df)
        last = feat.iloc[-1]
        r["rsi"] = round(_f(last.get("rsi"), 50), 1)
        r["atr_pct"] = round(_f(last.get("atr_pct")) * 100, 2)
        sma50 = _f(last.get("ema50"))
        r["trend"] = "up" if r["price"] > sma50 > 0 else ("down" if r["price"] < sma50 else "flat")


async def scan(broker: Broker, *, universe_syms: list[str] | None = None, watchlist: list[str] | None = None,
               full: bool = False, filters: dict | None = None, sort: str = "dollar_volume",
               limit: int = 100, enrich_top: int | None = None) -> dict:
    """Run a market scan and return filtered/sorted rows plus screener lists."""
    filters = filters or {}
    watchlist = [s.upper() for s in (watchlist or [])]
    mv = await movers(broker, top=50)
    ma = await most_active(broker, top=100)
    seed = set(watchlist)
    seed |= {m["symbol"] for m in mv.get("gainers", []) + mv.get("losers", [])}
    seed |= {m["symbol"] for m in ma}
    seed |= set(settings.cross_asset_symbols)
    if full and universe_syms:
        seed |= {s.upper() for s in universe_syms}
    seed = {s for s in seed if s}
    rows, extra = await _gather_rows(broker, sorted(seed))
    rows = _sort(_apply_filters(rows, filters), sort)
    limit = max(1, min(limit, 500))
    top_rows = rows[:limit]
    await _enrich(broker, top_rows, enrich_top if enrich_top is not None else settings.scanner_enrich_top)

    # attach live price to screener lists for display
    by_sym = {r["symbol"]: r for r in _cache["rows"]}
    for lst in (mv.get("gainers", []), mv.get("losers", [])):
        for item in lst:
            r = by_sym.get(item["symbol"])
            if r:
                item.update({"volume": r["volume"], "dollar_volume": r["dollar_volume"],
                             "rel_volume": r["rel_volume"]})
    for item in ma:
        r = by_sym.get(item["symbol"])
        if r:
            item.update({"price": r["price"], "change_pct": r["change_pct"]})

    return {
        "rows": top_rows,
        "total_matched": len(rows),
        "gainers": mv.get("gainers", [])[:40],
        "losers": mv.get("losers", [])[:40],
        "most_active": ma[:40],
        "scanned": extra.get("scanned", 0),
        "with_data": extra.get("with_data", 0),
        "universe_size": storage.universe_count(),
        "full": full,
        "updated": time.time(),
        "sectors": _sector_counts(_cache["rows"]),
    }


def _sector_counts(rows: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    chg: dict[str, list[float]] = {}
    for r in rows:
        s = r.get("sector") or "Other"
        counts[s] = counts.get(s, 0) + 1
        chg.setdefault(s, []).append(r["change_pct"])
    out = [{"sector": s, "count": n, "avg_change": round(sum(chg[s]) / len(chg[s]), 2)} for s, n in counts.items()]
    return sorted(out, key=lambda x: -x["count"])
