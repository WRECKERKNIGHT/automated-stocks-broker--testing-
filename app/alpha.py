"""Signal alpha-decay weighting.

Not every signal keeps its edge forever. Classic "alpha decay" says a signal's
information coefficient fades over time. This tracker gives each named signal a
recency-weighted score from its own realised outcomes and turns it into a
weight multiplier:

  * signals whose recent trades made money          -> up-weighted (capped)
  * signals whose recent trades lost money          -> down-weighted (floored)
  * signals with too little history                 -> neutral (1.0)

The half-life controls how fast old evidence is forgotten, i.e. how quickly an
alpha is allowed to decay. Everything is read from the signal_outcomes table
that the bot writes on every realised close.
"""
from __future__ import annotations

import math
import time

from . import storage
from .config import settings


class AlphaTracker:
    def __init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._ts = 0.0

    def edge_weights(self, ttl: float = 60.0) -> dict[str, float]:
        """Return {signal_name -> weight multiplier} using decayed expectancy."""
        if not settings.alpha_decay_enabled:
            return {}
        now = time.time()
        if self._cache and now - self._ts < ttl:
            return self._cache

        rows = storage.recent_signal_outcomes(limit=3000, market=storage.get_market())
        lam = math.log(2.0) / max(1e-6, settings.alpha_half_life_days * 86400.0)
        agg: dict[str, list] = {}
        for r in rows:
            name = r.get("signal")
            if not name:
                continue
            w = math.exp(-(now - float(r.get("ts") or now)) * lam)
            a = agg.setdefault(name, [0.0, 0.0, 0])
            a[0] += w * float(r.get("ret") or 0.0)
            a[1] += w
            a[2] += 1

        out: dict[str, float] = {}
        for name, (num, den, n) in agg.items():
            if n < settings.alpha_min_obs or den <= 0:
                continue
            edge = num / den  # weighted average return fraction per trade
            mult = 1.0 + settings.alpha_gain * math.tanh(edge / 0.01)
            out[name] = round(float(min(settings.alpha_ceil, max(settings.alpha_floor, mult))), 3)

        self._cache = out
        self._ts = now
        return out

    def reset(self) -> None:
        """Invalidate the cache (e.g. after a market-mode switch)."""
        self._cache = {}
        self._ts = 0.0


_tracker = AlphaTracker()


def get_alpha_tracker() -> AlphaTracker:
    return _tracker
