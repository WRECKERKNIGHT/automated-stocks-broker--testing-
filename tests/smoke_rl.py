"""Smoke test: RL regime-contextual bandit (app/rl.py) + regime-aware storage."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import storage
from app.config import settings
from app.rl import PolicyLearner


def _rows() -> list[dict]:
    now = time.time()
    fake = []
    for i in range(6):
        ts = now - i * 3600
        fake.append({"ts": ts, "signal": "momentum_long", "regime": "TREND_UP",
                     "pnl": 200.0, "ret": 0.02, "win": 1})
        fake.append({"ts": ts, "signal": "momentum_long", "regime": "RANGE",
                     "pnl": -200.0, "ret": -0.02, "win": 0})
        fake.append({"ts": ts, "signal": "mean_reversion_long", "regime": "RANGE",
                     "pnl": 200.0, "ret": 0.02, "win": 1})
        fake.append({"ts": ts, "signal": "mean_reversion_long", "regime": "TREND_UP",
                     "pnl": -200.0, "ret": -0.02, "win": 0})
    # below min_obs -> must stay neutral / absent
    fake.append({"ts": now, "signal": "thin_sig", "regime": "TREND_UP",
                 "pnl": 50.0, "ret": 0.05, "win": 1})
    fake.append({"ts": now - 60, "signal": "thin_sig", "regime": "TREND_UP",
                 "pnl": 50.0, "ret": 0.05, "win": 1})
    return fake


def test_bandit() -> None:
    orig = storage.recent_signal_outcomes
    storage.recent_signal_outcomes = lambda limit=5000: _rows()
    try:
        learner = PolicyLearner()
        up = learner.contextual_weights("TREND_UP", ttl=0, explore=False)
        rng = learner.contextual_weights("RANGE", ttl=0, explore=False)
        none = learner.contextual_weights("HIGH_VOL", ttl=0, explore=False)
        summary = learner.summary()
    finally:
        storage.recent_signal_outcomes = orig

    print("TREND_UP:", up)
    print("RANGE:   ", rng)
    # contextual: momentum pays in trends, mean-reversion pays in ranges - and vice versa
    assert up["momentum_long"] > 1.0, up
    assert up["mean_reversion_long"] < 1.0, up
    assert rng["mean_reversion_long"] > 1.0, rng
    assert rng["momentum_long"] < 1.0, rng
    assert all(settings.rl_floor <= v <= settings.rl_ceil for v in up.values())
    # thin arm below min_obs is not trusted
    assert "thin_sig" not in up
    # unseen regime -> no opinions
    assert none == {}
    # summary is populated and marks regime + sample size
    assert any(a["regime"] == "RANGE" and a["n"] == 6 for a in summary), summary
    print("contextual arm summary head:", summary[0])
    print("RL contextual bandit OK (context-sensitive weights)")


def test_storage_regime() -> None:
    storage.init_db()
    storage.log_signal_outcomes("SMOKE_RL", ["rl_sig"], 12.0, 0.015, regime="TREND_UP")
    rows = storage.recent_signal_outcomes(limit=20)
    hit = [r for r in rows if r["signal"] == "rl_sig"]
    assert hit and hit[0]["regime"] == "TREND_UP", hit
    print("storage: regime column roundtrip OK")


def main() -> None:
    storage.init_db()
    test_storage_regime()
    test_bandit()
    print("ALL RL CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
