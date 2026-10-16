"""Free public FX market data (no API key required).

Pulls OHLC candles for currency pairs and spot metals from Yahoo Finance's
public chart endpoint and normalises them into the same pandas shape the rest
of the engine already consumes (``open``/``high``/``low``/``close``/``volume``
indexed by a UTC ``DatetimeIndex``).

This deliberately avoids any paid/broker dependency: the merged app's "forex"
market mode runs on this feed with locally *simulated* fills (see fxbroker.py).
"""
from __future__ import annotations

import time

import httpx
import pandas as pd

# Yahoo uses "<BASE><QUOTE>=X" for FX and futures tickers for the metals.
_SYMBOL_MAP = {
    "XAU_USD": "GC=F",   # gold (front-month futures as the spot proxy)
    "XAG_USD": "SI=F",   # silver
    "XPT_USD": "PL=F",   # platinum
    "XPD_USD": "PA=F",   # palladium
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
}

# app timeframe -> Yahoo interval
_INTERVAL = {
    "1Min": "1m", "5Min": "5m", "15Min": "15m", "30Min": "30m",
    "1Hour": "60m", "1Day": "1d",
}

# app timeframe -> approximate minutes (used to size the requested range)
_TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60, "1Day": 1440}

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AITrader/1.0)"}

# Yahoo rejects 1m requests beyond ~7 days and 5m beyond ~60 days; keep the
# requested window inside those ceilings.
_RANGE_CEIL = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "60m": "730d", "1d": "10y"}

_client: httpx.AsyncClient | None = None
_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL = 25.0  # seconds: keep scans snappy without staling the tape


def to_yahoo(symbol: str) -> str:
    """Map an app symbol (EUR_USD / XAU_USD) to a Yahoo ticker."""
    sym = (symbol or "").upper().strip()
    if sym in _SYMBOL_MAP:
        return _SYMBOL_MAP[sym]
    if "_" in sym:
        base, _, quote = sym.partition("_")
        if base and quote:
            return f"{base}{quote}=X"
    return f"{sym}=X"


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20.0, headers=_HEADERS)
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _range_for(interval: str, limit: int) -> str:
    """Smallest Yahoo range that comfortably covers ``limit`` candles."""
    minutes = _TF_MINUTES.get("5Min", 5)
    for tf, mins in _TF_MINUTES.items():
        if _INTERVAL.get(tf) == interval:
            minutes = mins
            break
    need_days = max(1, int((limit * minutes) / 1440) + 2)
    for rng, days in (("1d", 1), ("5d", 5), ("1mo", 31), ("3mo", 92), ("6mo", 183),
                      ("1y", 366), ("2y", 731), ("5y", 1827), ("10y", 3653)):
        if need_days <= days:
            return rng
    return _RANGE_CEIL.get(interval, "1mo")


def last_error(payload: dict) -> str:
    """Extract a Yahoo error string (for diagnostics)."""
    err = (payload or {}).get("chart", {}).get("error")
    if not err:
        return ""
    return str(err.get("description") or err.get("code") or err)
