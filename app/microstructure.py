"""Market-microstructure proxies computed from OHLCV bars.

True Level-2 / tape needs a full SIP feed + websocket. With the free IEX feed we
approximate institutional intent from bar internals:
  - classified buy/sell volume (close position within the bar range)
  - cumulative delta & delta divergence
  - VPIN-style order-flow toxicity
  - liquidity pools (stop clusters) around swing levels
These feed the strategy as *context*, never as a lone trigger.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cv_arrays(df: pd.DataFrame):
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    v = df["volume"].to_numpy(dtype=float)
    rng = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        clv = ((c - l) - (h - c)) / rng
    clv = np.nan_to_num(clv, nan=0.0)
    clv = np.clip(clv, -1.0, 1.0)
    buy = v * (clv + 1.0) / 2.0
    sell = v * (1.0 - clv) / 2.0
    return buy, sell, buy - sell


def classified_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Split each bar's volume into buy/sell using the close-location value (CLV)."""
    buy, sell, delta = _cv_arrays(df)
    n = len(df)
    rng = (df["high"] - df["low"]).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        clv = ((2 * df["close"] - df["high"] - df["low"]) / rng).to_numpy(dtype=float)
    clv = np.nan_to_num(clv, nan=0.0)
    return pd.DataFrame({"buy_vol": buy, "sell_vol": sell, "delta": delta, "clv": clv})


def cumulative_delta(df: pd.DataFrame) -> pd.Series:
    return classified_volume(df)["delta"].cumsum()


def vpin(df: pd.DataFrame, n_buckets: int = 50, window: int = 20) -> float:
    """Volume-synchronized probability of informed trading (proxy, 0..1)."""
    _, _, delta = _cv_arrays(df)
    vol = df["volume"].to_numpy(dtype=float)
    return _vpin_from(vol, delta, n_buckets, window)


def _vpin_from(vol: np.ndarray, delta: np.ndarray, n_buckets: int = 50, window: int = 20) -> float:
    n = len(vol)
    if n == 0:
        return 0.0
    total = float(np.nansum(vol))
    if total <= 0:
        return 0.0
    # TRUE VPIN uses a *volume clock*: split the period's traded volume into
    # n_buckets equal tranches, not a fixed 50 *shares*. The old fixed bucket
    # took one bar per tranche and pinned VPIN at ~1.0 in every trend, which
    # falsely flagged normal order flow as toxic and vetoed good entries.
    bucket = max(1.0, total / float(max(1, n_buckets)))
    scores = []
    acc = buy = sell = 0.0
    for j in range(n):
        dv = float(delta[j])
        vj = float(vol[j])
        if dv > 0:
            buy += dv + vj / 2
        else:
            sell += -dv + vj / 2
        acc += vj
        if acc >= bucket:
            tot = buy + sell
            if tot > 0:
                scores.append(abs(buy - sell) / tot)
            buy = sell = acc = 0.0
    if not scores:
        return 0.0
    return float(np.mean(scores[-window:]))


def order_flow(df: pd.DataFrame, lookback: int = 20) -> dict:
    buy_a, sell_a, delta_a = _cv_arrays(df)
    close = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    n = len(df)
    lb = min(lookback, n)
    buy = float(buy_a[-lb:].sum())
    sell = float(sell_a[-lb:].sum())
    total = buy + sell
    imbalance = (buy - sell) / total if total else 0.0
    price_chg = float(close[-1] - close[-lb]) if n > lb else 0.0
    delta_chg = float(delta_a[-lb:].sum())
    divergence = 0.0
    if price_chg > 0 and delta_chg < 0:
        divergence = -1.0
    elif price_chg < 0 and delta_chg > 0:
        divergence = 1.0
    return {
        "buy_vol": buy,
        "sell_vol": sell,
        "imbalance": float(imbalance),
        "delta": delta_chg,
        "divergence": divergence,
        "toxicity": _vpin_from(vol[-400:], delta_a[-400:]),
    }


def liquidity_pools(df: pd.DataFrame, lookback: int = 40) -> dict:
    """Where are retail stops likely parked? Below swing lows / above swing highs."""
    from .indicators import swing_levels

    lv = swing_levels(df.tail(120), 5)
    price = float(df["close"].iloc[-1])
    below = [p for p in lv["swing_lows"] if p < price]
    above = [p for p in lv["swing_highs"] if p > price]
    return {
        "support_pool": max(below) if below else None,
        "resistance_pool": min(above) if above else None,
        "swing_highs": lv["swing_highs"],
        "swing_lows": lv["swing_lows"],
    }
