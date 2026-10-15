"""Risk & capital management - the survival layer.

Nothing else matters if this is wrong. Implements:
  - fractional Kelly position sizing (capped)
  - ATR-based stop / target with R-multiples
  - expectancy / profit-factor math
  - portfolio-level guard rails (max positions, exposure, daily loss kill-switch)
"""
from __future__ import annotations

from dataclasses import dataclass


def kelly_fraction(win_prob: float, win_loss_ratio: float, cap: float = 0.25) -> float:
    """f* = p - (1-p)/b  then scaled down (fractional Kelly) and floored at 0."""
    if win_loss_ratio <= 0:
        return 0.0
    f = win_prob - (1 - win_prob) / win_loss_ratio
    return float(max(0.0, min(cap, f)))


def expectancy(win_prob: float, avg_win: float, avg_loss: float) -> float:
    """E = p*W - (1-p)*L  (avg_loss given as positive number)."""
    return float(win_prob * avg_win - (1 - win_prob) * avg_loss)


def profit_factor(wins_sum: float, losses_sum: float) -> float:
    if losses_sum <= 0:
        return float("inf") if wins_sum > 0 else 0.0
    return float(wins_sum / losses_sum)


def position_size(
    equity: float,
    price: float,
    stop_price: float,
    risk_pct: float = 0.01,
    kelly_f: float | None = None,
    max_position_pct: float = 0.20,
    kelly_ref: float = 0.25,
    min_frac: float = 0.25,
) -> dict:
    """Risk-based sizing. Risk-per-share defines quantity; Kelly scales the bet."""
    risk_per_share = abs(price - stop_price)
    if risk_per_share <= 0 or price <= 0 or equity <= 0:
        return {"qty": 0, "risk_per_share": risk_per_share, "risk_dollars": 0.0, "notional": 0.0}
    risk_dollars = equity * risk_pct
    qty = int(min(risk_dollars // risk_per_share, (equity * max_position_pct) // price))
    if kelly_f is not None:
        # Kelly *scales* the bet between probes size and full size - it must
        # never silently reduce a valid setup to zero shares. A small or
        # negative recent-edge sample means "trade small while you rebuild the
        # edge", not "stop trading forever" (that bug idled the desk all day).
        # The psychology layer (cooldown / halt) is what stands the desk down.
        scale = kelly_f / kelly_ref if kelly_ref else 1.0
        scale = max(min_frac, min(1.0, scale))
        qty = int(qty * scale)
    return {
        "qty": max(0, qty),
        "risk_per_share": risk_per_share,
        "risk_dollars": round(max(0, qty) * risk_per_share, 2),
        "notional": round(max(0, qty) * price, 2),
    }


@dataclass
class RiskLimits:
    risk_per_trade: float = 0.01
    max_position_pct: float = 0.20
    # Trade a *portfolio*, not one idea: hold more names so a single stop can't
    # dominate the day and so the law of large numbers can actually work.
    max_open_positions: int = 12
    # Never become a one-way index bet: cap how many names may be held on the
    # same side so a single macro move can't stop out the whole book at once.
    max_positions_per_side: int = 6
    max_gross_exposure_pct: float = 1.0
    daily_loss_limit_pct: float = 0.03
    max_trades_per_day: int = 40
    min_confidence: float = 0.50
    rr: float = 2.0
    # Wider structural stop (structure + >=1xATR floor). The tighter the stop the
    # more often ordinary noise tags a correct trade; we size down instead.
    # atr_mult is only the fallback when no swing is available; the swing buffer
    # and the min/max stop band do most of the work.
    atr_mult: float = 3.0
    # volatility dampener ("humility"): shrink size as ATR% runs hot, hard-stop if extreme
    atr_pct_hot: float = 2.5
    atr_pct_extreme: float = 4.5
    vol_dampen: float = 0.5
    # trailing stop: give the runner room (let winners run), engage later
    trail_mult: float = 3.0
    trail_after_r: float = 1.5


# Risk profiles: scale every guard rail at once. "conservative" is the
# capital-preservation preset (smallest bets, tightest daily kill-switch).
PROFILES: dict[str, dict] = {
    "conservative": {
        "label": "Capital-preservation",
        "desc": "Smallest bets, tightest daily kill-switch, only the cleanest setups. Fewest names.",
        "limits": dict(risk_per_trade=0.0075, max_position_pct=0.15, max_open_positions=8,
                       max_positions_per_side=4, max_gross_exposure_pct=0.8, daily_loss_limit_pct=0.02,
                       max_trades_per_day=25, min_confidence=0.58, rr=2.2, atr_mult=3.0,
                       atr_pct_hot=2.5, atr_pct_extreme=4.5, vol_dampen=0.5,
                       trail_mult=3.0, trail_after_r=2.0),
    },
    "balanced": {
        "label": "Balanced",
        "desc": "The default preset: a real portfolio of positions, structural stops, "
                "patience to let winners run, and a hard daily kill-switch.",
        "limits": dict(RiskLimits().__dict__),
    },
    "aggressive": {
        "label": "Aggressive",
        "desc": "More names, bigger bets and looser filters to chase more trades. Drawdowns will be deeper.",
        "limits": dict(risk_per_trade=0.015, max_position_pct=0.25, max_open_positions=16,
                       max_positions_per_side=8, max_gross_exposure_pct=1.50, daily_loss_limit_pct=0.05,
                       max_trades_per_day=60, min_confidence=0.45, rr=2.0, atr_mult=3.0,
                       atr_pct_hot=3.0, atr_pct_extreme=5.0, vol_dampen=0.6,
                       trail_mult=3.0, trail_after_r=1.5),
    },
}

DEFAULT_PROFILE = "balanced"


def profile_limits(profile: str | None) -> RiskLimits:
    """Return a RiskLimits preset by name (falls back to balanced)."""
    p = PROFILES.get((profile or "").lower(), PROFILES[DEFAULT_PROFILE])
    return RiskLimits(**p["limits"])


def profile_summary() -> list[dict]:
    return [{"name": k, "label": v["label"], "desc": v["desc"], "limits": v["limits"]}
            for k, v in PROFILES.items()]


@dataclass
class PortfolioState:
    equity: float
    cash: float
    day_pnl: float
    open_positions: int
    gross_exposure: float
    trades_today: int

def check_portfolio(state: PortfolioState, limits: RiskLimits) -> tuple[bool, list[str]]:
    """Returns (allowed, reasons_if_blocked)."""
    blocks: list[str] = []
    if state.open_positions >= limits.max_open_positions:
        blocks.append(f"max open positions ({limits.max_open_positions}) reached")
    if state.equity > 0:
        day_ret = state.day_pnl / state.equity
        if day_ret <= -limits.daily_loss_limit_pct:
            blocks.append(f"daily loss limit hit ({day_ret:.1%}) - trading halted for the day")
        if state.gross_exposure / max(state.equity, 1e-9) >= limits.max_gross_exposure_pct:
            blocks.append("max gross exposure reached")
    if state.trades_today >= limits.max_trades_per_day:
        blocks.append(f"max trades/day ({limits.max_trades_per_day}) reached")
    return (len(blocks) == 0, blocks)


def atr_stops(price: float, atr_val: float, direction: int, rr: float = 2.0, atr_mult: float = 1.5) -> dict:
    """Stop at atr_mult*ATR away; target at rr * risk."""
    risk = atr_mult * atr_val
    if direction >= 0:
        stop = price - risk
        target = price + rr * risk
    else:
        stop = price + risk
        target = price - rr * risk
    return {"stop": round(stop, 4), "target": round(target, 4), "risk": round(risk, 4)}


def structural_stops(price: float, atr_val: float, direction: int, rr: float = 2.0,
                     atr_mult: float = 3.0, min_stop_pct: float = 0.02,
                     max_stop_pct: float = 0.08, swing: float | None = None,
                     buffer_atr: float = 0.75, atr_floor_mult: float = 2.0) -> dict:
    """Stop/target placed where the trade is *wrong*, not at a blind ATR distance.

    - If `swing` (recent swing low for longs / swing high for shorts) is given,
      the stop sits just beyond it (buffer_atr * ATR) - set where the setup is
      invalidated, like a person would.
    - A noise floor of `atr_floor_mult * ATR` guarantees the stop is never inside
      the one-ATR noise envelope that tags correct trades (structure decides the
      level, volatility decides the minimum distance).
    - Distance is clamped to [min_stop_pct, max_stop_pct] of price so it is never
      inside the noise band and never catastrophically wide.
    - Target stays at rr * distance so reward:risk is preserved.
    """
    if direction == 0:
        return {"stop": round(price, 4), "target": round(price, 4), "risk": 0.0,
                "basis": "flat"}
    floor = price * min_stop_pct
    cap = price * max_stop_pct
    atr_floor = atr_floor_mult * atr_val
    if swing is not None and swing > 0:
        if direction > 0:
            structural = price - (swing - buffer_atr * atr_val)
        else:
            structural = (swing + buffer_atr * atr_val) - price
        dist = max(structural, atr_floor, floor)
        basis = "swing"
    else:
        dist = max(atr_mult * atr_val, atr_floor, floor)
        basis = "atr"
    dist = min(dist, cap)
    if direction > 0:
        stop, target = price - dist, price + rr * dist
    else:
        stop, target = price + dist, price - rr * dist
    return {"stop": round(stop, 4), "target": round(target, 4), "risk": round(dist, 4),
            "basis": basis}
