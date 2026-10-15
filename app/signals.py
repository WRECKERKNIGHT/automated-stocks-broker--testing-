"""Signal generation.

Each playbook emits a *named* signal with a direction (+1 long / -1 short / 0)
and a weight (0..1). The strategy layer then aggregates weighted votes. Every
signal carries a human-readable reason so the dashboard can show *why*.
"""
from __future__ import annotations

from typing import Any


def _row(df, name: str, default: float = 0.0) -> float:
    try:
        v = df[name].iloc[-1]
        return default if v != v else float(v)  # NaN check
    except Exception:
        return default


def trend_continuation(df, regime: str) -> dict | None:
    c = _row(df, "close")
    ema9, ema21, ema50 = _row(df, "ema9"), _row(df, "ema21"), _row(df, "ema50")
    adx, rvol, vwap = _row(df, "adx"), _row(df, "rvol", 1), _row(df, "vwap")
    if adx >= 22 and rvol >= 1.2 and ema9 > ema21 > ema50 and c > vwap and regime in ("TREND_UP", "RANGE"):
        return {"name": "trend_pullback_long", "dir": 1, "weight": 0.9,
                "reason": f"EMA stack bullish, ADX {adx:.0f}, RVOL {rvol:.1f}, above VWAP"}
    if adx >= 22 and rvol >= 1.2 and ema9 < ema21 < ema50 and c < vwap and regime in ("TREND_DOWN", "RANGE"):
        return {"name": "trend_pullback_short", "dir": -1, "weight": 0.9,
                "reason": f"EMA stack bearish, ADX {adx:.0f}, RVOL {rvol:.1f}, below VWAP"}
    return None


def value_area_breakout(df, vol_profile: dict) -> dict | None:
    c = _row(df, "close")
    rvol, vwap = _row(df, "rvol", 1), _row(df, "vwap")
    vah, val = vol_profile.get("vah"), vol_profile.get("val")
    if vah and c > vah and rvol >= 1.5 and c > vwap:
        return {"name": "value_area_breakout_long", "dir": 1, "weight": 0.85,
                "reason": f"Price {c:.2f} broke value-area-high {vah:.2f} on RVOL {rvol:.1f}"}
    if val and c < val and rvol >= 1.5 and c < vwap:
        return {"name": "value_area_breakdown_short", "dir": -1, "weight": 0.85,
                "reason": f"Price {c:.2f} broke value-area-low {val:.2f} on RVOL {rvol:.1f}"}
    return None


def momentum_ignition(df, micro: dict) -> dict | None:
    rvol = _row(df, "rvol", 1)
    imb = micro.get("imbalance", 0.0)
    if rvol >= 2.0 and imb >= 0.35:
        return {"name": "momentum_long", "dir": 1, "weight": 1.0,
                "reason": f"Aggressive buying: RVOL {rvol:.1f}, delta imbalance +{imb:.0%}"}
    if rvol >= 2.0 and imb <= -0.35:
        return {"name": "momentum_short", "dir": -1, "weight": 1.0,
                "reason": f"Aggressive selling: RVOL {rvol:.1f}, delta imbalance {imb:.0%}"}
    return None


def mean_reversion(df, regime: str, htf_trend: int = 0) -> dict | None:
    if regime not in ("RANGE",):
        return None
    c = _row(df, "close")
    rsi = _row(df, "rsi", 50)
    dn, up = _row(df, "bb_dn"), _row(df, "bb_up")
    # Never fade into a higher-timeframe trend - the "mean" has moved.
    if rsi <= 28 and c <= dn and htf_trend >= 0:
        return {"name": "mean_reversion_long", "dir": 1, "weight": 0.7,
                "reason": f"Oversold in range: RSI {rsi:.0f}, at/below lower band"}
    if rsi >= 72 and c >= up and htf_trend <= 0:
        return {"name": "mean_reversion_short", "dir": -1, "weight": 0.7,
                "reason": f"Overbought in range: RSI {rsi:.0f}, at/above upper band"}
    return None


def liquidity_sweep(df, pools: dict, regime: str = "RANGE", htf_trend: int = 0) -> dict | None:
    """Stop-hunt reversal: swept a support pool then closed back above it.

    Refuses to fade a trend: a reclaim is not bought when it is a knife-catch
    against a down-trend, and a rejection is not shorted into an up-trend. This
    signal is the usual culprit behind "bought the top of the pullback / sold the
    bottom of the rip".
    """
    c = _row(df, "close")
    low = _row(df, "low", c)
    sup = pools.get("support_pool")
    res = pools.get("resistance_pool")
    fade_down = regime == "TREND_DOWN" or htf_trend < 0
    fade_up = regime == "TREND_UP" or htf_trend > 0
    if sup and low < sup and c > sup and not fade_down:
        return {"name": "sweep_reclaim_long", "dir": 1, "weight": 0.75,
                "reason": f"Swept liquidity below {sup:.2f} then reclaimed - stop-hunt reversal"}
    if res and _row(df, "high", c) > res and c < res and not fade_up:
        return {"name": "sweep_reject_short", "dir": -1, "weight": 0.75,
                "reason": f"Swept liquidity above {res:.2f} then rejected - stop-hunt reversal"}
    return None


def toxicity_warning(micro: dict) -> dict | None:
    tox = micro.get("toxicity", 0.0)
    if tox >= 0.4:
        return {"name": "toxic_flow", "dir": 0, "weight": 0.6,
                "reason": f"Order-flow toxicity high (VPIN {tox:.2f}) - informed flow active"}
    return None


def generate(df, regime: str, micro: dict, pools: dict, vol_profile: dict,
             news_sentiment: float = 0.0) -> list[dict[str, Any]]:
    sigs: list[dict] = []
    for fn, args in (
        (trend_continuation, (df, regime)),
        (value_area_breakout, (df, vol_profile)),
        (momentum_ignition, (df, micro)),
        (mean_reversion, (df, regime)),
        (liquidity_sweep, (df, pools)),
        (toxicity_warning, (micro,)),
    ):
        s = fn(*args)
        if s:
            sigs.append(s)
    if abs(news_sentiment) >= 0.3:
        sigs.append({
            "name": "news_sentiment",
            "dir": 1 if news_sentiment > 0 else -1,
            "weight": min(0.5, abs(news_sentiment)),
            "reason": f"News sentiment {'bullish' if news_sentiment > 0 else 'bearish'} ({news_sentiment:+.2f})",
        })
    return sigs
