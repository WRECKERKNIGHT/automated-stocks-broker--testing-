"""The Trader's Brain - an encoded model of how a disciplined human day trader
thinks, selects and manages a position.

Three jobs:
  1. SESSION - know what time of day it is and what that time is *for*. The same
     setup has a completely different expectancy at 09:40 vs 12:30 vs 15:20.
  2. SELECT  - refuse the low-quality setups that make up most of a losing tape:
     counter-trend knife-catching, chasing, dead volume, chop, revenge trades.
  3. THESIS  - turn a raw signal into a human plan: setup type, trigger,
     invalidation, target and *expected holding time* - so a position is managed
     by whether its thesis is still valid, not by minute-to-minute noise.

Grounded in the recurring, teachable rules of consistently profitable traders
(researched from their own writing):
  * Richard Wyckoff  - read the Composite Operator: trade with institutional
                       intent, buy the spring / sell the upthrust, wait for the
                       phase to develop (patience is the whole method).
  * Jesse Livermore  - trade the main movement not the ticks; wait for the pivotal
                       point; never average a loser; sit tight when you are right.
  * Paul Tudor Jones - defence first; don't fight the tape; the best trade is often
                       the one you don't make.
  * Mark Minervini   - only confirmed uptrends; buy strength, never weakness;
                       risk 1-2% and only take A+ setups (the trend template).
  * Linda Raschke    - big moves are born from volatility expansion; if it doesn't
                       work quickly, the odds were never there.
  * Al Brooks        - trade with context; never trade the middle of a range.
  * Dan Zanger       - the biggest gains are leaders on volume expansion.
  * Ed Seykota       - the elements of good trading: cut losses, ride winners,
                       manage risk, know when to do nothing.
  * Mark Douglas     - think in probabilities; obey the process, not the outcome;
                       never revenge-trade.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Active market ("stocks" | "forex"). The session playbook is written for the US
# equity session; FX trades ~24/5 so the session gates become a neutral pass.
_market = "stocks"


def set_market(mode: str | None) -> None:
    global _market
    _market = "forex" if str(market or "").lower() == "forex" else "stocks"


def market() -> str:
    return _market

TRADERS: list[dict] = [
    {"name": "Richard Wyckoff", "style": "Composite Operator / phases",
     "rules": ["Trade with institutional intent, not against it; read the tape for footprints.",
               "Buy the spring, sell the upthrust - trades that trap the crowd.",
               "Wait for the phase to develop; patience is the whole method."]},
    {"name": "Jesse Livermore", "style": "Speculation / pivotal points",
     "rules": ["Trade the main movement, not the individual fluctuations.",
               "Wait for the pivotal point; late and correct beats early and wrong.",
               "Never average a loss; sit tight once you are right."]},
    {"name": "Paul Tudor Jones", "style": "Macro / risk-first",
     "rules": ["Defence first - control the downside and the upside takes care of itself.",
               "Don't fight the tape; align with the dominant trend.",
               "The best trade you make may be the one you don't make."]},
    {"name": "Mark Minervini", "style": "Momentum / trend template",
     "rules": ["Trade only in a confirmed uptrend; price above key moving averages.",
               "Buy strength, never average down into a loser.",
               "Risk 1-2% per trade and only take A+ setups."]},
    {"name": "Linda Raschke", "style": "Volatility breakout",
     "rules": ["Big moves are born from volatility expansion.",
               "If the trade doesn't work quickly, get out - time is a cost.",
               "Trade the leaders of the strongest group."]},
    {"name": "Al Brooks", "style": "Price action",
     "rules": ["Only take trades with context; skip the middle of a range.",
               "Wait for a clear signal bar at a familiar level.",
               "Trend bars close near their extremes - that is the momentum footprint."]},
    {"name": "Dan Zanger", "style": "Momentum / leaders",
     "rules": ["Trade the highest relative-strength leaders on volume expansion.",
               "The biggest gains come from bases breaking out on huge volume.",
               "Cut quickly if the breakout fails."]},
    {"name": "Ed Seykota", "style": "Trend following",
     "rules": ["Cut losses; ride winners; manage risk; know when to do nothing.",
               "The elements of good trading are timeless - the process, not the outcome."]},
    {"name": "Mark Douglas", "style": "Psychology",
     "rules": ["Think in probabilities; one trade means nothing.",
               "Your edge is a series - obey the process, not the outcome.",
               "Don't revenge-trade; step away after a loss."]},
]

MAX_SESSION_START_MIN = 9 * 60 + 30   # 09:30 ET
MAX_SESSION_END_MIN = 15 * 60 + 50    # 15:50 ET (avoid the closing auction drift)
NO_OPEN_MIN = 9 * 60 + 35             # don't enter in the first 5 minutes

# Prime windows: the times of day with the best follow-through for our setups.
_PHASES = [
    (9 * 60 + 35, 10 * 60, "opening_drive", 1.0),
    (10 * 60, 11 * 60 + 30, "morning_trend", 1.0),
    (11 * 60 + 30, 13 * 60 + 30, "midday_lull", 0.7),
    (13 * 60 + 30, 15 * 60 + 45, "afternoon_trend", 1.0),
    (15 * 60 + 45, 15 * 60 + 50, "power_hour", 1.0),
]


def session_phase(now: datetime | None = None) -> dict:
    """Which phase of the session are we in, and how should we behave?"""
    now = now or datetime.now(ET)
    if _market == "forex":
        return {"phase": "fx_session", "size_mult": 1.0, "note": "24/5 FX session"}
    m = now.hour * 60 + now.minute
    for start, end, name, mult in _PHASES:
        if start <= m < end:
            if name in ("morning_trend", "opening_drive", "afternoon_trend"):
                note = "prime trend window"
            elif name == "midday_lull":
                note = "midday lull - chop risk"
            else:
                note = "power hour - momentum"
            return {"phase": name, "size_mult": mult, "note": note}
    if m < MAX_SESSION_START_MIN:
        return {"phase": "premarket", "size_mult": 0.0, "note": "pre-open"}
    return {"phase": "after_hours", "size_mult": 0.0, "note": "after close"}


def session_ok(now: datetime | None = None) -> tuple[bool, str]:
    """Prime-hours filter: skip the chaotic open and the closing auction drift."""
    now = now or datetime.now(ET)
    if _market == "forex":
        # FX runs Sunday 22:00 UTC -> Friday 22:00 UTC; otherwise always tradeable.
        wd = now.astimezone(ZoneInfo("UTC")).weekday()
        return (wd < 5, "24/5 FX session" if wd < 5 else "FX weekend - market closed")
    m = now.hour * 60 + now.minute
    if m < NO_OPEN_MIN:
        return False, "pre-open / opening chop (first 5 min)"
    if m > MAX_SESSION_END_MIN:
        return False, "after 15:50 close risk"
    return True, session_phase(now)["note"]


def evaluate(sym: str, ctx: dict, htf: dict | None, market: dict | None,
             min_rvol: float = 0.8, require_trend: bool = True,
             market_veto: bool = False, now: datetime | None = None) -> dict:
    """Return the elite quality verdict for a proposed entry.

    ok      - may this trade be taken at all (no hard veto + score >= threshold)
    score   - 0..1 quality score
    notes   - positive confirmations worth journalling
    veto    - disqualifying reasons (empty when the name passes)
    """
    feats = ctx.get("features") or {}
    reasons = " ".join(ctx.get("reasons") or [])
    direction = ctx.get("direction") or (1 if ctx.get("action") == "BUY" else -1)
    regime = ctx.get("regime") or "RANGE"
    conf = float(ctx.get("confidence") or 0.0)
    rvol = float(feats.get("rvol") or 1.0)
    adx = float(feats.get("adx") or 0.0)
    notes: list[str] = []
    veto: list[str] = []
    score = 0.0

    htf_trend = int((htf or {}).get("trend") or 0)
    htf_label = (htf or {}).get("label") or "OFF"

    # 1) Trade with the higher-timeframe line of least resistance (PTJ/Livermore).
    if htf_trend and htf_trend == direction:
        score += 0.30
        notes.append(f"with HTF {htf_label} trend")
    elif htf_trend and htf_trend != direction:
        if require_trend:
            veto.append(f"fights HTF {htf_label} trend")
        else:
            score -= 0.15
            notes.append(f"counter-trend to {htf_label}")

    # 2) Participation / volume expansion (Zanger/Wyckoff/Livermore).
    if rvol >= 1.3:
        score += 0.20
        notes.append(f"volume expansion {rvol:.1f}x")
    elif rvol >= 1.0:
        score += 0.10
        notes.append(f"decent volume {rvol:.1f}x")
    elif rvol < min_rvol:
        veto.append(f"dead volume {rvol:.1f}x")

    # 3) Trend strength - avoid the middle of a range (Brooks/Raschke).
    if adx >= 25:
        score += 0.15
        notes.append(f"strong trend ADX {adx:.0f}")
    elif adx < 15:
        if "stop-hunt" in reasons or "sweep" in reasons or "reversal" in reasons:
            score += 0.05
            notes.append("range-extreme reversal (low ADX)")
        else:
            veto.append(f"choppy tape ADX {adx:.0f}")

    # 4) Setup quality - what elite traders actually wait for.
    setup = 0.0
    if "breakout" in reasons or "broke value-area" in reasons or "broke range" in reasons:
        setup += 0.15
        notes.append("breakout setup")
    if "pullback" in reasons or "value-area" in reasons or "VWAP" in reasons:
        setup += 0.10
        notes.append("pullback-to-value setup")
    if "stop-hunt" in reasons or "sweep" in reasons or "reversal" in reasons:
        setup += 0.15
        notes.append("liquidity-sweep reversal")
    score += min(setup, 0.20)

    # 4b) Session context - the same setup is worth less in the midday chop and
    # more in the trend windows (PTJ: don't fight the tape; Wyckoff: wait for the
    # phase). Breakouts in the lull are the classic failure.
    ph = session_phase(now)
    if ph["phase"] in ("morning_trend", "afternoon_trend", "opening_drive"):
        score += 0.05
        notes.append(f"prime window ({ph['phase']})")
    elif ph["phase"] == "midday_lull":
        if "breakout" in reasons:
            score -= 0.10
            notes.append("breakout in midday lull (lower odds)")
        else:
            score -= 0.05
    elif ph["phase"] == "power_hour":
        score += 0.03

    # 5) Don't fight the tape / breadth (PTJ).
    bias = float((market or {}).get("bias") or 0.0)
    if bias and direction and (bias > 0) == (direction > 0):
        score += 0.10
        notes.append(f"aligned with breadth {(market or {}).get('label')}")
    elif bias and direction and abs(bias) >= 0.35 and (bias > 0) != (direction > 0):
        if market_veto:
            veto.append(f"against strong breadth {(market or {}).get('label')}")
        else:
            score -= 0.10

    # 6) Conviction (Douglas: only A+ setups).
    if conf >= 0.80:
        score += 0.10
        notes.append("high conviction")
    elif conf < 0.55:
        score -= 0.10

    # 7) Slight premium for trading in a confirmed trend regime.
    if "TREND" in str(regime).upper():
        score += 0.05

    score = max(0.0, min(1.0, score))
    return {"ok": not veto, "score": round(score, 3), "notes": notes,
            "veto": veto, "htf": htf_label, "phase": session_phase()[ "phase"]}


def _setup_of(ctx: dict) -> str:
    r = " ".join(ctx.get("reasons") or []).lower()
    if "sweep" in r or "stop-hunt" in r:
        return "liquidity-sweep reversal"
    if "breakout" in r or "broke value-area" in r or "broke range" in r:
        return "breakout"
    if "trend_pullback" in r or "pullback" in r or "vwap" in r:
        return "trend pullback"
    if "mean_reversion" in r or "oversold" in r or "overbought" in r:
        return "mean reversion"
    if "momentum" in r:
        return "momentum continuation"
    return "trend continuation"


def thesis(sym: str, ctx: dict, htf: dict | None = None,
           now: datetime | None = None) -> dict:
    """Turn a signal into an explicit human plan for the position.

    Returns setup / trigger / invalidation / target / expected hold, so the
    position is later managed by whether the thesis still holds - not by noise.
    """
    direction = ctx.get("direction") or (1 if ctx.get("action") == "BUY" else -1)
    side = "long" if direction > 0 else "short"
    setup = _setup_of(ctx)
    entry = float(ctx.get("entry") or ctx.get("price") or 0.0)
    stop = float(ctx.get("stop") or 0.0)
    target = float(ctx.get("target") or 0.0)
    risk = abs(entry - stop) or (entry * 0.01)
    ph = session_phase(now)

    if setup in ("trend pullback", "breakout", "momentum continuation", "trend continuation"):
        hold = "intraday trend - hold while price holds above the invalidation and VWAP"
        patience = "high"
    elif setup == "liquidity-sweep reversal":
        hold = "let the reclaim run back to the range midpoint / opposite pool"
        patience = "high"
    else:  # mean reversion
        hold = "take profit into the mean (VWAP / mid-band); do not marry it"
        patience = "medium"

    htf_label = (htf or {}).get("label", "OFF")
    thesis_text = (
        f"{side.upper()} {sym} - {setup} in the {ph['phase'].replace('_', ' ')}. "
        f"Trigger {entry:.2f}. "
        f"Invalidation {stop:.2f} ({(stop / entry - 1) * direction * 100:+.2f}%, "
        f"{risk / entry * 100:.2f}% risk). "
        f"Objective {target:.2f} ({((target / entry) - 1) * direction * 100:+.2f}%). "
        f"HTF {htf_label}. Hold: {hold}."
    ) if entry else f"{side.upper()} {sym} - {setup}."
    return {
        "setup": setup,
        "side": side,
        "trigger": round(entry, 4),
        "invalidation": round(stop, 4),
        "objective": round(target, 4),
        "risk_per_share": round(risk, 4),
        "risk_pct": round(risk / entry, 4) if entry else 0.0,
        "expected_hold": hold,
        "patience": patience,
        "phase": ph["phase"],
        "text": thesis_text,
    }


def context_block(limit: int = 3) -> str:
    """Compact playbook text for grounding the LLM analyst prompt."""
    lines = ["Elite day-trader playbook (obey these):"]
    for t in TRADERS[:limit]:
        lines.append(f"- {t['name']} ({t['style']}): " + " ".join(t["rules"]))
    lines.append("- Session: trade the trend windows (open drive, morning, afternoon); "
                 "the midday lull is chop - fade extremes or stand aside.")
    return "\n".join(lines)
