"""Adverse-selection / toxic-flow defence.

High VPIN with delta divergence means informed flow is on the other side and
liquidity providers are pulling - the classic moment a retail entry gets
adversely selected. Crucially, one-sided flow is only *adverse* when it opposes
the trade we are about to take: riding informed buying is fine, buying into
informed selling is not. This layer is therefore direction-aware and decides how
much to trust an entry:

  * CLEAR     - normal/agreeing flow, full size, no extra confidence needed
  * ELEVATED  - informed flow against us: shrink size and demand more conviction
  * TOXIC     - heavy informed flow against us / absorption: stand down (optional)

It is deliberately conservative: it never creates trades, only removes/right-sizes
them. Wiring is in strategy.analyze (attach to ctx) and strategy.size_decision
(apply the size multiplier alongside the volatility dampener).
"""
from __future__ import annotations

from .config import settings


def assess(micro: dict | None, direction: int = 0) -> dict:
    if not settings.toxic_enabled or not micro:
        return {"level": "OFF", "vpin": 0.0, "size_mult": 1.0,
                "require_conf": 0.0, "block": False, "reason": "toxic-flow defence off"}

    vpin = float(micro.get("toxicity", 0.0) or 0.0)
    imbalance = float(micro.get("imbalance", 0.0) or 0.0)
    divergence = float(micro.get("divergence", 0.0) or 0.0)

    # only one-sided flow AGAINST our direction is adverse; divergence (absorption)
    # is a strong adverse tell regardless of side.
    against = direction != 0 and imbalance * direction < 0
    factor = 1.0 if against else 0.35
    adjusted = min(1.0, vpin * factor + 0.4 * abs(divergence))

    # Fail-safe: a *saturated* VPIN means one side has absorbed the whole book -
    # the classic adverse-selection tape. Even if the raw flow looks like it is
    # "with us", never let it collapse to CLEAR; hold it at ELEVATED (shrink size,
    # demand more conviction). This is the guard that stops a mis-computed VPIN
    # from green-lighting full-size entries into one-sided flow.
    saturated = vpin >= max(0.9, settings.toxic_vpin_extreme)
    if saturated:
        adjusted = max(adjusted, settings.toxic_vpin_high + 0.01)

    if adjusted >= settings.toxic_vpin_extreme:
        level, size_mult, require_conf = "TOXIC", 0.0, settings.toxic_conf_penalty * 2
    elif adjusted >= settings.toxic_vpin_high:
        level, size_mult, require_conf = "ELEVATED", settings.toxic_size_dampen, settings.toxic_conf_penalty
    else:
        level, size_mult, require_conf = "CLEAR", 1.0, 0.0

    block = level == "TOXIC" and settings.toxic_block
    tokens = [f"VPIN {vpin:.2f}"]
    if against:
        tokens.append("flow against us")
    if divergence:
        tokens.append(f"delta divergence {divergence:+.0f}")
    return {
        "level": level,
        "vpin": round(vpin, 3),
        "against": bool(against),
        "size_mult": round(size_mult, 3),
        "require_conf": round(require_conf, 3),
        "block": block,
        "reason": f"flow {level}: " + ", ".join(tokens),
    }

