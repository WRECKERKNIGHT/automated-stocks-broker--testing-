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

    async def close(self) -> None:
        await fxdata.aclose()
