"""Smoke test: cross-asset/breadth, toxic-flow defence, HTF breakout entry."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import cross_asset, mtf, strategy, toxic
from app.config import settings


def _close_df(vals) -> pd.DataFrame:
    return pd.DataFrame({"close": np.asarray(vals, dtype=float)})


def test_cross_asset() -> None:
    up = _close_df(np.linspace(100, 130, 120))
    down = _close_df(np.linspace(130, 100, 120))
    flat = _close_df(np.full(120, 100.0))
    assert cross_asset.asset_score(up) > 0.2
    assert cross_asset.asset_score(down) < -0.2
    assert abs(cross_asset.asset_score(flat)) < 0.2
    assert cross_asset.asset_score(None) == 0.0

    risk_on = cross_asset.assess({"SPY": up, "QQQ": up, "IWM": up})
    risk_off = cross_asset.assess({"SPY": down, "QQQ": down, "IWM": down})
    neutral = cross_asset.assess({"SPY": up, "QQQ": down, "IWM": flat})
    print("cross-asset:", risk_on["label"], risk_on["bias"], "|",
          risk_off["label"], risk_off["bias"], "|", neutral["label"], neutral["bias"])
    assert risk_on["label"] == "RISK_ON"
    assert risk_off["label"] == "RISK_OFF"
    assert cross_asset.assess({})["label"] == "OFF"


def test_toxic() -> None:
    prev_block = settings.toxic_block
    settings.toxic_block = True
    # moderate informed flow that agrees with our direction is NOT adverse -> clear
    clear = toxic.assess({"toxicity": 0.5, "imbalance": 1.0, "divergence": 0.0}, direction=1)
    # ... but a *saturated* book is never CLEAR, even when the raw flow agrees
    # (fail-safe so a mis-computed VPIN can't green-light a full-size entry)
    sat = toxic.assess({"toxicity": 0.95, "imbalance": 1.0, "divergence": 0.0}, direction=1)
    # informed flow against us -> elevated
    elev = toxic.assess({"toxicity": 0.5, "imbalance": -1.0, "divergence": 0.0}, direction=1)
    # heavy flow against us -> toxic
    tox_lvl = toxic.assess({"toxicity": 0.7, "imbalance": -1.0, "divergence": 0.0}, direction=1)
    print("toxic:", clear["level"], sat["level"], elev["level"], tox_lvl["level"],
          "sizes", clear["size_mult"], elev["size_mult"], tox_lvl["size_mult"])
    assert clear["level"] == "CLEAR" and clear["size_mult"] == 1.0
    assert sat["level"] == "ELEVATED" and 0 < sat["size_mult"] < 1.0
    assert elev["level"] == "ELEVATED" and 0 < elev["size_mult"] < 1.0
    assert tox_lvl["level"] == "TOXIC" and tox_lvl["size_mult"] == 0.0
    assert tox_lvl["block"] is True
    # absorption (delta divergence) is adverse even without directional flow
    weak = toxic.assess({"toxicity": 0.5, "imbalance": 0.0, "divergence": 0.0}, direction=0)
    div = toxic.assess({"toxicity": 0.5, "imbalance": 0.0, "divergence": 1.0}, direction=0)
    print("divergence tip:", weak["level"], "->", div["level"])
    assert weak["level"] == "CLEAR" and div["level"] in ("ELEVATED", "TOXIC")
    settings.toxic_block = prev_block


def test_breakout() -> None:
    highs = np.concatenate([np.full(80, 100.0), [101.0, 102.5]])
    lows = np.concatenate([np.full(80, 99.0), [98.5, 97.5]])
    df = pd.DataFrame({"high": highs, "low": lows,
                       "close": np.concatenate([np.full(80, 99.5), [100.5, 102.4]])})
    b = mtf.breakout(df, 20)
    print("breakout up:", b)
    assert b["dir"] == 1

    df2 = df.copy()
    df2["close"] = np.concatenate([np.full(80, 100.5), [99.0, 96.0]])
    assert mtf.breakout(df2, 20)["dir"] == -1

    df3 = df.copy()
    df3["close"] = np.full(82, 99.8)
    assert mtf.breakout(df3, 20)["dir"] == 0


def _trend_df() -> pd.DataFrame:
    n = 260
    idx = pd.date_range("2026-01-02 09:30", periods=n, freq="5min", tz="America/New_York")
    close = 100 + np.linspace(0, 20, n) + np.sin(np.arange(n) / 8) * 0.4
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) + 0.15,
        "low": np.minimum(open_, close) - 0.15, "close": close,
        "volume": 1_000_000.0 * (1 + 0.5 * np.sin(np.arange(n) / 3)),
    }, index=idx)


def test_strategy_integration() -> None:
    old = (settings.alpha_decay_enabled, settings.cross_asset_enabled, settings.toxic_enabled,
           settings.toxic_block, settings.min_confluence)
    settings.alpha_decay_enabled = False
    settings.cross_asset_enabled = True
    settings.toxic_enabled = False          # isolate market/breakout effects
    settings.min_confluence = 1             # isolate market/breakout from the confluence gate
    params = {"regime_method": "heuristic"}
    df = _trend_df()

    on = strategy.analyze("T", df, news_sentiment=0.5, params=params,
                          market={"bias": 1.0, "label": "RISK_ON"})
    off = strategy.analyze("T", df, news_sentiment=0.5, params=params,
                           market={"bias": -1.0, "label": "RISK_OFF"})
    print("market: on conf=%.3f (%s) off conf=%.3f (%s)"
          % (on["confidence"], on["action"], off["confidence"], off["action"]))
    assert on["direction"] != 0, "expected a directional call for the market test"
    assert on["confidence"] > off["confidence"]
    assert on["market_bias"] == 1.0

    brk = strategy.analyze("T", df, news_sentiment=0.5, params=params,
                           htf={"trend": 1, "label": "UP", "strength": 0.9,
                                "breakout": 1, "breakout_reason": "HTF broke high"})
    names = [s["name"] for s in brk["signals"]]
    print("htf breakout signal present:", "htf_breakout" in names)
    assert "htf_breakout" in names

    # toxic block -> forced HOLD (opt-in)
    settings.toxic_enabled = True
    settings.toxic_block = True
    settings.toxic_vpin_extreme = 0.0
    tox = strategy.analyze("T", df, news_sentiment=1.0, params=params,
                          market={"bias": 1.0, "label": "RISK_ON"})
    print("tox-blocked action:", tox["action"], "level", tox["toxicity"]["level"])
    assert tox["action"] == "HOLD" and tox["toxicity"]["level"] == "TOXIC"

    # tox dampener reduces size
    from app.risk import RiskLimits
    ctx = {"action": "BUY", "price": 100.0, "stop": 99.0, "entry": 100.0, "target": 102.0,
           "features": {"atr_pct": 1.0}, "toxicity": {"size_mult": 0.5}}
    strategy.size_decision(ctx, 100_000, RiskLimits(), 0.55, 2.0)
    print("dampen:", ctx["sizing"]["vol_dampen"], ctx["sizing"]["tox_dampen"], ctx["sizing"]["dampen"])
    assert ctx["sizing"]["tox_dampen"] == 0.5
    assert abs(ctx["sizing"]["dampen"] - 0.5) < 1e-9

    (settings.alpha_decay_enabled, settings.cross_asset_enabled, settings.toxic_enabled,
     settings.toxic_block, settings.min_confluence) = old
    print("strategy cross/toxic/breakout integration OK")


def main() -> None:
    test_cross_asset()
    test_toxic()
    test_breakout()
    test_strategy_integration()
    print("ALL CROSS-ASSET / TOXIC / BREAKOUT CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
