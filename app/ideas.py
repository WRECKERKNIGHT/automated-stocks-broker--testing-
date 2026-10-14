"""Ideas & tips: auto-generated trade ideas (strategy across a candidate set),
a daily briefing and a rotating set of risk / discipline tips.
"""
from __future__ import annotations

import random
import time

from . import indicators, strategy
from .alpaca import Broker
from .config import settings

TIPS = [
    "Risk a fixed fraction per trade (0.5-1%); never let one loss define the week.",
    "Trade with the higher-timeframe trend; counter-trend entries need extra confirmation.",
    "Plan the exit (stop + target) before the entry - and honour the stop.",
    "Cut losers fast, let winners run: move to break-even after +1R.",
    "Avoid the first 5 and last 5 minutes - spreads and noise are widest.",
    "Size down when volatility (ATR) spikes; the same position is suddenly twice the risk.",
    "One good setup repeated beats ten random trades.",
    "Beware low-float, low-price movers - slippage and manipulation are real.",
    "News can invalidate a chart in seconds; check the tape before chasing.",
    "Correlation kills diversification - don't stack five names that move together.",
    "Your edge shows up in expectancy, not win rate. Track both.",
    "If you can't explain the trade in one sentence, skip it.",
    "Green days are for banking, not for revenge-trading a red one.",
    "Respect the daily loss limit - it exists to keep you in the game.",
    "Relative volume > high volume: RVOL tells you if *today* is unusual.",
]


async def ideas(broker: Broker, *, candidates: list[str], sentiment: dict | None = None,
                market: dict | None = None, limit: int | None = None) -> dict:
    sentiment = sentiment or {}
    limit = limit or settings.ideas_max
    cands = [c.upper() for c in dict.fromkeys(candidates) if c][:60]
    market = market or {"bias": 0.0, "label": "OFF"}
    out: list[dict] = []
    regimes: dict[str, int] = {}

    frames = await broker.get_bars_multi(cands, "5Min", 200) if cands else {}
    for sym, df in frames.items():
        if df is None or len(df) < 40:
            continue
        try:
            feat = indicators.compute_features(df)
            ctx = strategy.analyze(sym, df, news_sentiment=sentiment.get(sym, 0.0), feat=feat,
                                   market=market)
        except Exception:  # noqa: BLE001
            continue
        regimes[ctx.get("regime", "?")] = regimes.get(ctx.get("regime", "?"), 0) + 1
        if ctx.get("action") in ("BUY", "SELL") and ctx.get("confidence", 0) >= 0.15:
            out.append({
                "symbol": sym,
                "action": ctx["action"],
                "confidence": ctx["confidence"],
                "regime": ctx.get("regime"),
                "price": ctx.get("price"),
                "entry": ctx.get("entry"),
                "stop": ctx.get("stop"),
                "target": ctx.get("target"),
                "rr": ctx.get("rr"),
                "atr_pct": (ctx.get("features") or {}).get("atr_pct"),
                "rsi": (ctx.get("features") or {}).get("rsi"),
                "rvol": (ctx.get("features") or {}).get("rvol"),
                "signals": [s["name"] for s in ctx.get("signals", []) if s.get("dir")],
                "reasons": ctx.get("reasons", [])[:5],
                "toxicity": (ctx.get("toxicity") or {}).get("level"),
            })

    out.sort(key=lambda x: -x["confidence"])
    ideas_top = out[:limit]

    buys = sum(1 for i in out if i["action"] == "BUY")
    sells = sum(1 for i in out if i["action"] == "SELL")
    sent_vals = [v for v in sentiment.values() if v]
    sent_avg = round(sum(sent_vals) / len(sent_vals), 3) if sent_vals else 0.0
    label = market.get("label", "OFF")
    bias = float(market.get("bias") or 0)
    mood = "risk-on" if bias > 0.05 else ("risk-off" if bias < -0.05 else "mixed")

    if not out:
        headline = ("No high-conviction setups right now. "
                    f"Market context is {mood} ({label}). Fewer trades is a position too.")
    else:
        headline = (f"{len(out)} setups detected ({buys} long / {sells} short); "
                    f"market context {mood} ({label}). Top: "
                    + ", ".join(f"{i['symbol']} {i['action']}" for i in ideas_top[:4]) + ".")

    rng = random.Random(int(time.time() // 3600))
    tips = rng.sample(TIPS, k=min(6, len(TIPS)))

    result = {
        "ideas": ideas_top,
        "total": len(out),
        "briefing": {
            "headline": headline,
            "market": market,
            "mood": mood,
            "sentiment_avg": sent_avg,
            "counts": {"BUY": buys, "SELL": sells},
            "regimes": regimes,
        },
        "tips": tips,
        "updated": time.time(),
    }
    return result
