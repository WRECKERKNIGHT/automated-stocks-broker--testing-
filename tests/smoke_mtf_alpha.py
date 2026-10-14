"""Smoke test: multi-timeframe confirmation (app/mtf.py) + alpha decay (app/alpha.py)."""
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.alpha as alpha_mod
from app import mtf, storage, strategy
from app.alpha import AlphaTracker
from app.config import settings


def _trend_df(n: int = 120) -> pd.DataFrame:
    return pd.DataFrame({"close": np.linspace(100.0, 130.0, n)})


def test_mtf() -> None:
    assert mtf.trend_of(_trend_df())["trend"] == 1
    down = pd.DataFrame({"close": np.linspace(130.0, 100.0, 120)})
    assert mtf.trend_of(down)["trend"] == -1
    flat = pd.DataFrame({"close": np.full(120, 100.0)})
    assert mtf.trend_of(flat)["trend"] == 0
    assert mtf.trend_of(None)["trend"] == 0
    assert mtf.confirm(1, 1) == settings.mtf_align_boost
    assert mtf.confirm(-1, -1) == settings.mtf_align_boost
    assert mtf.confirm(1, -1) == settings.mtf_conflict_penalty
    assert mtf.confirm(0, 1) == 1.0
    print("mtf: trend/confirm OK  aligned x%.2f  conflict x%.2f"
          % (settings.mtf_align_boost, settings.mtf_conflict_penalty))


def test_alpha() -> None:
    now = time.time()
    fake = []
    for i in range(6):
        fake.append({"ts": now - i * 3600, "signal": "winner", "pnl": 100.0,
                     "ret": 0.02, "win": 1})
        fake.append({"ts": now - i * 3600, "signal": "loser", "pnl": -100.0,
                     "ret": -0.02, "win": 0})
        fake.append({"ts": now - i * 3600, "signal": "thin", "pnl": 10.0,
                     "ret": 0.01, "win": 1})
    orig = storage.recent_signal_outcomes
    storage.recent_signal_outcomes = lambda limit=3000: fake
    try:
        w = AlphaTracker().edge_weights(ttl=0)
    finally:
        storage.recent_signal_outcomes = orig
    print("alpha weights:", w)
    assert w["winner"] > 1.0, w
    assert w["loser"] < 1.0, w
    assert settings.alpha_floor <= w["loser"] <= settings.alpha_ceil
    assert settings.alpha_floor <= w["winner"] <= settings.alpha_ceil

    storage.init_db()
    storage.log_signal_outcomes("SMOKE", ["smoke_sig_mtfalpha"], -5.0, -0.01)
    rows = storage.recent_signal_outcomes(limit=20)
    assert any(r["signal"] == "smoke_sig_mtfalpha" for r in rows)
    print("alpha: edge_weights + storage roundtrip OK")


def test_strategy_mtf() -> None:
    n = 260
    idx = pd.date_range("2026-01-02 09:30", periods=n, freq="5min", tz="America/New_York")
    close = 100 + np.linspace(0, 20, n) + np.sin(np.arange(n) / 8) * 0.4
    open_ = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({
        "open": open_,
        "high": np.maximum(open_, close) + 0.15,
        "low": np.minimum(open_, close) - 0.15,
        "close": close,
        "volume": 1_000_000.0 * (1 + 0.5 * np.sin(np.arange(n) / 3)),
    }, index=idx)

    settings.alpha_decay_enabled = False
    settings.mtf_enabled = True
    params = {"regime_method": "heuristic"}

    aligned = strategy.analyze("TEST", df, news_sentiment=1.0, params=params,
                               htf={"trend": 1, "label": "UP", "strength": 0.9})
    conflict = strategy.analyze("TEST", df, news_sentiment=1.0, params=params,
                                htf={"trend": -1, "label": "DOWN", "strength": 0.9})
    print("aligned  dir=%s conf=%.3f mtf_mult=%.2f"
          % (aligned["action"], aligned["confidence"], aligned["mtf_mult"]))
    print("conflict dir=%s conf=%.3f mtf_mult=%.2f"
          % (conflict["action"], conflict["confidence"], conflict["mtf_mult"]))
    assert aligned["direction"] == 1
    assert aligned["confidence"] > conflict["confidence"]
    assert aligned["mtf_mult"] == settings.mtf_align_boost
    assert conflict["mtf_mult"] == settings.mtf_conflict_penalty
    assert "mtf" in aligned and aligned["mtf"]["label"] == "UP"

    settings.mtf_block_on_conflict = True
    veto = strategy.analyze("TEST", df, news_sentiment=1.0, params=params,
                            htf={"trend": -1, "label": "DOWN", "strength": 1.0})
    settings.mtf_block_on_conflict = False
    print("veto -> action=%s blocked=%s" % (veto["action"], veto["mtf_blocked"]))
    assert veto["action"] == "HOLD" and veto["mtf_blocked"] is True

    # no HTF -> neutral, unchanged behaviour
    neutral = strategy.analyze("TEST", df, news_sentiment=1.0, params=params)
    assert neutral["mtf_mult"] == 1.0 and neutral["mtf_blocked"] is False
    print("strategy MTF integration OK")


def main() -> None:
    storage.init_db()
    test_mtf()
    test_alpha()
    test_strategy_mtf()
    print("ALL MTF/ALPHA CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
