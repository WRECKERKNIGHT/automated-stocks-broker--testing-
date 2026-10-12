"""Market-regime detection.

Two engines:
  * heuristic - explainable Gaussian-style classifier from return-vol + trend t-stat
  * HMM       - a fitted Gaussian Hidden Markov Model (app/hmm.py) that decodes the
                latent regime from return/volatility features

`classify(method=...)` selects `heuristic`, `hmm`, or `hybrid` (HMM label, heuristic
metrics). Models are cached per symbol/timeframe and refit periodically.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
import pandas as pd

from .hmm import GaussianHMM, build_features

REGIMES = ["TREND_UP", "TREND_DOWN", "RANGE", "VOLATILE"]

_hmm_cache: dict[str, tuple] = {}
_pending: dict[str, Future] = {}
_hmm_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hmm")
_HMM_TTL = 300.0


def _trend_strength(df: pd.DataFrame, window: int = 50) -> float:
    if len(df) < window:
        window = len(df)
    y = np.log(df["close"].tail(window).to_numpy())
    x = np.arange(len(y))
    if len(y) < 3:
        return 0.0
    coeffs = np.polyfit(x, y, 1)
    resid = y - np.polyval(coeffs, x)
    sd = resid.std() or 1e-9
    return float(coeffs[0] / sd * np.sqrt(len(y)))


def _heuristic(df: pd.DataFrame, vol_lookback: int = 60) -> dict:
    if len(df) < 10:
        return {"regime": "RANGE", "trend_strength": 0.0, "vol_pct": 0.5, "volatility": 0.0}
    ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    vol = ret.rolling(20).std() * np.sqrt(390 * 252)
    vol_now = float(vol.iloc[-1]) if not np.isnan(vol.iloc[-1]) else float(vol.dropna().iloc[-1] or 0)
    hist = vol.dropna().tail(vol_lookback * 5)
    vol_pct = float((hist < vol_now).mean()) if len(hist) > 5 else 0.5
    ts = _trend_strength(df, 60)
    if vol_pct > 0.85:
        regime = "VOLATILE"
    elif ts > 1.2:
        regime = "TREND_UP"
    elif ts < -1.2:
        regime = "TREND_DOWN"
    else:
        regime = "RANGE"
    return {"regime": regime, "trend_strength": ts, "vol_pct": vol_pct,
            "volatility": vol_now, "method": "heuristic"}


def _label_states(model: GaussianHMM) -> dict[int, str]:
    """Map hidden states to human regimes: highest-vol -> VOLATILE, then by mean return."""
    k = model.k
    vol = model.var.sum(axis=1)
    mean = model.mu[:, 0]
    labels: dict[int, str] = {}
    volatile = int(np.argmax(vol))
    labels[volatile] = "VOLATILE"
    rest = [s for s in range(k) if s != volatile]
    rest_sorted = sorted(rest, key=lambda s: mean[s])
    if len(rest_sorted) >= 2:
        labels[rest_sorted[-1]] = "TREND_UP"
        labels[rest_sorted[0]] = "TREND_DOWN"
        for s in rest_sorted[1:-1]:
            labels[s] = "RANGE"
    elif rest_sorted:
        labels[rest_sorted[0]] = "RANGE"
    return labels


def _fit_job(df: pd.DataFrame, symbol: str, timeframe: str):
    X = build_features(df)
    if len(X) < 60:
        raise ValueError("too little data")
    model = GaussianHMM(n_states=4, n_iter=25, restarts=2).fit(X)
    return model, _label_states(model)


def _get_hmm(df: pd.DataFrame, symbol: str, timeframe: str):
    """Returns (model, labels, status). Fits in a background thread so the async
    bot loop never blocks; callers fall back to the heuristic until it is ready."""
    key = f"{symbol}:{timeframe}"
    now = time.time()
    with _hmm_lock:
        cached = _hmm_cache.get(key)
        if cached and now - cached[0] < _HMM_TTL:
            return cached[1], cached[2], "ready"
        fut = _pending.get(key)
        if fut is None:
            _pending[key] = _executor.submit(_fit_job, df.copy(), symbol, timeframe)
            return None, None, "fitting"
    if not fut.done():
        return None, None, "fitting"
    try:
        model, labels = fut.result()
        with _hmm_lock:
            _hmm_cache[key] = (time.time(), model, labels)
            _pending.pop(key, None)
        return model, labels, "ready"
    except Exception:
        with _hmm_lock:
            _pending.pop(key, None)
        return None, None, "failed"


def classify(df: pd.DataFrame, method: str = "hybrid", symbol: str = "",
             timeframe: str = "5Min", vol_lookback: int = 60) -> dict:
    heur = _heuristic(df, vol_lookback)
    if method == "heuristic" or len(df) < 80:
        return heur
    model, labels, status = _get_hmm(df, symbol, timeframe)
    if model is None:
        heur["hmm_status"] = status
        return heur
    try:
        X = build_features(df)
        path = model.viterbi(X)
        probs = model.predict_proba_last(X)
    except Exception:
        return heur
    state = int(path[-1])
    hmm = {
        "regime": labels.get(state, "RANGE"),
        "state": state,
        "state_probs": [round(float(p), 3) for p in probs],
        "loglik": round(float(model.loglik), 2),
    }
    out = dict(heur)
    out.update(hmm)
    out["hmm_status"] = "ready"
    if method == "hmm":
        out["method"] = "hmm"
        return out
    out["heuristic_regime"] = heur["regime"]
    out["method"] = "hybrid"
    return out


def playbook(regime: str) -> dict:
    table = {
        "TREND_UP": {"bias": 1, "style": "pullback/breakout continuation", "size_mult": 1.0},
        "TREND_DOWN": {"bias": -1, "style": "fade rallies / breakdown", "size_mult": 0.8},
        "RANGE": {"bias": 0, "style": "mean-reversion at extremes", "size_mult": 0.7},
        "VOLATILE": {"bias": 0, "style": "reduced size, wider stops, wait for structure", "size_mult": 0.4},
    }
    return table.get(regime, table["RANGE"])
