"""Trader psychology & discipline governor.

Markets are not lost to bad signals - they are lost to bad behaviour. This layer
models the human side of a desk and enforces the rules a disciplined trader would
enforce on themselves:

  * emotional state     - CALM / CONFIDENT / CAUTIOUS / STRESSED / FRUSTRATED / TILTED
  * patience & cooldown - after a losing streak the trader sits out and then returns at half size
  * overtrading guard   - caps entries inside a rolling window
  * trading IQ          - rolling win rate / profit factor / expectancy -> a 0..100 self-grade
  * adaptive sizing     - bet smaller when the recent edge decays, never above a cap
  * loss budget         - total give-back is bounded relative to realised profit
  * profit protection   - once in profit, a rising equity floor stops the desk giving it all back

It is deliberately stateful: call observe_equity() every scan and observe_trade()
for every realised P&L, then ask can_trade() / size_multiplier() before entering.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class MindConfig:
    size_calm: float = 1.0
    size_confident: float = 1.15
    size_cautious: float = 0.6
    size_stressed: float = 0.4
    size_frustrated: float = 0.25
    size_tilted: float = 0.0
    size_cap: float = 1.25

    loss_streak_cooldown: int = 3
    cooldown_minutes: float = 30.0
    half_size_minutes: float = 60.0

    max_trades_window: int = 8
    window_minutes: float = 60.0

    loss_budget_frac: float = 0.5
    daily_loss_frac: float = 0.025
    min_protect_profit_frac: float = 0.004   # ignore give-back until peak profit is meaningful
    profit_pause_minutes: float = 25.0       # a profit give-back pauses the desk, does not kill the day

    drawdown_caution: float = 0.03
    drawdown_stress: float = 0.06
    drawdown_tilt: float = 0.10

    tilt_streak: int = 4
    confident_winrate: float = 0.60

    history: int = 200


_STATE_RANK = {"TILTED": 6, "FRUSTRATED": 5, "STRESSED": 4, "CAUTIOUS": 3,
               "CONFIDENT": 2, "CALM": 1, "HALTED": 7}


class TraderMind:
    def __init__(self, cfg: MindConfig | None = None) -> None:
        self.cfg = cfg or MindConfig()
        self.pnl_hist: deque[float] = deque(maxlen=self.cfg.history)
        self.events: deque[dict] = deque(maxlen=40)
        self.trade_times: deque[float] = deque(maxlen=200)
        self.loss_streak = 0
        self.win_streak = 0
        self.start_equity: float | None = None
        self.peak_equity: float | None = None
        self.equity: float | None = None
        self.day_start_equity: float | None = None
        self.state = "CALM"
        self.halted = False
        self.halt_reason = ""
        self.cooldown_until = 0.0
        self.half_size_until = 0.0
        self.discipline = 100.0
        self.violations = {"cooldown_hits": 0, "tilt_events": 0, "overtrade_hits": 0,
                           "profit_floor_hits": 0, "daily_stop_hits": 0}

    # ------------------------------------------------------------------ inputs
    def start_session(self, equity: float) -> None:
        self.day_start_equity = equity
        self.start_equity = equity
        self.halted = False
        self.halt_reason = ""
        self.cooldown_until = 0.0
        self._record("session", f"new session at {equity:,.2f}")

    def resume(self) -> None:
        """Clear a halt / cooldown so the desk can trade again (manual override)."""
        self.halted = False
        self.halt_reason = ""
        self.cooldown_until = 0.0
        self.half_size_until = 0.0
        self.loss_streak = 0
        if self.equity:
            self.start_equity = self.equity
            self.peak_equity = self.equity
        self._record("resume", "manual resume - halt/cooldown cleared")

    def observe_equity(self, equity: float, now: float | None = None) -> None:
        now = now or time.time()
        if self.start_equity is None:
            self.start_equity = equity
            self.day_start_equity = equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        self.equity = equity

        if not self.halted:
            peak_profit = max(0.0, self.peak_equity - self.start_equity)
            # only guard a *meaningful* peak: a few dollars of pre-market drift on a
            # large account must not trip the floor (that halted the desk all day).
            min_profit = (self.start_equity or 0.0) * self.cfg.min_protect_profit_frac
            if peak_profit > min_profit > 0:
                floor = self.peak_equity - peak_profit * self.cfg.loss_budget_frac
                if equity < floor and now >= self.cooldown_until:
                    # a give-back pauses the desk (recoverable), it does not end the day
                    self.violations["profit_floor_hits"] += 1
                    self.cooldown_until = now + self.cfg.profit_pause_minutes * 60
                    self.half_size_until = self.cooldown_until + self.cfg.half_size_minutes * 60
                    self._record("pause", f"profit protection: gave back "
                                          f">{self.cfg.loss_budget_frac:.0%} of peak profit "
                                          f"({self.peak_equity:,.0f} -> {equity:,.0f}) - "
                                          f"pausing {self.cfg.profit_pause_minutes:.0f}m")
            if self.day_start_equity and not self.halted:
                day_ret = (equity - self.day_start_equity) / self.day_start_equity
                if day_ret <= -self.cfg.daily_loss_frac:
                    self.violations["daily_stop_hits"] += 1
                    self._halt(f"daily emotional stop hit ({day_ret:.1%})")

        self._refresh_state(now)

    def observe_trade(self, pnl: float, now: float | None = None) -> None:
        now = now or time.time()
        self.pnl_hist.append(float(pnl))
        self.trade_times.append(now)
        if pnl < 0:
            self.loss_streak += 1
            self.win_streak = 0
            if self.loss_streak >= self.cfg.loss_streak_cooldown:
                self.cooldown_until = now + self.cfg.cooldown_minutes * 60
                self.half_size_until = self.cooldown_until + self.cfg.half_size_minutes * 60
                self.violations["cooldown_hits"] += 1
                self._record("cooldown", f"{self.loss_streak} straight losses - "
                                         f"sitting out {self.cfg.cooldown_minutes:.0f}m")
        else:
            self.win_streak += 1
            self.loss_streak = 0
        self._refresh_state(now)

    # ------------------------------------------------------------------ gates
    def cooldown_remaining(self, now: float | None = None) -> float:
        now = now or time.time()
        return max(0.0, self.cooldown_until - now)

    def can_trade(self, now: float | None = None) -> tuple[bool, str]:
        now = now or time.time()
        if self.halted:
            return False, self.halt_reason
        if now < self.cooldown_until:
            return False, (f"cooling down after {self.loss_streak} straight losses "
                           f"({self.cooldown_remaining(now) / 60:.0f}m left)")
        window = [t for t in self.trade_times if now - t <= self.cfg.window_minutes * 60]
        if len(window) >= self.cfg.max_trades_window:
            self.violations["overtrade_hits"] += 1
            return False, (f"overtrading guard: {len(window)} trades in "
                           f"{self.cfg.window_minutes:.0f}m")
        if self.state == "TILTED":
            return False, "tilted - protecting capital, sitting out"
        return True, ""

    def size_multiplier(self, now: float | None = None) -> float:
        now = now or time.time()
        if self.halted or self.state == "TILTED":
            return 0.0
        base = {
            "CALM": self.cfg.size_calm,
            "CONFIDENT": self.cfg.size_confident,
            "CAUTIOUS": self.cfg.size_cautious,
            "STRESSED": self.cfg.size_stressed,
            "FRUSTRATED": self.cfg.size_frustrated,
        }.get(self.state, 0.5)
        adaptive = min(1.2, max(0.4, self.iq() / 60.0))
        mult = base * adaptive
        if now < self.half_size_until:
            mult = min(mult, 0.5)
        return float(max(0.0, min(self.cfg.size_cap, mult)))

    # ------------------------------------------------------------------ scoring
    def iq(self) -> float:
        n = len(self.pnl_hist)
        if n < 5:
            return 50.0
        wins = [p for p in self.pnl_hist if p > 0]
        losses = [p for p in self.pnl_hist if p < 0]
        wr = len(wins) / n
        gp = sum(wins)
        gl = -sum(losses)
        pf = (gp / gl) if gl > 0 else (3.0 if gp > 0 else 0.0)
        score = 40 + 60 * (wr - 0.5) + 10 * (min(pf, 3.0) - 1.0)
        return float(max(0.0, min(100.0, round(score, 1))))

    def recent_edge(self) -> tuple[float, float, float]:
        n = len(self.pnl_hist)
        if n == 0:
            return 0.5, 0.0, 0.0
        wins = [p for p in self.pnl_hist if p > 0]
        losses = [p for p in self.pnl_hist if p < 0]
        wr = len(wins) / n
        exp = sum(self.pnl_hist) / n
        gp = sum(wins)
        gl = -sum(losses)
        pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
        return wr, exp, pf

    # ------------------------------------------------------------------ state
    def _drawdown(self) -> float:
        if not self.peak_equity or not self.equity:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    def _refresh_state(self, now: float) -> None:
        dd = self._drawdown()
        wr, _, _ = self.recent_edge()
        prev = self.state
        if self.halted:
            self.state = "HALTED"
        elif self.loss_streak >= self.cfg.tilt_streak or dd >= self.cfg.drawdown_tilt:
            self.state = "TILTED"
        elif self.loss_streak >= 2 or dd >= self.cfg.drawdown_stress:
            self.state = "FRUSTRATED" if self.loss_streak >= 2 else "STRESSED"
        elif dd >= self.cfg.drawdown_caution:
            self.state = "CAUTIOUS"
        elif (self.win_streak >= 2 and len(self.pnl_hist) >= 5 and wr >= self.cfg.confident_winrate):
            self.state = "CONFIDENT"
        else:
            self.state = "CALM"

        if self.state == "TILTED" and prev != "TILTED":
            self.violations["tilt_events"] += 1
        penalty = (10 * self.violations["tilt_events"] + 6 * self.violations["cooldown_hits"]
                   + 4 * self.violations["overtrade_hits"] + 8 * self.violations["profit_floor_hits"]
                   + 8 * self.violations["daily_stop_hits"])
        self.discipline = float(max(0.0, round(100.0 - penalty + 2 * min(self.win_streak, 5), 1)))

        if self.state != prev:
            self._record("state", f"{prev} -> {self.state}")

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        self._record("halt", reason)

    def _record(self, kind: str, msg: str) -> None:
        self.events.appendleft({"ts": time.time(), "kind": kind, "msg": msg})

    # ------------------------------------------------------------------ output
    def snapshot(self, now: float | None = None) -> dict:
        now = now or time.time()
        wr, exp, pf = self.recent_edge()
        peak_profit = max(0.0, (self.peak_equity or 0.0) - (self.start_equity or 0.0))
        floor = (self.peak_equity - peak_profit * self.cfg.loss_budget_frac
                 if self.peak_equity and peak_profit > 0 else None)
        can, why = self.can_trade(now)
        return {
            "state": self.state,
            "mood": self.state,
            "size_mult": round(self.size_multiplier(now), 3),
            "discipline": self.discipline,
            "iq": self.iq(),
            "can_trade": can,
            "block_reason": why,
            "loss_streak": self.loss_streak,
            "win_streak": self.win_streak,
            "cooldown_remaining": round(self.cooldown_remaining(now)),
            "half_size_remaining": round(max(0.0, self.half_size_until - now)),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "drawdown": round(self._drawdown(), 4),
            "peak_profit": round(peak_profit, 2),
            "protect_floor": round(floor, 2) if floor is not None else None,
            "win_rate": round(wr, 3),
            "expectancy": round(exp, 2),
            "profit_factor": (round(pf, 2) if math.isfinite(pf) else None),
            "trades_seen": len(self.pnl_hist),
            "violations": dict(self.violations),
            "events": list(self.events)[:12],
        }
