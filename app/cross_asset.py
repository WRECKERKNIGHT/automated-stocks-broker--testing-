"""Cross-asset & market-breadth leading context.

Single-name setups are dominated by the tide: when the broad market is risk-on,
longs work and shorts fight the tape; risk-off flips that. This module reads a
basket of liquid index/ETF proxies (default SPY, QQQ, IWM) and distils them into
one market bias in -1..1:

  * each proxy scored from its EMA spread + slow-EMA slope (trend & momentum)
  * the basket average is the breadth signal
  * label: RISK_ON / NEUTRAL / RISK_OFF

The bias is fed to the strategy as an additive context term (like news/LLM),
never as a standalone trigger.
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


def asset_score(df, fast: int = 20, slow: int = 50, slope: int = 5) -> float:
    """Trend+momentum score for one asset in -1..1."""
    if df is None or len(df) < slow + slope + 1:
        return 0.0
    close = df["close"].to_numpy(dtype=float)
    ef = _ema(close, fast)
    es = _ema(close, slow)
    spread = (ef[-1] - es[-1]) / (es[-1] or 1.0)
    slope_v = (es[-1] - es[-1 - slope]) / (es[-1 - slope] or 1.0)
    raw = 50.0 * spread + 50.0 * slope_v
    return float(max(-1.0, min(1.0, raw)))


def assess(frames: dict) -> dict:
    """Distil a basket of benchmark frames into one market bias."""
    scores: dict[str, float] = {}
    for sym, df in (frames or {}).items():
        scores[sym] = round(asset_score(df), 3)
    if not scores:
        return {"bias": 0.0, "label": "OFF", "scores": {}, "reason": "no cross-asset data"}
    bias = float(np.mean(list(scores.values())))
    if bias >= 0.2:
        label = "RISK_ON"
    elif bias <= -0.2:
        label = "RISK_OFF"
    else:
        label = "NEUTRAL"
    n_up = sum(1 for v in scores.values() if v > 0)
    return {
        "bias": round(bias, 3),
        "label": label,
        "scores": scores,
        "breadth": f"{n_up}/{len(scores)} risk-on",
        "reason": f"Market {label} (bias {bias:+.2f}, {n_up}/{len(scores)} proxies up)",
    }
