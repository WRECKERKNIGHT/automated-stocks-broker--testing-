"""Stock research: a per-symbol dossier from price/volume/news + a rule-based
scorecard (trend, momentum, relative strength, sentiment) with a rating,
thesis and risk notes.

The free Alpaca feed carries no fundamentals, so everything here is derived from
price action, volume, market structure and news sentiment - and we say so.
"""
from __future__ import annotations

import math

import numpy as np

from . import indicators, storage
from .alpaca import Broker


def _f(v, d=0.0) -> float:
    try:
        f = float(v)
        return d if f != f else f
    except (TypeError, ValueError):
        return d


def _pct(a, b) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _trend_score(price, sma20, sma50, sma200) -> float:
    s = 0.0
    if sma20 and price > sma20:
        s += 0.4
    if sma50 and price > sma50:
        s += 0.3
    if sma200 and price > sma200:
        s += 0.3
    return (s * 2 - 1) if sma20 or sma50 or sma200 else 0.0  # -1..1


def _momentum_score(rsi, macd_hist, ret20) -> float:
    r = 0.0
    r += max(-1.0, min(1.0, ret20 / 10.0)) * 0.5           # 20d % return, capped
    r += (0.25 if macd_hist > 0 else -0.25)
    if rsi >= 50:
        r += min(0.25, (rsi - 50) / 100)
    else:
        r -= min(0.25, (50 - rsi) / 100)
    return max(-1.0, min(1.0, r))


def _rating(score: float) -> str:
    if score >= 72:
        return "Strong Buy"
    if score >= 58:
        return "Buy"
    if score >= 43:
        return "Neutral"
    if score >= 28:
        return "Sell"
    return "Strong Sell"


async def research(broker: Broker, symbol: str, *, news: list[dict] | None = None,
                   sentiment: float = 0.0) -> dict:
    symbol = symbol.upper()
    dfd = await broker.get_bars(symbol, "1Day", 260)
    if dfd is None or len(dfd) < 25:
        return {"symbol": symbol, "error": "insufficient daily history"}
    feat = indicators.compute_features(dfd)
    last = feat.iloc[-1]
    price = _f(last["close"])
    window = dfd.tail(252)
    hi52 = _f(window["high"].max())
    lo52 = _f(window["low"].min())

    sma20 = _f(last.get("ema21"))  # ema as moving-average proxy already computed
    sma50 = _f(last.get("ema50"))
    sma200 = _f(last.get("sma200"))
    rsi = _f(last.get("rsi"), 50)
    macd_hist = _f(last.get("macd_hist"))
    atr_pct = _f(last.get("atr_pct")) * 100
    adx = _f(last.get("adx"))
    avg_vol20 = _f(dfd["volume"].tail(20).mean())
    ret20 = _pct(price, _f(dfd["close"].iloc[-21]) if len(dfd) > 21 else price)
    ret5 = _pct(price, _f(dfd["close"].iloc[-6]) if len(dfd) > 6 else price)

    # relative strength vs SPY (best-effort; one extra cheap call)
    rel = None
    if symbol != "SPY":
        try:
            spy = await broker.get_bars("SPY", "1Day", 60)
            if spy is not None and len(spy) > 21:
                spy_ret = _pct(_f(spy["close"].iloc[-1]), _f(spy["close"].iloc[-21]))
                rel = round(ret20 - spy_ret, 2)
        except Exception:  # noqa: BLE001
            rel = None

    # intraday structure
    intraday = {}
    try:
        dfi = await broker.get_bars(symbol, "5Min", 120)
        if dfi is not None and not dfi.empty:
            fi = indicators.compute_features(dfi)
            li = fi.iloc[-1]
            intraday = {
                "vwap": round(_f(li.get("vwap")), 4),
                "session_high": round(_f(dfi["high"].tail(78).max()), 4),
                "session_low": round(_f(dfi["low"].tail(78).min()), 4),
                "rvol": round(_f(li.get("rvol"), 1), 2),
            }
    except Exception:  # noqa: BLE001
        intraday = {}

    pools = indicators.swing_levels(feat, lookback=5)
    vprof = indicators.volume_profile(feat.tail(120))

    # ---- scorecard ----
    tscore = _trend_score(price, sma20, sma50, sma200)
    mscore = _momentum_score(rsi, macd_hist, ret20)
    sscore = max(-1.0, min(1.0, _f(sentiment)))
    rscore = max(-1.0, min(1.0, (rel or 0) / 8.0)) if rel is not None else 0.0
    composite = 0.34 * tscore + 0.34 * mscore + 0.16 * rscore + 0.16 * sscore
    score100 = round((composite + 1) / 2 * 100, 1)
    rating = _rating(score100)

    thesis, risks = [], []
    if tscore > 0.3:
        thesis.append("Price above key moving averages - constructive trend.")
    elif tscore < -0.3:
        risks.append("Price below key moving averages - downtrend structure.")
    if ret20 > 3:
        thesis.append(f"20-day momentum is positive ({ret20:+.1f}%).")
    elif ret20 < -3:
        risks.append(f"20-day momentum is negative ({ret20:+.1f}%).")
    if rsi >= 70:
        risks.append(f"RSI {rsi:.0f} - overbought, pullback risk.")
    elif rsi <= 30:
        thesis.append(f"RSI {rsi:.0f} - oversold, mean-reversion potential.")
    if adx >= 25:
        thesis.append(f"ADX {adx:.0f} - trending market (directional edge favoured).")
    else:
        risks.append(f"ADX {adx:.0f} - weak trend, chop risk.")
    if atr_pct >= 4:
        risks.append(f"High volatility (ATR {atr_pct:.1f}% of price) - size down.")
    if rel is not None:
        if rel > 2:
            thesis.append(f"Outperforming SPY by {rel:+.1f}% over 20d (relative strength).")
        elif rel < -2:
            risks.append(f"Underperforming SPY by {rel:+.1f}% over 20d.")
    if sscore > 0.2:
        thesis.append("Recent news sentiment is net positive.")
    elif sscore < -0.2:
        risks.append("Recent news sentiment is net negative.")

    summary = (f"{symbol} scores {score100:.0f}/100 ({rating}). "
               f"Trend {tscore:+.2f}, momentum {mscore:+.2f}, "
               f"rel-strength {rscore:+.2f}, sentiment {sscore:+.2f}. "
               f"Price {price:.2f}, RSI {rsi:.0f}, ATR {atr_pct:.1f}%, ADX {adx:.0f}.")

    # news feed for this symbol
    items = news
    if items is None:
        items = [n for n in storage.recent_news(limit=200)
                 if (n.get("symbol") or "") == symbol
                 or symbol in (n.get("headline") or "")]
    items = items[:12]

    return {
        "symbol": symbol,
        "price": round(price, 4),
        "rating": rating,
        "score": score100,
        "summary": summary,
        "thesis": thesis,
        "risks": risks,
        "subscores": {"trend": round(tscore, 2), "momentum": round(mscore, 2),
                      "rel_strength": round(rscore, 2), "sentiment": round(sscore, 2)},
        "stats": {
            "high_52w": round(hi52, 2), "low_52w": round(lo52, 2),
            "pct_from_high": round(_pct(price, hi52), 2),
            "pct_from_low": round(_pct(price, lo52), 2),
            "sma20": round(sma20, 2), "sma50": round(sma50, 2), "sma200": round(sma200, 2),
            "rsi": round(rsi, 1), "adx": round(adx, 1), "atr_pct": round(atr_pct, 2),
            "ret5": round(ret5, 2), "ret20": round(ret20, 2),
            "rel_strength_spy": rel,
            "avg_volume_20d": int(avg_vol20),
        },
        "intraday": intraday,
        "levels": {"support": [round(x, 2) for x in (pools.get("swing_lows") or [])[:4]],
                   "resistance": [round(x, 2) for x in (pools.get("swing_highs") or [])[:4]],
                   "poc": round(_f(vprof.get("poc")), 2) if vprof.get("poc") else None,
                   "value_high": round(_f(vprof.get("vah")), 2) if vprof.get("vah") else None,
                   "value_low": round(_f(vprof.get("val")), 2) if vprof.get("val") else None},
        "news": items,
        "fundamentals_note": "Free data feed has no fundamentals; metrics are price/volume/news derived.",
    }
