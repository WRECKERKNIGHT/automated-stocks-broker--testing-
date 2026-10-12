"""Broker / data access.

Two implementations behind one interface:
  * AlpacaBroker - real US stocks + paper-trading account via the Alpaca REST API
  * DemoBroker   - fully working synthetic market + virtual paper account, used
                   automatically when no Alpaca keys are configured.

Everything is async (httpx) and dependency-light (no alpaca SDK).
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np
import pandas as pd

from .config import settings

# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
_TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60, "1Day": 390}


def _parse_ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC")


def _df_from_alpaca(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    rows = []
    for b in bars:
        rows.append({
            "t": pd.Timestamp(b["t"]),
            "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"],
        })
    df = pd.DataFrame(rows).set_index("t")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


# ----------------------------------------------------------------------------
# interface
# ----------------------------------------------------------------------------
class Broker:
    mode = "DEMO"

    async def get_account(self) -> dict: ...
    async def get_positions(self) -> list[dict]: ...
    async def get_orders(self, limit: int = 50) -> list[dict]: ...
    async def submit_order(self, **kw) -> dict: ...
    async def close_position(self, symbol: str) -> dict: ...
    async def get_clock(self) -> dict: ...
    async def get_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 300) -> pd.DataFrame: ...
    async def get_snapshots(self, symbols: list[str]) -> dict[str, dict]: ...
    async def get_bars_multi(self, symbols: list[str], timeframe: str = "1Day",
                             limit: int = 30) -> dict[str, pd.DataFrame]: ...
    async def get_latest_price(self, symbol: str) -> float: ...
    async def get_news(self, symbols: list[str] | None = None, limit: int = 30) -> list[dict]: ...
    async def close(self) -> None: ...


# ----------------------------------------------------------------------------
# Alpaca (real)
# ----------------------------------------------------------------------------
class AlpacaBroker(Broker):
    mode = "PAPER"

    def __init__(self) -> None:
        self.mode = "PAPER" if settings.alpaca_paper else "LIVE"
        self._client = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
                "accept": "application/json",
            },
        )

    async def _get(self, base: str, path: str, **params) -> Any:
        r = await self._client.get(base + path, params=params)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, json: dict) -> Any:
        r = await self._client.post(settings.trading_base + path, json=json)
        r.raise_for_status()
        return r.json()

    async def get_account(self) -> dict:
        a = await self._get(settings.trading_base, "/v2/account")
        equity = float(a["equity"])
        last_eq = float(a.get("last_equity", equity))
        return {
            "equity": equity,
            "cash": float(a["cash"]),
            "buying_power": float(a["buying_power"]),
            "day_pnl": equity - last_eq,
            "day_pnl_pct": (equity - last_eq) / last_eq if last_eq else 0.0,
            "currency": a.get("currency", "USD"),
            "blocked": a.get("trading_blocked", False),
        }

    async def get_positions(self) -> list[dict]:
        ps = await self._get(settings.trading_base, "/v2/positions")
        out = []
        for p in ps:
            out.append({
                "symbol": p["symbol"],
                "qty": float(p["qty"]),
                "avg_entry": float(p["avg_entry_price"]),
                "current_price": float(p.get("current_price") or 0),
                "market_value": float(p.get("market_value") or 0),
                "unrealized_pl": float(p.get("unrealized_pl") or 0),
                "unrealized_plpc": float(p.get("unrealized_plpc") or 0),
            })
        return out

    async def get_orders(self, limit: int = 50) -> list[dict]:
        os_ = await self._get(settings.trading_base, "/v2/orders", status="all", limit=limit, direction="desc")
        return [{
            "id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": o.get("qty"),
            "type": o["type"], "status": o["status"], "filled_qty": o.get("filled_qty"),
            "filled_avg_price": o.get("filled_avg_price"), "submitted_at": o.get("submitted_at"),
        } for o in os_]

    async def submit_order(self, symbol: str, qty: int, side: str, order_class: str = "simple",
                           stop_loss: dict | None = None, take_profit: dict | None = None,
                           limit_price: float | None = None, type: str = "market") -> dict:
        body: dict[str, Any] = {
            "symbol": symbol, "qty": str(int(qty)), "side": side,
            "type": type, "time_in_force": "day",
        }
        if type == "limit" and limit_price:
            body["limit_price"] = f"{limit_price:.2f}"
        if order_class == "bracket" and stop_loss and take_profit:
            body["order_class"] = "bracket"
            body["stop_loss"] = {"stop_price": f"{stop_loss['stop']:.2f}"}
            body["take_profit"] = {"limit_price": f"{take_profit['target']:.2f}"}
        return await self._post("/v2/orders", body)

    async def close_position(self, symbol: str) -> dict:
        r = await self._client.delete(settings.trading_base + f"/v2/positions/{symbol}")
        r.raise_for_status()
        return r.json() if r.content else {}

    async def get_clock(self) -> dict:
        c = await self._get(settings.trading_base, "/v2/clock")
        return {"is_open": c["is_open"], "timestamp": c["timestamp"],
                "next_open": c["next_open"], "next_close": c["next_close"]}

    async def get_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 300) -> pd.DataFrame:
        # Alpaca defaults to the *current* day when no start is given, which is
        # empty on weekends / holidays / pre-market. Always send a wide-enough
        # window and sort desc (newest first) so we get exactly the latest bars.
        minutes = _TF_MINUTES.get(timeframe, 5)
        bars_per_day = 1 if timeframe == "1Day" else max(1, int(390 / minutes))
        days = int((limit / bars_per_day) * 7 / 5) + 5
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"timeframe": timeframe, "limit": min(limit, 10000), "feed": settings.data_feed,
                  "adjustment": "raw", "sort": "desc", "start": start}
        d = await self._get(settings.data_base, f"/v2/stocks/{symbol}/bars", **params)
        bars = d.get("bars") or []
        return _df_from_alpaca(list(reversed(bars)))

    async def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """Batch latest snapshots (free IEX feed). Chunked to stay within limits."""
        out: dict[str, dict] = {}
        syms = [s.upper() for s in symbols if s]
        for i in range(0, len(syms), 400):
            chunk = syms[i:i + 400]
            try:
                d = await self._get(settings.data_base, "/v2/stocks/snapshots",
                                    symbols=",".join(chunk), feed=settings.data_feed)
                if isinstance(d, dict):
                    out.update(d)
            except Exception:  # noqa: BLE001
                continue
        return out

    async def get_bars_multi(self, symbols: list[str], timeframe: str = "1Day",
                             limit: int = 30) -> dict[str, pd.DataFrame]:
        """Multiple symbols' bars in as few requests as possible (follows paging)."""
        out: dict[str, list] = {}
        syms = [s.upper() for s in symbols if s]
        minutes = _TF_MINUTES.get(timeframe, 5)
        bars_per_day = 1 if timeframe == "1Day" else max(1, int(390 / minutes))
        days = int((limit / bars_per_day) * 7 / 5) + 5
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(0, len(syms), 100):
            chunk = syms[i:i + 100]
            page_limit = min(10000, limit * len(chunk) + len(chunk))
            token = None
            guard = 0
            while guard < 200:
                guard += 1
                params = {"symbols": ",".join(chunk), "timeframe": timeframe,
                          "limit": page_limit, "feed": settings.data_feed,
                          "adjustment": "raw", "sort": "desc", "start": start}
                if token:
                    params["page_token"] = token
                try:
                    d = await self._get(settings.data_base, "/v2/stocks/bars", **params)
                except Exception:  # noqa: BLE001
                    break
                bysym = (d or {}).get("bars") or {}
                for sym, bars in bysym.items():
                    out.setdefault(sym, []).extend(bars)
                token = (d or {}).get("next_page_token")
                if not token:
                    break
        return {sym: _df_from_alpaca(list(reversed(bars))).tail(limit) for sym, bars in out.items()}

    async def get_latest_price(self, symbol: str) -> float:
        try:
            d = await self._get(settings.data_base, f"/v2/stocks/{symbol}/trades/latest", feed=settings.data_feed)
            return float(d["trade"]["p"])
        except Exception:
            df = await self.get_bars(symbol, "1Min", 5)
            return float(df["close"].iloc[-1]) if not df.empty else 0.0

    async def get_news(self, symbols: list[str] | None = None, limit: int = 30) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "sort": "desc", "exclude_contentless": "true"}
        if symbols:
            params["symbols"] = ",".join(symbols[:50])
        d = await self._get(settings.data_base, "/v1beta1/news", **params)
        out = []
        for n in d.get("news", []):
            out.append({
                "ts": _parse_ts(n["created_at"]).timestamp(),
                "headline": n.get("headline", ""),
                "summary": n.get("summary", ""),
                "source": n.get("source", ""),
                "url": n.get("url", ""),
                "symbols": n.get("symbols", []),
                "symbol": (n.get("symbols") or [None])[0],
            })
        return out

    async def close(self) -> None:
        await self._client.aclose()


# ----------------------------------------------------------------------------
# Demo (no keys required)
# ----------------------------------------------------------------------------
class DemoBroker(Broker):
    mode = "DEMO"
    START_EQUITY = 100_000.0

    def __init__(self) -> None:
        self._cash = self.START_EQUITY
        self._day_start_equity = self.START_EQUITY
        self._positions: dict[str, dict] = {}
        self._orders: list[dict] = []
        self._ooid = 0
        self._news: list[dict] = []
        self._news_ts = 0.0

    # ---- synthetic market data (deterministic per symbol/day) ----
    def _base_price(self, symbol: str) -> float:
        h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return 30 + (h % 470)

    def _gen_day(self, symbol: str, d: pd.Timestamp) -> pd.DataFrame:
        """Deterministic full trading-day session (390 x 1-min bars) for one day."""
        seed = int(hashlib.md5(f"{symbol}{d.date().isoformat()}".encode()).hexdigest()[:8], 16) % (2**32)
        rng = np.random.default_rng(seed)
        L = 390
        drift = np.zeros(L)
        vol = np.full(L, 0.0009)
        i = 0
        while i < L:
            seg = int(rng.integers(30, 120))
            drift[i:i + seg] = rng.normal(0, 0.0008)
            vol[i:i + seg] = rng.uniform(0.0005, 0.0022)
            i += seg
        rets = rng.normal(drift, vol)
        base = self._base_price(symbol)
        close = base * np.exp(np.cumsum(rets))
        hl = np.abs(rng.normal(0, vol * close))
        high = close + hl * rng.uniform(0.3, 1.0, L)
        low = close - hl * rng.uniform(0.3, 1.0, L)
        open_ = np.concatenate([[close[0]], close[:-1]])
        pos = np.arange(L) / L
        ushape = 0.5 + 2.5 * (2 * np.abs(pos - 0.5)) ** 2
        volume = (rng.lognormal(11, 0.5, L) * ushape).round()
        idx = pd.date_range(start=d + pd.Timedelta(hours=9, minutes=30), periods=L, freq="1min",
                            tz="America/New_York")
        return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                            index=idx)

    def _gen_1min(self, symbol: str, needed: int) -> pd.DataFrame:
        today = pd.Timestamp.now(tz="America/New_York").normalize()
        days: list[pd.Timestamp] = []
        d = today
        while len(days) * 390 < needed + 60:
            if d.weekday() < 5:
                days.append(d)
            d = d - pd.Timedelta(days=1)
            if len(days) > 40:
                break
        days = sorted(days)
        frames = [self._gen_day(symbol, dd) for dd in days]
        df = pd.concat(frames)
        now = pd.Timestamp.now(tz="America/New_York")
        if days and days[-1] == today:
            df = df[df.index <= now]
        return df

    async def get_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 300) -> pd.DataFrame:
        minute_bars = _TF_MINUTES.get(timeframe, 5)
        need = limit * minute_bars + 30
        df1 = self._gen_1min(symbol, need)
        if timeframe == "1Min":
            return df1.tail(limit)
        if timeframe == "1Day":
            rule = "1D"
        else:
            rule = f"{minute_bars}min"
        agg = df1.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        return agg.tail(limit)

    async def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """Synthesise snapshot-shaped data from the deterministic demo series."""
        out: dict[str, dict] = {}
        for sym in [s.upper() for s in symbols if s]:
            try:
                df = await self.get_bars(sym, "1Day", 2)
            except Exception:  # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            out[sym] = {
                "dailyBar": {"o": float(last["open"]), "h": float(last["high"]),
                             "l": float(last["low"]), "c": float(last["close"]),
                             "v": float(last["volume"]), "vw": float((last["high"] + last["low"] + last["close"]) / 3)},
                "prevDailyBar": {"c": float(prev["close"]), "v": float(prev["volume"])},
                "latestTrade": {"p": float(last["close"])},
            }
        return out

    async def get_bars_multi(self, symbols: list[str], timeframe: str = "1Day",
                             limit: int = 30) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for sym in [s.upper() for s in symbols if s]:
            try:
                df = await self.get_bars(sym, timeframe, limit)
            except Exception:  # noqa: BLE001
                continue
            if df is not None and not df.empty:
                out[sym] = df
        return out

    async def get_latest_price(self, symbol: str) -> float:
        df = await self.get_bars(symbol, "1Min", 2)
        return float(df["close"].iloc[-1]) if not df.empty else 0.0

    async def get_clock(self) -> dict:
        return {"is_open": True, "timestamp": datetime.now(timezone.utc).isoformat(),
                "next_open": None, "next_close": None, "note": "demo market is always open"}

    async def get_account(self) -> dict:
        positions_value = 0.0
        for sym, p in self._positions.items():
            px = await self.get_latest_price(sym)
            p["current_price"] = px
            positions_value += p["qty"] * px
        equity = self._cash + positions_value
        return {
            "equity": round(equity, 2),
            "cash": round(self._cash, 2),
            "buying_power": round(max(self._cash, 0) + abs(positions_value), 2),
            "day_pnl": round(equity - self._day_start_equity, 2),
            "day_pnl_pct": (equity - self._day_start_equity) / self._day_start_equity if self._day_start_equity else 0.0,
            "currency": "USD",
            "blocked": False,
        }

    async def get_positions(self) -> list[dict]:
        out = []
        for sym, p in list(self._positions.items()):
            if abs(p["qty"]) < 1e-9:
                continue
            px = await self.get_latest_price(sym)
            upnl = (px - p["avg_entry"]) * p["qty"]
            out.append({
                "symbol": sym,
                "qty": p["qty"],
                "avg_entry": p["avg_entry"],
                "current_price": px,
                "market_value": round(p["qty"] * px, 2),
                "unrealized_pl": round(upnl, 2),
                "unrealized_plpc": round(upnl / (abs(p["avg_entry"] * p["qty"]) or 1e-9), 4),
            })
        return out

    async def get_orders(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._orders))[:limit]

    async def submit_order(self, symbol: str, qty: int, side: str, order_class: str = "simple",
                           stop_loss: dict | None = None, take_profit: dict | None = None,
                           limit_price: float | None = None, type: str = "market") -> dict:
        px = await self.get_latest_price(symbol)
        slip = px * 0.0002
        fill = px + slip if side == "buy" else px - slip
        signed = int(qty) if side == "buy" else -int(qty)
        self._cash -= signed * fill
        p = self._positions.setdefault(symbol, {"qty": 0.0, "avg_entry": fill})
        new_qty = p["qty"] + signed
        if new_qty != 0 and (p["qty"] >= 0) == (signed > 0):
            p["avg_entry"] = (p["avg_entry"] * p["qty"] + fill * signed) / new_qty if new_qty else fill
        p["qty"] = new_qty
        if abs(new_qty) < 1e-9:
            self._positions.pop(symbol, None)
        self._ooid += 1
        order = {"id": f"demo-{self._ooid}", "symbol": symbol, "side": side, "qty": str(qty),
                 "type": type, "status": "filled", "filled_qty": str(qty),
                 "filled_avg_price": f"{fill:.2f}",
                 "submitted_at": datetime.now(timezone.utc).isoformat()}
        self._orders.append(order)
        return order

    async def close_position(self, symbol: str) -> dict:
        p = self._positions.get(symbol)
        if not p or abs(p["qty"]) < 1e-9:
            return {}
        side = "sell" if p["qty"] > 0 else "buy"
        return await self.submit_order(symbol, int(abs(p["qty"])), side)

    async def get_news(self, symbols: list[str] | None = None, limit: int = 30) -> list[dict]:
        # rotate a synthetic but realistic-looking feed; sentiment handled downstream
        now = time.time()
        if now - self._news_ts < 120 and self._news:
            return self._news
        templates = [
            ("{s} beats quarterly earnings expectations, raises full-year guidance", "Reuters", 0.6),
            ("{s} announces $10B share buyback program", "Bloomberg", 0.5),
            ("Analysts upgrade {s} to Overweight citing margin expansion", "Barron's", 0.4),
            ("{s} faces regulatory probe over accounting practices", "WSJ", -0.6),
            ("{s} warns of softening demand, cuts outlook", "CNBC", -0.5),
            ("{s} unveils new AI product line at developer conference", "TechCrunch", 0.3),
            ("Institutional investors increase stake in {s} per 13F filings", "MarketWatch", 0.3),
            ("{s} insiders sold shares last week, filings show", "Barron's", -0.25),
            ("Fed minutes signal cautious stance on rates; markets mixed", "Reuters", -0.1),
            ("{s} secures major government contract", "Bloomberg", 0.45),
        ]
        syms = symbols or ["SPY", "QQQ", "AAPL"]
        rng = np.random.default_rng(int(now // 120))
        items = []
        for i in range(min(limit, 24)):
            t = templates[rng.integers(0, len(templates))]
            s = syms[rng.integers(0, len(syms))]
            items.append({
                "ts": now - i * rng.integers(60, 1800),
                "headline": t[0].format(s=s),
                "summary": t[0].format(s=s),
                "source": t[1],
                "url": "",
                "symbols": [s],
                "symbol": s,
                "_seed_sent": float(t[2]),
            })
        self._news = items
        self._news_ts = now
        return items

    async def close(self) -> None:
        pass


# ----------------------------------------------------------------------------
def get_broker() -> Broker:
    if settings.alpaca_enabled:
        return AlpacaBroker()
    return DemoBroker()
