"""Reinforcement-style adaptive policy: a regime-contextual bandit over signals.

Where `alpha.py` learns one global edge per signal, real edges are conditional:
`mean_reversion_long` can pay in a RANGE and bleed in a trend, while
`momentum_long` is the opposite. This module treats each **signal as an arm** and
the **regime as context**, learning the expected reward of every (signal, regime)
pair online from the same realised outcomes the bot already logs.

Learning rule: a Thompson-sampling Gaussian bandit with empirical-Bayes
shrinkage. For each (signal, regime) arm we keep `n`, `sum(reward)` and
`sum(reward^2)` of the trade return. The posterior mean is shrunk toward the
signal's *global* edge from all regimes (a hierarchical prior), so a thin arm
borrows strength from its siblings instead of over-fitting a handful of trades.
Each decision draws one sample from that posterior - exploration that narrows as
evidence accumulates - and maps it to a weight multiplier.

Honest scope: this is a contextual (multi-armed) bandit, not deep RL - it is
lightweight, interpretable and needs no GPU. It only *re-weights* the signals the
strategy already produces; it never invents trades.
"""
from __future__ import annotations

import math
import random
import time

from . import storage
from .config import settings


class PolicyLearner:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, float]] = {}
        self._ts = 0.0
        self._rng = random.Random(20240517)

    # ---------------------------------------------------------------- stats
    def _tally(self) -> tuple[dict[tuple[str, str], list], dict[str, list]]:
        rows = storage.recent_signal_outcomes(limit=5000)
        cells: dict[tuple[str, str], list] = {}
        glob: dict[str, list] = {}
        for r in rows:
            name = r.get("signal")
            if not name:
                continue
            rw = float(r.get("ret") or 0.0)
            reg = r.get("regime") or "UNKNOWN"
            a = cells.setdefault((name, reg), [0, 0.0, 0.0, 0])  # n, sum, sumsq, wins
            a[0] += 1
            a[1] += rw
            a[2] += rw * rw
            a[3] += int(r.get("win") or 0)
            g = glob.setdefault(name, [0, 0.0, 0, 0])
            g[0] += 1
            g[1] += rw
            g[2] += int(r.get("win") or 0)
        return cells, glob

    @staticmethod
    def _std(sumsq: float, s: float, n: int) -> float:
        if n < 2:
            return settings.rl_prior_scale
        var = max(0.0, (sumsq - s * s / n) / (n - 1))
        return math.sqrt(var) if var > 0 else settings.rl_prior_scale

    def _arm_mult(self, mean: float, sd: float, n_eff: int, explore: bool) -> float:
        draw = mean
        if explore and n_eff > 0:
            draw = mean + self._rng.gauss(0.0, 1.0) * sd / math.sqrt(n_eff)
        mult = 1.0 + settings.rl_gain * math.tanh(draw / max(1e-9, settings.rl_scale))
        return round(float(min(settings.rl_ceil, max(settings.rl_floor, mult))), 3)

    # -------------------------------------------------------------- weights
    def contextual_weights(self, regime: str, ttl: float = 60.0,
                           explore: bool = True) -> dict[str, float]:
        """Return {signal -> multiplier} for signals evidenced in this regime."""
        if not settings.rl_enabled or not regime:
            return {}
        now = time.time()
        cached = self._cache.get(regime)
        if cached is not None and now - self._ts < ttl and not explore:
            return cached

        cells, glob = self._tally()
        kappa = max(0.0, settings.rl_prior_strength)
        out: dict[str, float] = {}
        for (name, reg), (n, s, sumsq, _wins) in cells.items():
            if reg != regime or n < settings.rl_min_obs:
                continue
            g = glob.get(name)
            prior_mean = (g[1] / g[0]) if g and g[0] > 0 else 0.0
            sd = self._std(sumsq, s, n)
            n_eff = n + kappa
            mean = (s + kappa * prior_mean) / n_eff
            out[name] = self._arm_mult(mean, sd, int(n_eff), explore)

        if not explore:
            self._cache[regime] = out
            self._ts = now
        return out

    # -------------------------------------------------------------- summary
    def summary(self, limit: int = 24) -> list[dict]:
        """Flat listing of learned arms for the dashboard / status."""
        cells, glob = self._tally()
        kappa = max(0.0, settings.rl_prior_strength)
        rows: list[dict] = []
        for (name, reg), (n, s, sumsq, wins) in cells.items():
            if n < settings.rl_min_obs:
                continue
            g = glob.get(name)
            prior_mean = (g[1] / g[0]) if g and g[0] > 0 else 0.0
            sd = self._std(sumsq, s, n)
            n_eff = n + kappa
            mean = (s + kappa * prior_mean) / n_eff
            rows.append({
                "signal": name,
                "regime": reg,
                "n": n,
                "mean_ret": round(mean, 5),
                "win_rate": round(wins / n, 3) if n else 0.0,
                "mult": self._arm_mult(mean, sd, int(n_eff), explore=False),
            })
        rows.sort(key=lambda r: r["n"], reverse=True)
        return rows[:limit]


_learner = PolicyLearner()


def get_policy_learner() -> PolicyLearner:
    return _learner
