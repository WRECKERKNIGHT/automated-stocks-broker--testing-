"""Technical / statistical indicators. No lagging-only indicators as *edge* -
they are context features the strategy combines with regime + order-flow proxies.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def realized_vol(close: pd.Series, window: int = 20, periods_per_year: int = 252 * 390) -> pd.Series:
    logret = np.log(close / close.shift(1))
    return logret.rolling(window).std() * np.sqrt(periods_per_year)


def parkinson_vol(df: pd.DataFrame, window: int = 20, periods_per_year: int = 252 * 390) -> pd.Series:
    """Parkinson high/low volatility estimator - reacts faster than close-based vol."""
    hl = np.log(df["high"] / df["low"]) ** 2
    return np.sqrt(hl.rolling(window).mean() / (4 * np.log(2))) * np.sqrt(periods_per_year)


def vwap(df: pd.DataFrame, session_reset: bool = True) -> pd.Series:
    """Session-anchored VWAP using typical price * volume."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    if session_reset:
        day = df.index.normalize()
        grp_pv = pv.groupby(day).cumsum()
        grp_v = df["volume"].groupby(day).cumsum()
    else:
        grp_pv = pv.cumsum()
        grp_v = df["volume"].cumsum()
    return grp_pv / grp_v.replace(0, np.nan)


def vwap_bands(df: pd.DataFrame, n_std: float = 1.0) -> pd.DataFrame:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"].replace(0, np.nan)
    vw = vwap(df)
    day = df.index.normalize()
    dev = (tp - vw) ** 2
    var = (dev * v).groupby(day).cumsum() / df["volume"].groupby(day).cumsum()
    sd = np.sqrt(var)
    return pd.DataFrame({"vwap": vw, "upper": vw + n_std * sd, "lower": vw - n_std * sd})


def rvol(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Relative volume vs the same time-of-day baseline (intraday)."""
    vol = df["volume"]
    if isinstance(df.index, pd.DatetimeIndex):
        # cumulative volume so far today vs average cumulative by bar-of-day
        day = df.index.normalize()
        minute = df.index.hour * 60 + df.index.minute
        cum = vol.groupby(day).cumsum()
        tod = pd.Series(minute, index=df.index)
        base = cum.groupby(tod).expanding(min_periods=1).mean()
        base = base.droplevel(0).reindex(df.index)
        return (cum / base.replace(0, np.nan)).clip(0, 20)
    return (vol / vol.rolling(window).mean().replace(0, np.nan)).clip(0, 20)


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std()
    return pd.DataFrame({"mid": mid, "upper": mid + n_std * sd, "lower": mid - n_std * sd})


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def volume_profile(df: pd.DataFrame, bins: int = 24) -> dict:
    """Approximate volume-at-price. Returns POC and value area (70%)."""
    if df.empty:
        return {"poc": None, "vah": None, "val": None, "hist": []}
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return {"poc": None, "vah": None, "val": None, "hist": []}
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    tp = (df["high"] + df["low"] + df["close"]) / 3
    idx = np.clip(np.digitize(tp.to_numpy(), edges) - 1, 0, bins - 1)
    hist = np.zeros(bins)
    np.add.at(hist, idx, df["volume"].to_numpy(dtype=float))
    poc_i = int(np.argmax(hist))
    total = hist.sum()
    # expand around POC to cover 70%
    sel = {poc_i}
    acc = hist[poc_i]
    lo_i = hi_i = poc_i
    while acc < 0.7 * total and (lo_i > 0 or hi_i < bins - 1):
        left = hist[lo_i - 1] if lo_i > 0 else -1
        right = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1
            acc += hist[hi_i]
        else:
            lo_i -= 1
            acc += hist[lo_i]
    return {
        "poc": float(centers[poc_i]),
        "vah": float(edges[hi_i + 1]),
        "val": float(edges[lo_i]),
        "hist": [{"price": float(centers[i]), "volume": float(hist[i])} for i in range(bins)],
    }


def swing_levels(df: pd.DataFrame, lookback: int = 5) -> dict:
    """Recent swing highs/lows -> liquidate-prone liquidity pools."""
    highs, lows = [], []
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    for i in range(lookback, len(df) - lookback):
        if h[i] == max(h[i - lookback : i + lookback + 1]):
            highs.append(float(h[i]))
        if l[i] == min(l[i - lookback : i + lookback + 1]):
            lows.append(float(l[i]))
    return {
        "swing_highs": highs[-5:],
        "swing_lows": lows[-5:],
    }


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the full context feature set to an OHLCV dataframe."""
    if df.empty:
        return df
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)
    out["sma200"] = sma(out["close"], 200)
    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out, 14)
    out["atr_pct"] = out["atr"] / out["close"]
    out["rvol"] = rvol(out)
    out["parkinson"] = parkinson_vol(out)
    out["adx"] = adx(out)
    vwb = vwap_bands(out, 1.0)
    out["vwap"] = vwb["vwap"]
    out["vwap_up"] = vwb["upper"]
    out["vwap_dn"] = vwb["lower"]
    bb = bollinger(out["close"], 20, 2.0)
    out["bb_up"] = bb["upper"]
    out["bb_dn"] = bb["lower"]
    out["bb_mid"] = bb["mid"]
    md = macd(out["close"])
    out["macd"] = md["macd"]
    out["macd_hist"] = md["hist"]
    return out
