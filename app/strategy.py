"""Strategy: fuses features + regime + order-flow + volume-profile + news into a
single explainable decision per symbol.
"""
from __future__ import annotations

import numpy as np

from . import alpha, cross_asset, indicators, microstructure, mtf, regime as regime_mod, risk, rl, signals, toxic
from .config import settings


def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if (f != f) else f
    except Exception:
        return default


def analyze(symbol: str, df, news_sentiment: float = 0.0, llm_brief: dict | None = None,
            params: dict | None = None, feat=None, htf: dict | None = None,
            market: dict | None = None) -> dict:
    """Return a full context/decision dict for one symbol (no sizing yet).

    `feat` lets callers pass a precomputed feature frame (indicators are causal),
    which makes backtests/optimization far cheaper than recomputing per bar.
    `htf` is an optional higher-timeframe dict (mtf.trend_of + mtf.breakout) used
    to confirm / penalise (and optionally trigger) the decision. `market` is an
    optional cross-asset/breadth bias (cross_asset.assess).
    """
    params = params or {}
    rr = float(params.get("rr", 2.0))
    atr_mult = float(params.get("atr_mult", 3.0))
    regime_method = params.get("regime_method", settings.regime_method)
    if df is None or len(df) < 30:
        return {"symbol": symbol, "action": "HOLD", "confidence": 0.0, "reasons": ["insufficient data"],
                "regime": "RANGE", "signals": [], "features": {}, "price": 0.0,
                "mtf": {"trend": 0, "label": "OFF"}, "mtf_mult": 1.0, "mtf_blocked": False,
                "market": {"bias": 0.0, "label": "OFF"},
                "toxicity": {"level": "OFF", "size_mult": 1.0, "require_conf": 0.0, "block": False}}

    feat = feat if feat is not None else indicators.compute_features(df)
    reg = regime_mod.classify(feat, method=regime_method, symbol=symbol)
    book = regime_mod.playbook(reg["regime"])
    micro = microstructure.order_flow(feat)
    pools = microstructure.liquidity_pools(feat)
    vprof = indicators.volume_profile(feat.tail(120))

    htf = htf or {}
    htf_trend = int(htf.get("trend", 0) or 0)
    sigs = signals.generate(feat, reg["regime"], micro, pools, vprof, news_sentiment,
                            htf_trend=htf_trend)

    # --- HTF breakout as an explicit multi-timeframe entry trigger ---
    htf_breakout = int(htf.get("breakout", 0))
    if htf_breakout != 0:
        sigs.append({
            "name": "htf_breakout",
            "dir": htf_breakout,
            "weight": 0.7,
            "reason": (htf or {}).get("breakout_reason")
            or f"HTF breakout {'up' if htf_breakout > 0 else 'down'}",
        })

    # --- alpha decay: down-weight signals whose recent edge has faded ---
    if settings.alpha_decay_enabled:
        edge_w = alpha.get_alpha_tracker().edge_weights()
        for s in sigs:
            m = edge_w.get(s["name"])
            if m is not None:
                s["weight"] = round(s["weight"] * m, 4)
                s["edge_mult"] = m

    # --- RL: regime-contextual bandit re-weights signals by conditional edge ---
    if settings.rl_enabled:
        rl_w = rl.get_policy_learner().contextual_weights(reg["regime"])
        for s in sigs:
            m = rl_w.get(s["name"])
            if m is not None:
                s["weight"] = round(s["weight"] * m, 4)
                s["rl_mult"] = m

    last = feat.iloc[-1]
    price = float(last["close"])

    num = sum(s["dir"] * s["weight"] for s in sigs if s["dir"] != 0)
    den = sum(s["weight"] for s in sigs if s["dir"] != 0) or 1.0
    net = num / den if den else 0.0

    # regime bias & LLM narrative modulation
    llm_bias = 0.0
    llm_text = ""
    if llm_brief:
        llm_bias = _safe(llm_brief.get("bias"))
        llm_text = llm_brief.get("brief", "")

    # cross-asset / breadth leading context
    market = market or {"bias": 0.0, "label": "OFF"}
    market_bias = _safe(market.get("bias"))

    base = net * book["size_mult"] + 0.25 * llm_bias
    if settings.cross_asset_enabled and market.get("label") not in (None, "OFF"):
        base += settings.cross_asset_weight * market_bias
    base_dir = 1 if base > 0 else (-1 if base < 0 else 0)

    # --- multi-timeframe confirmation gate ---
    mtf_info = htf if htf is not None else {"trend": 0, "label": "OFF", "strength": 0.0}
    mtf_mult = 1.0
    mtf_blocked = False
    if settings.mtf_enabled and htf is not None and base_dir != 0 and mtf_info.get("trend", 0) != 0:
        mtf_mult = mtf.confirm(base_dir, mtf_info["trend"])
        if (mtf_mult < 1.0 and settings.mtf_block_on_conflict
                and mtf_info.get("strength", 0.0) >= 0.5):
            mtf_blocked = True

    # Anti-chase: buying far above VWAP / selling far below is how most
    # round-trips happen. Penalise an extended entry so we wait for better price.
    chase = 1.0
    vwap = _safe(last["vwap"])
    extend_pct = 0.0
    if base_dir != 0 and vwap:
        extend_pct = (price - vwap) / vwap
        ideal = 1 if base_dir > 0 else -1
        if extend_pct * ideal > float(params.get("extend_penalty_pct", 0.008)):
            chase = float(params.get("chase_penalty", 0.55))

    composite = 0.0 if mtf_blocked else base * mtf_mult * chase
    confidence = float(min(0.99, abs(composite)))
    direction = 1 if composite > 0 else (-1 if composite < 0 else 0)
    action = "BUY" if direction > 0 else ("SELL" if direction < 0 else "HOLD")

    gates: list[str] = []

    # --- anti-fade: never trade against the higher-timeframe trend. Fading a
    # trend (buying a dip in a down-trend / shorting a rip in an up-trend) is the
    # single most expensive habit; when the HTF disagrees, stand down. ---
    htf_veto = (settings.antifade_enabled and direction != 0
                and htf_trend != 0 and direction * htf_trend < 0)
    if htf_veto:
        gates.append(f"anti-fade veto: would trade against HTF {mtf_info.get('label')} trend")
        action, direction, confidence = "HOLD", 0, 0.0

    # --- confluence: require >= min_confluence independent signals to agree.
    # A single weak signal is a coin flip; two agreeing signals is a setup. ---
    aligned = [s for s in sigs if s["dir"] == direction and s.get("weight", 0) > 0]
    if direction != 0 and len(aligned) < max(1, settings.min_confluence):
        gates.append(f"confluence {len(aligned)} < {settings.min_confluence} (single-signal entry)")
        action, direction, confidence = "HOLD", 0, 0.0

    # --- adverse-selection / toxic-flow defence (direction-aware) ---
    toxicity = toxic.assess(micro, direction)
    if toxicity.get("block") and direction != 0:
        action, direction, confidence = "HOLD", 0, 0.0

    reasons = [f"Regime: {reg['regime']} ({book['style']})"]
    reasons += [s["reason"] for s in sigs]
    reasons += gates
    if settings.mtf_enabled and htf is not None and not mtf_blocked and mtf_info.get("trend", 0) != 0:
        tag = "aligned" if mtf_mult >= 1.0 else "conflict"
        reasons.append(f"MTF {mtf_info.get('label')}: {tag} (x{mtf_mult:.2f})")
    if mtf_blocked:
        reasons.append(f"MTF veto: primary signal fights HTF {mtf_info.get('label')} trend")
    if settings.cross_asset_enabled and market.get("label") not in (None, "OFF") and abs(market_bias) >= 0.05:
        reasons.append(f"Market {market.get('label')} (bias {market_bias:+.2f})")
    if toxicity["level"] in ("ELEVATED", "TOXIC"):
        reasons.append(toxicity["reason"])
    if chase < 1.0:
        reasons.append(f"Extended {(extend_pct * 100):+.1f}% vs VWAP - scaled (x{chase})")
    if llm_text:
        reasons.append(f"Analyst: {llm_text}")

    atr_val = _safe(last["atr"], price * 0.01) or price * 0.01
    # Stop sits beyond the recent swing (where the trade is invalidated), with a
    # noise floor so ordinary wiggle can't tag a correct trade, clamped to a
    # floor/cap of price. Risk-based sizing then keeps $ risk constant as the
    # stop widens - we size down instead of getting shaken out.
    min_stop_pct = float(params.get("min_stop_pct", 0.02))
    max_stop_pct = float(params.get("max_stop_pct", 0.08))
    stop_lookback = int(params.get("stop_lookback", 10))
    buffer_atr = float(params.get("stop_buffer_atr", 0.75))
    atr_floor_mult = float(params.get("stop_atr_floor", 2.0))
    swing = None
    try:
        if direction > 0:
            swing = float(df["low"].tail(stop_lookback).min())
        elif direction < 0:
            swing = float(df["high"].tail(stop_lookback).max())
    except Exception:  # noqa: BLE001
        swing = None
    stops = risk.structural_stops(price, atr_val, direction, rr=rr, atr_mult=atr_mult,
                                  min_stop_pct=min_stop_pct, max_stop_pct=max_stop_pct,
                                  swing=swing, buffer_atr=buffer_atr,
                                  atr_floor_mult=atr_floor_mult)

    return {
        "symbol": symbol,
        "action": action,
        "direction": direction,
        "confidence": round(confidence, 3),
        "price": round(price, 4),
        "entry": round(price, 4),
        "stop": stops["stop"],
        "target": stops["target"],
        "rr": rr,
        "stop_basis": stops.get("basis", "atr"),
        "atr_mult": atr_mult,
        "atr_raw": round(atr_val, 6),
        "regime": reg["regime"],
        "regime_detail": reg,
        "playbook": book,
        "signals": sigs,
        "mtf": mtf_info,
        "mtf_mult": round(mtf_mult, 3),
        "mtf_blocked": mtf_blocked,
        "market": market,
        "market_bias": round(market_bias, 3),
        "toxicity": toxicity,
        "micro": micro,
        "pools": pools,
        "volume_profile": vprof,
        "news_sentiment": round(float(news_sentiment), 3),
        "llm": {"bias": llm_bias, "brief": llm_text} if llm_brief else {},
        "features": {
            "rsi": round(_safe(last["rsi"], 50), 1),
            "adx": round(_safe(last["adx"]), 1),
            "rvol": round(_safe(last["rvol"], 1), 2),
            "atr": round(atr_val, 4),
            "atr_pct": round(_safe(last["atr_pct"]) * 100, 2),
            "vwap": round(_safe(last["vwap"]), 4),
            "vwap_upper": round(_safe(last["vwap_up"]), 4),
            "vwap_lower": round(_safe(last["vwap_dn"]), 4),
            "ema9": round(_safe(last["ema9"]), 4),
            "ema21": round(_safe(last["ema21"]), 4),
            "ema50": round(_safe(last["ema50"]), 4),
            "bb_up": round(_safe(last["bb_up"]), 4),
            "bb_dn": round(_safe(last["bb_dn"]), 4),
            "vpin": round(_safe(micro.get("toxicity")), 3),
            "delta_imbalance": round(_safe(micro.get("imbalance")) * 100, 1),
        },
        "reasons": reasons,
    }


def size_decision(ctx: dict, equity: float, limits: risk.RiskLimits,
                  win_prob: float = 0.5, win_loss_ratio: float = 2.0) -> dict:
    """Attach a risk-based position size using fractional Kelly + fixed-fraction risk."""
    if ctx.get("action") not in ("BUY", "SELL") or ctx.get("price", 0) <= 0:
        ctx["sizing"] = {"qty": 0}
        return ctx
    kelly = risk.kelly_fraction(win_prob, win_loss_ratio, cap=0.25)
    s = risk.position_size(
        equity=equity,
        price=ctx["price"],
        stop_price=ctx["stop"],
        risk_pct=limits.risk_per_trade,
        kelly_f=kelly,
        max_position_pct=limits.max_position_pct,
    )
    atr_pct = _safe((ctx.get("features") or {}).get("atr_pct"))
    if atr_pct >= limits.atr_pct_extreme:
        vol_factor = 0.0
    elif atr_pct >= limits.atr_pct_hot:
        vol_factor = limits.vol_dampen
    else:
        vol_factor = 1.0
    tox_factor = _safe((ctx.get("toxicity") or {}).get("size_mult"), 1.0)
    dampen = vol_factor * tox_factor
    if dampen < 1.0:
        s["qty"] = int(s.get("qty", 0) * dampen)
        s["risk_dollars"] = round(s["qty"] * s["risk_per_share"], 2)
        s["notional"] = round(s["qty"] * ctx["price"], 2)
    s["vol_dampen"] = round(vol_factor, 2)
    s["tox_dampen"] = round(tox_factor, 2)
    s["dampen"] = round(dampen, 3)
    s["atr_pct"] = atr_pct
    s["kelly"] = round(kelly, 3)
    s["win_prob"] = win_prob
    s["win_loss_ratio"] = win_loss_ratio
    ctx["sizing"] = s
    return ctx
