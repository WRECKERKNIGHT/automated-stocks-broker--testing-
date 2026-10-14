"""Market pulse: the "what's going on right now" layer.

Aggregates the live wire (news / movers / most-active / ideas) into a single
digest and mixes in a rotating library of *tips* plus a curated shelf of
notable *talks* (lectures, interviews, podcasts) worth watching. Talks use
search links so they never rot.
"""
from __future__ import annotations

import random
import time

from . import knowledge


def _yt(q: str) -> str:
    return "https://www.youtube.com/results?search_query=" + q.replace(" ", "+")


# Curated trading talks / lectures / interviews. kind: lecture | interview | podcast.
TALKS: list[dict] = [
    {"title": "Trading in the Zone - the nature of trading", "speaker": "Mark Douglas",
     "kind": "lecture", "why": "The psychology foundation: probabilities, not predictions.",
     "url": _yt("Mark Douglas trading in the zone lecture")},
    {"title": "Psychology of Human Misjudgment", "speaker": "Charlie Munger",
     "kind": "lecture", "why": "The bias catalogue that quietly drives bad trades.",
     "url": _yt("Charlie Munger psychology of human misjudgment")},
    {"title": "How the Economic Machine Works", "speaker": "Ray Dalio",
     "kind": "lecture", "why": "Macro regime framing for the top-down context.",
     "url": _yt("Ray Dalio how the economic machine works")},
    {"title": "Lost Tree Club talk", "speaker": "Stanley Druckenmiller",
     "kind": "interview", "why": "Concentration, conviction and cutting losers fast.",
     "url": _yt("Stanley Druckenmiller Lost Tree Club")},
    {"title": "A rare conversation", "speaker": "Jim Simons",
     "kind": "interview", "why": "Why systematic, data-driven edges beat discretion.",
     "url": _yt("Jim Simons rare interview MIT")},
    {"title": "Street Smarts - short-term patterns", "speaker": "Linda Raschke",
     "kind": "lecture", "why": "Practical swing/intraday pattern playbook.",
     "url": _yt("Linda Raschke street smarts lecture")},
    {"title": "The market is a discounting mechanism", "speaker": "Ed Seykota",
     "kind": "interview", "why": "Trend following and emotional self-mastery.",
     "url": _yt("Ed Seykota interview trend following")},
    {"title": "Price action seminars", "speaker": "Al Brooks",
     "kind": "lecture", "why": "Bar-by-bar reading of intraday structure.",
     "url": _yt("Al Brooks price action seminar")},
    {"title": "Come into my trading room", "speaker": "Alexander Elder",
     "kind": "lecture", "why": "The three M's: Mind, Method, Money.",
     "url": _yt("Alexander Elder come into my trading room lecture")},
    {"title": "Berkshire annual meeting Q&A", "speaker": "Warren Buffett",
     "kind": "interview", "why": "Moats, patience and margin of safety in practice.",
     "url": _yt("Warren Buffett Berkshire annual meeting highlights")},
    {"title": "Skin in the Game", "speaker": "Nassim Taleb",
     "kind": "lecture", "why": "Asymmetry, fragility and tail-risk thinking.",
     "url": _yt("Nassim Taleb skin in the game talk")},
    {"title": "Trading nuts and bolts", "speaker": "Peter Brandt",
     "kind": "interview", "why": "Classic chart patterns and risk-first execution.",
     "url": _yt("Peter Brandt trading interview")},
    {"title": "The little guy can beat the market", "speaker": "Chris Camillo",
     "kind": "talk", "why": "Social-arbitrage: spotting demand before the tape.",
     "url": _yt("Chris Camillo social arbitrage TED")},
    {"title": "Trend following - the complete trader", "speaker": "Michael Covel",
     "kind": "podcast", "why": "Cross-asset trend systems and survival math.",
     "url": _yt("Michael Covel trend following interview")},
    {"title": "Market Wizards conversations", "speaker": "Jack Schwager",
     "kind": "interview", "why": "Common threads across the greats: cut losses, let winners run.",
     "url": _yt("Jack Schwager market wizards interview")},
    {"title": "Reminiscences of a Stock Operator", "speaker": "Edwin Lefevre (audiobook)",
     "kind": "audiobook", "why": "Timeless tape-reading and the cost of stubbornness.",
     "url": _yt("Reminiscences of a Stock Operator audiobook")},
    {"title": "Options, volatility and tail hedges", "speaker": "Universa / Mark Spitznagel",
     "kind": "interview", "why": "Convex payoff thinking for catastrophic risk.",
     "url": _yt("Mark Spitznagel Universa interview")},
    {"title": "Trading for a living - building a system", "speaker": "Van Tharp",
     "kind": "lecture", "why": "Position sizing and expectancy over entries.",
     "url": _yt("Van Tharp position sizing expectancy lecture")},
]


def talks(query: str | None = None, limit: int = 12) -> list[dict]:
    rows = TALKS
    if query:
        q = query.lower()
        rows = [t for t in rows
                if q in t["title"].lower() or q in t["speaker"].lower() or q in t["kind"].lower()]
    return rows[: max(1, limit)]


def tip(seed: int | None = None) -> str:
    """One rotating actionable tip - mixes the trading library with common sense."""
    pool = [b["lessons"][0] for b in knowledge.all_books() if b.get("lessons")]
    pool += [
        "Trade the plan, not the P&L.",
        "When unsure, do nothing - no trade is a position.",
        "Cut losers at the stop; never widen it.",
        "Size so a full stop-out is boring, not painful.",
        "The best setups are rare; patience pays the bills.",
        "Add to winners, not to losers.",
    ]
    rng = random.Random(seed if seed is not None else int(time.time() // 3600))
    return rng.choice(pool)


def digest(news: list[dict] | None, movers: dict | None, most_active: list[dict] | None,
           ideas: dict | None) -> dict:
    """Assemble the live 'everything going on' snapshot."""
    news = news or []
    movers = movers or {}
    ideas = ideas or {}
    backdrop = ideas.get("briefing", {}) or {}
    return {
        "ts": time.time(),
        "tip": tip(),
        "wire": [{"symbol": n.get("symbol"), "headline": n.get("headline"),
                  "ts": n.get("ts"), "source": n.get("source")} for n in news[:25]],
        "gainers": (movers.get("gainers") or [])[:8],
        "losers": (movers.get("losers") or [])[:8],
        "most_active": (most_active or [])[:10],
        "ideas_count": len(ideas.get("setups") or []),
        "breadth": backdrop,
        "talks": talks(),
    }
