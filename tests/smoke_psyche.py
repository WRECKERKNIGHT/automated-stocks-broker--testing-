"""Smoke test: trader psychology / discipline governor (app/psyche.py)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.psyche import MindConfig, TraderMind


def main() -> None:
    m = TraderMind(MindConfig(loss_streak_cooldown=3, cooldown_minutes=30,
                              tilt_streak=4, max_trades_window=100))
    m.start_session(100_000)
    t = time.time()

    m.observe_equity(100_000, t)
    print("initial:", m.state, "iq", m.iq(), "mult", m.size_multiplier(t))
    assert m.state == "CALM"
    assert m.can_trade(t)[0] is True

    for _ in range(5):
        m.observe_trade(90, t); t += 10
    print("after 5 wins:", m.state, "win_streak", m.win_streak, "mult", m.size_multiplier(t))
    assert m.state == "CONFIDENT"

    for _ in range(3):
        m.observe_trade(-90, t); t += 10
    ok, why = m.can_trade(t)
    print("after 3 losses:", m.state, "cooldown_remaining", m.cooldown_remaining(t), "->", ok, why)
    assert ok is False and "cooling down" in why

    t += 31 * 60
    ok, why = m.can_trade(t)
    print("after cooldown:", m.state, "can_trade", ok, "mult", m.size_multiplier(t))
    assert ok is True
    assert m.size_multiplier(t) <= 0.5

    m.observe_trade(-50, t); t += 5
    print("tilted check:", m.state, "mult", m.size_multiplier(t))
    assert m.state == "TILTED"
    assert m.size_multiplier(t) == 0.0
    assert m.can_trade(t)[0] is False

    m2 = TraderMind(MindConfig(loss_budget_frac=0.5))
    m2.start_session(100_000)
    m2.observe_equity(100_000)
    m2.observe_equity(102_000)
    m2.observe_equity(101_500)
    print("profit ok, floor", m2.snapshot()["protect_floor"], "halted", m2.halted)
    assert m2.halted is False
    t2 = time.time()
    m2.observe_equity(100_800, t2)
    print("gave back too much -> paused:", m2.halted, "cooldown", round(m2.cooldown_remaining(t2)))
    assert m2.halted is False                     # a give-back pauses, it does not kill the day
    assert m2.can_trade(t2)[0] is False
    assert m2.cooldown_remaining(t2) > 0
    assert m2.can_trade(t2 + 26 * 60)[0] is True  # recovers after the pause
    m2.resume()
    assert m2.halted is False and m2.can_trade(t2)[0] is True

    m3 = TraderMind(MindConfig(max_trades_window=3, window_minutes=60))
    m3.start_session(100_000)
    m3.observe_equity(100_000)
    for i in range(4):
        m3.observe_trade(10, time.time())
    ok, why = m3.can_trade()
    print("overtrading guard ->", ok, why)
    assert ok is False and "overtrading" in why

    snap = m.snapshot()
    print("snapshot keys:", sorted(snap.keys()))
    print("ALL PSYCHE CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
