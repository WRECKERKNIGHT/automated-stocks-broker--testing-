"""Forex broker: real public candles + locally simulated paper fills.

There is no broker account here. Prices come from the free Yahoo feed
(app.fxdata); orders are filled instantly against the latest mid with a small,
symbol-appropriate spread + slippage, and tracked in a virtual $100k account.
This lets the merged app trade FX end-to-end without any API keys, while the
dashboard tape runs in synthetic mode (``synthetic_tape``) so we never try to
open an Alpaca equity websocket for currency pairs.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from . import fxdata
from .alpaca import Broker

# approximate half-spread in "price" terms per instrument family
_SPREAD = {
    "XAU_USD": 0.25, "XAG_USD": 0.02, "XPT_USD": 0.8, "XPD_USD": 1.2,
}
_DEFAULT_SPREAD = 0.00006  # ~0.6 pip on a 5-decimal major


class FxBroker(Broker):
    mode = "FOREX"
    synthetic_tape = True  # the order-flow tape is simulated for FX
    START_EQUITY = 100_000.0

    def __init__(self) -> None:
        self._cash = self.START_EQUITY
        self._day_start_equity = self.START_EQUITY
        self._positions: dict[str, dict] = {}
        self._orders: list[dict] = []
        self._ooid = 0
        self._news: list[dict] = []
        self._news_ts = 0.0

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _norm(symbol: str) -> str:
        return (symbol or "").upper().replace("/", "_").strip()

    def _half_spread(self, symbol: str) -> float:
        return _SPREAD.get(symbol, _DEFAULT_SPREAD)

    # ---- market data (real, public) ------------------------------------
    async def get_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 300) -> pd.DataFrame:
        return await fxdata.fetch_bars(self._norm(symbol), timeframe, limit)

    async def get_latest_price(self, symbol: str) -> float:
        df = await self.get_bars(symbol, "1Min", 3)
        return float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0

    async def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for sym in [self._norm(s) for s in symbols if s]:
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
                             "v": float(last["volume"]),
                             "vw": float((last["high"] + last["low"] + last["close"]) / 3)},
                "prevDailyBar": {"c": float(prev["close"]), "v": float(prev["volume"])},
                "latestTrade": {"p": float(last["close"])},
            }
        return out

    async def get_bars_multi(self, symbols: list[str], timeframe: str = "1Day",
                             limit: int = 30) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for sym in [self._norm(s) for s in symbols if s]:
            try:
                df = await self.get_bars(sym, timeframe, limit)
            except Exception:  # noqa: BLE001
                continue
            if df is not None and not df.empty:
                out[sym] = df
        return out

    # ---- account / positions / orders ----------------------------------
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
            "day_pnl_pct": (equity - self._day_start_equity) / self._day_start_equity
            if self._day_start_equity else 0.0,
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
        sym = self._norm(symbol)
        px = await self.get_latest_price(sym)
        if px <= 0:
            px = 1.0
        half = self._half_spread(sym)
        slip = px * 0.00002
        # buy fills at the ask, sell at the bid
        fill = (px + half + slip) if side == "buy" else (px - half - slip)
        fill = round(fill, 5)
        signed = int(qty) if side == "buy" else -int(qty)
        self._cash -= signed * fill
        p = self._positions.setdefault(sym, {"qty": 0.0, "avg_entry": fill})
        new_qty = p["qty"] + signed
        if new_qty != 0 and (p["qty"] >= 0) == (signed > 0):
            p["avg_entry"] = ((p["avg_entry"] * p["qty"]) + (fill * signed)) / new_qty if new_qty else fill
        p["qty"] = new_qty
        if abs(new_qty) < 1e-9:
            self._positions.pop(sym, None)
        self._ooid += 1
        order = {"id": f"fx-{self._ooid}", "symbol": sym, "side": side, "qty": str(qty),
                 "type": type, "status": "filled", "filled_qty": str(qty),
                 "filled_avg_price": f"{fill:.5f}",
                 "submitted_at": datetime.now(timezone.utc).isoformat()}
        self._orders.append(order)
        return order

    async def close_position(self, symbol: str) -> dict:
        sym = self._norm(symbol)
        p = self._positions.get(sym)
        if not p or abs(p["qty"]) < 1e-9:
            return {}
        side = "sell" if p["qty"] > 0 else "buy"
        return await self.submit_order(sym, int(abs(p["qty"])), side)

    async def get_clock(self) -> dict:
        """FX trades ~24h from Sunday evening to Friday evening (UTC)."""
        now = datetime.now(timezone.utc)
        day = now.weekday()
        open_now = day < 5 or (day == 5 and now.hour < 22) or (day == 6 and now.hour >= 22)
        if open_now:
            return {"is_open": True, "timestamp": now.isoformat(),
                    "next_open": None, "next_close": None, "note": "FX market open"}
        return {"is_open": False, "timestamp": now.isoformat(),
                "next_open": None, "next_close": None, "note": "FX market closed for the weekend"}

    async def get_news(self, symbols: list[str] | None = None, limit: int = 30) -> list[dict]:
        now = time.time()
        if now - self._news_ts < 120 and self._news:
            return self._news
        templates = [
            ("Fed holds rates steady, signals data-dependent path ahead", "Reuters", 0.3),
            ("ECB officials hint at possible rate cut in coming months", "Bloomberg", -0.2),
            ("BOJ intervenes to stabilise yen after sharp decline", "Reuters", 0.5),
            ("US NFP beats expectations, dollar rallies broadly", "CNBC", 0.6),
            ("BoE holds rates, pushback on early cuts", "FT", 0.4),
            ("Risk-off sentiment lifts safe-haven flows into the dollar", "WSJ", 0.2),
            ("China stimulus hopes boost commodity currencies", "Bloomberg", 0.35),
            ("Inflation data cools more than expected, yields slide", "Reuters", -0.3),
            ("Oil spikes on supply-disruption fears, CAD under pressure", "CNBC", -0.25),
            ("Powell reiterates higher-for-longer stance", "Reuters", 0.45),
        ]
        import numpy as np

        syms = [self._norm(s) for s in (symbols or ["EUR_USD", "GBP_USD", "USD_JPY"])]
        rng = np.random.default_rng(int(now // 120))
        items = []
        for i in range(min(limit, 24)):
            t = templates[rng.integers(0, len(templates))]
            s = syms[rng.integers(0, len(syms))]
            items.append({
                "ts": now - i * rng.integers(60, 1800),
                "headline": t[0], "summary": t[0], "source": t[1], "url": "",
                "symbols": [s], "symbol": s, "_seed_sent": float(t[2]),
            })
        self._news = items
        self._news_ts = now
        return items

    async def close(self) -> None:
        await fxdata.aclose()
