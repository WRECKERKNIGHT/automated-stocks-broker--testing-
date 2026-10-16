"""Real-time top-of-book (NBBO) tape + order-flow feed.

* Real mode: connects to Alpaca's market-data websocket and subscribes to trades
  and quotes (best bid/ask + sizes), producing a live tape and book imbalance.
* Demo mode: simulates a realistic tape/book so the dashboard is alive without keys.

Note: full multi-level DOM requires a paid consolidated feed. This exposes best
bid/offer + aggressor-classified trade flow, which is what matters for imbalance.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Awaitable, Callable

from .config import settings


def _first_error(msgs) -> str | None:
    """Return 'code msg' for the first Alpaca feed error in a message batch."""
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and m.get("T") == "error":
                return f"{m.get('code')} {m.get('msg')}"
    return None


class TapeFeed:
    def __init__(self, broker, symbols: list[str],
                 on_update: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.broker = broker
        self.symbols = self._cap_symbols([s.upper() for s in symbols])
        self.on_update = on_update
        self.running = False
        self._task: asyncio.Task | None = None
        self._ws = None
        self.demo = broker.mode == "DEMO"
        self.data: dict[str, dict] = {s: self._blank(s) for s in self.symbols}
        self._last_broadcast = 0.0
        self.log: list[str] = []
        self.last_error: str = ""
        self._heat: dict[str, deque] = {s: deque(maxlen=120) for s in self.symbols}

    def _blank(self, s: str) -> dict:
        return {"symbol": s, "bid": 0.0, "ask": 0.0, "bid_size": 0.0, "ask_size": 0.0,
                "spread": 0.0, "imbalance": 0.0, "last": 0.0, "last_size": 0.0,
                "cum_delta": 0.0, "buy_vol": 0.0, "sell_vol": 0.0, "vwap": 0.0,
                "trades": [], "_pv": 0.0, "_v": 0.0}

    # ------------------------------------------------------------------
    def _cap_symbols(self, symbols: list[str]) -> list[str]:
        """Trim to the feed's per-plan symbol limit (free IEX => 405 otherwise)."""
        lim = max(1, int(settings.tape_max_symbols))
        return list(dict.fromkeys(symbols))[:lim]

    def update_symbols(self, symbols: list[str]) -> None:
        self.symbols = self._cap_symbols([s.upper() for s in symbols])
        keep = set(self.symbols)
        self.data = {s: d for s, d in self.data.items() if s in keep}
        self._heat = {s: d for s, d in self._heat.items() if s in keep}
        for s in self.symbols:
            self.data.setdefault(s, self._blank(s))
            self._heat.setdefault(s, deque(maxlen=120))
        if self._ws is not None:
            asyncio.create_task(self._resubscribe())

    def _on_quote(self, sym: str, bid: float, ask: float, bs: float, as_: float) -> None:
        d = self.data.setdefault(sym, self._blank(sym))
        d["bid"], d["ask"] = bid, ask
        d["bid_size"], d["ask_size"] = bs, as_
        d["spread"] = round(ask - bid, 4)
        tot = (bs + as_) or 1.0
        d["imbalance"] = round((bs - as_) / tot, 3)

    def _on_trade(self, sym: str, price: float, size: float) -> None:
        d = self.data.setdefault(sym, self._blank(sym))
        d["last"], d["last_size"] = price, size
        d["_pv"] += price * size
        d["_v"] += size
        d["vwap"] = round(d["_pv"] / d["_v"], 4) if d["_v"] else price
        if d["ask"] and price >= d["ask"]:
            side = "buy"
        elif d["bid"] and price <= d["bid"]:
            side = "sell"
        else:
            mid = (d["bid"] + d["ask"]) / 2 if d["ask"] else price
            side = "buy" if price >= mid else "sell"
        if side == "buy":
            d["buy_vol"] += size
            d["cum_delta"] += size
        else:
            d["sell_vol"] += size
            d["cum_delta"] -= size
        d["trades"].insert(0, {"ts": time.time(), "price": price, "size": size, "side": side})
        del d["trades"][25:]

    # ------------------------------------------------------------------
    def _price_step(self, mid: float) -> float:
        if mid <= 0:
            return 0.01
        return max(0.01, round(mid * 0.0006, 2))

    def _record_heat(self) -> None:
        now = time.time()
        for sym, d in self.data.items():
            if not d.get("bid") or not d.get("ask"):
                continue
            step = self._price_step((d["bid"] + d["ask"]) / 2)
            frame = {"ts": now, "bids": {}, "asks": {}}
            frame["bids"][round(round(d["bid"] / step) * step, 4)] = float(d["bid_size"])
            frame["asks"][round(round(d["ask"] / step) * step, 4)] = float(d["ask_size"])
            if self.demo:
                for k in range(1, 6):
                    size = max(100.0, float(d["bid_size"]) * 0.65 ** k)
                    frame["bids"][round(round((d["bid"] - k * step) / step) * step, 4)] = size
                    size = max(100.0, float(d["ask_size"]) * 0.65 ** k)
                    frame["asks"][round(round((d["ask"] + k * step) / step) * step, 4)] = size
            self._heat[sym].append(frame)

    def build_heatmap(self, symbol: str, frames: int = 90) -> dict:
        frames_list = list(self._heat.get(symbol, []))[-frames:]
        if not frames_list:
            return {"symbol": symbol, "demo": self.demo, "times": [], "prices": [],
                    "cells": [], "sides": [], "max_abs": 0}
        prices = set()
        for f in frames_list:
            prices.update(f["bids"])
            prices.update(f["asks"])
        prices = sorted(prices, reverse=True)
        cells, sides = [], []
        max_abs = 1.0
        for p in prices:
            row = [f["bids"].get(p, 0.0) - f["asks"].get(p, 0.0) for f in frames_list]
            m = max(abs(float(v)) for v in row) or 0.0
            if m > max_abs:
                max_abs = m
            cells.append(row)
            sides.append("bid" if row[-1] > 0 else ("ask" if row[-1] < 0 else "flat"))
        return {"symbol": symbol, "demo": self.demo,
                "times": [f["ts"] for f in frames_list],
                "prices": prices, "cells": cells, "sides": sides,
                "max_abs": max_abs}

    async def _maybe_broadcast(self) -> None:
        now = time.time()
        if now - self._last_broadcast >= 1.0:
            self._last_broadcast = now
            self._record_heat()
            if self.on_update:
                await self.on_update({"type": "tape", "data": self.snapshot()})

    async def start(self) -> None:
        if self.running or not settings.tape_enabled:
            return
        self.running = True
        self._task = asyncio.create_task(self._run())
        self.log.append("tape started")

    async def stop(self) -> None:
        self.running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while self.running:
            try:
                if self.demo or not settings.alpaca_enabled:
                    await self._run_demo()
                else:
                    await self._run_alpaca()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                msg = str(e) or e.__class__.__name__
                if settings.real_data_only and settings.alpaca_enabled:
                    # integrity policy: never fake prices in a real-key session.
                    self.log.append(f"tape error: {msg} (real-data-only: NOT using synthetic)")
                    self.last_error = msg
                    # back off so the single allowed IEX socket is fully released
                    # before we reconnect (the free feed permits one connection).
                    await asyncio.sleep(5)
                else:
                    self.log.append(f"tape error: {msg} -> demo fallback")
                    self.demo = True
                    await asyncio.sleep(2)

    # ------------------------------------------------------------------
    async def _run_alpaca(self) -> None:
        import websockets

        # NOTE: the free IEX feed permits a single concurrent market-data socket
        # per account. We must validate the handshake (a 406 "connection limit
        # exceeded" was previously swallowed, leaving a dead unauthenticated
        # socket holding the only slot), and treat a quiet tape as normal rather
        # than reconnecting into the connection limit.
        url = f"wss://stream.data.alpaca.markets/v2/{settings.data_feed}"
        async with websockets.connect(url, ping_interval=20, max_size=2**23) as ws:
            self._ws = ws
            self.log.append("alpaca tape connected")
            await self._ws_expect(ws, timeout=10)  # {"T":"success","msg":"connected"}
            await ws.send(json.dumps({"action": "auth", "key": settings.alpaca_key,
                                      "secret": settings.alpaca_secret}))
            err = _first_error(await self._ws_expect(ws, timeout=10))
            if err is not None:
                raise RuntimeError(f"auth rejected: {err}")
            self.log.append("alpaca tape authenticated")
            await self._subscribe(ws)
            while self.running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    continue  # no prints (quiet tape) - keep the socket alive
                for m in json.loads(raw):
                    T = m.get("T")
                    if T == "t":
                        self._on_trade(m["S"], float(m["p"]), float(m["s"]))
                    elif T == "q":
                        self._on_quote(m["S"], float(m["bp"]), float(m["ap"]),
                                       float(m["bs"]), float(m["as"]))
                    elif T == "error":
                        self.last_error = str(m.get("msg"))
                        self.log.append(f"tape feed error {m.get('code')}: {m.get('msg')}")
                await self._maybe_broadcast()
        self._ws = None

    async def _ws_expect(self, ws, timeout: float):
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    async def _subscribe(self, ws) -> None:
        await ws.send(json.dumps({"action": "subscribe", "trades": self.symbols,
                                  "quotes": self.symbols}))
        self.log.append(f"subscribed {len(self.symbols)} symbols")

    async def _resubscribe(self) -> None:
        try:
            if self._ws is not None:
                await self._subscribe(self._ws)
        except Exception as e:  # noqa: BLE001
            self.log.append(f"resubscribe failed: {e}")

    async def _run_demo(self) -> None:
        import random

        # seed anchors from current prices
        prices: dict[str, float] = {}
        for s in self.symbols:
            try:
                prices[s] = await self.broker.get_latest_price(s) or 100.0
            except Exception:  # noqa: BLE001
                prices[s] = 100.0
        while self.running:
            for s in self.symbols:
                p = prices.get(s, 100.0)
                tick = max(0.01, round(p * random.uniform(0.00002, 0.0004), 2))
                p = round(max(0.5, p + random.gauss(0, tick)), 2)
                prices[s] = p
                bid = round(p - random.uniform(0.01, tick + 0.01), 2)
                ask = round(p + random.uniform(0.01, tick + 0.01), 2)
                self._on_quote(s, bid, ask, random.randint(100, 5000), random.randint(100, 5000))
                for _ in range(random.randint(1, 4)):
                    self._on_trade(s, round(random.uniform(bid, ask), 2), random.choice([100, 200, 300, 500, 1000, 2500]))
            await self._maybe_broadcast()
            await asyncio.sleep(0.8)

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        out = {}
        for s, d in self.data.items():
            out[s] = {k: v for k, v in d.items() if not k.startswith("_")}
        return {"demo": self.demo, "symbols": self.symbols, "ts": time.time(),
                "book": out, "log": self.log[-5:]}
