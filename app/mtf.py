"""Multi-timeframe trend confirmation.

A primary (low) timeframe signal is only as good as the tide it swims in. This
module classifies the higher-timeframe (HTF) trend and turns it into a
multiplier the strategy applies to its composite score:

  * aligned  -> boost confidence (the LTF signal agrees with the HTF tide)
  * conflict -> penalise (or veto) the trade (fighting the tide is low-probability)

The trend is derived from an EMA fast/slow spread plus the slope of the slow
EMA, so a flat/choppy HTF stays neutral and never fires a false confirmation.
"""
from __future__ import annotations

import numpy as np

from .config import settings


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    if len(arr) == 0:
        return arr
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def trend_of(df, fast: int | None = None, slow: int | None = None) -> dict:
    """Classify the HTF trend as +1 (up) / -1 (down) / 0 (flat)."""
    fast = fast or settings.mtf_fast
    slow = slow or settings.mtf_slow
    if df is None or len(df) < slow + 6:
        return {"trend": 0, "label": "UNKNOWN", "strength": 0.0,
                "reason": "insufficient higher-timeframe data"}
    close = df["close"].to_numpy(dtype=float)
    ef = _ema(close, fast)
    es = _ema(close, slow)
    denom = es[-1] or 1.0
    diff = (ef[-1] - es[-1]) / denom
    slope = (es[-1] - es[-6]) / (es[-6] or 1.0)
    strength = float(min(1.0, abs(diff) * 50.0 + abs(slope) * 50.0))

    if diff > 0 and slope >= 0:
        trend, label = 1, "UP"
    elif diff < 0 and slope <= 0:
        trend, label = -1, "DOWN"
    else:
        trend, label = 0, "FLAT"

    return {
        "trend": trend,
        "label": label,
        "strength": round(strength, 3),
        "ema_fast": round(float(ef[-1]), 4),
        "ema_slow": round(float(es[-1]), 4),
        "reason": f"HTF {label} (EMA{fast} vs EMA{slow}, strength {strength:.2f})",
    }


def confirm(direction: int, trend: int) -> float:
    """Multiplier for a trade direction given the HTF trend."""
    if direction == 0 or trend == 0:
        return 1.0
    if direction == trend:
        return float(settings.mtf_align_boost)
    return float(settings.mtf_conflict_penalty)


def breakout(df, lookback: int | None = None) -> dict:
    """Detect a higher-timeframe N-bar breakout (an HTF entry trigger).

    A fresh high above the prior `lookback` bars (or low below them) means the
    higher timeframe itself is igniting, which is a legitimate multi-timeframe
    entry trigger rather than mere confirmation.
    """
    lookback = lookback or settings.mtf_breakout_lookback
    if df is None or len(df) < lookback + 2:
        return {"dir": 0, "level": None, "reason": "insufficient HTF data"}
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    prior_hi = float(np.max(highs[-lookback - 1:-1]))
    prior_lo = float(np.min(lows[-lookback - 1:-1]))
    close = float(df["close"].to_numpy(dtype=float)[-1])
    if close > prior_hi:
        return {"dir": 1, "level": round(prior_hi, 4),
                "reason": f"HTF broke {lookback}-bar high {prior_hi:.2f}"}
    if close < prior_lo:
        return {"dir": -1, "level": round(prior_lo, 4),
                "reason": f"HTF broke {lookback}-bar low {prior_lo:.2f}"}
    return {"dir": 0, "level": None, "reason": "no HTF breakout"}
