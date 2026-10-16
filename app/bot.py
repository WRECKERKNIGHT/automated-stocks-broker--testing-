"""The autonomous trading bot: scan -> decide -> size -> execute -> manage -> journal."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from . import alerts as alerts_mod
from . import cross_asset, elite, indicators, mtf, storage, strategy
from . import universe as universe_mod
from .alpha import get_alpha_tracker
from .rl import get_policy_learner
from .analyst import Analyst, lexicon_sentiment
from .alpaca import Broker
from .config import settings
from .notify import get_notifier
from .psyche import TraderMind
from .risk import RiskLimits, PortfolioState, check_portfolio, profile_limits, DEFAULT_PROFILE
from .tape import TapeFeed

ET = ZoneInfo("America/New_York")
TIMEFRAME = "5Min"
BARS = 260
MAX_HOLD_MIN = 360  # ~ 6h hard time cap; a runner is never cut early (see exits)
STOP_GRACE_MIN = 20        # no structural stop-outs in the first N minutes
DISASTER_PCT = 0.02        # hard backstop: never risk more than this % of price
REVENGE_COOLDOWN_MIN = 45  # don't touch a name that just stopped us


class TradingBot:
    def __init__(self, broker: Broker, analyst: Analyst,
                 on_update: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.broker = broker
        self.analyst = analyst
        self.on_update = on_update
        self.universe = list(settings.watchlist)
        self.risk_profile = storage.get_setting("risk_profile", settings.risk_profile) or DEFAULT_PROFILE
        self.limits = profile_limits(self.risk_profile)
        self.stop_grace_min = settings.stop_grace_min
        self.disaster_pct = settings.disaster_stop_pct
        self.stop_grace_mult = settings.stop_grace_mult
        self.max_hold_min = max(60, int(settings.max_hold_min)) if hasattr(settings, "max_hold_min") else MAX_HOLD_MIN
        self.time_stop_enabled = bool(getattr(settings, "time_stop_enabled", False))
        self.breakeven_r = float(getattr(settings, "breakeven_r", 1.5))
        self.scale_out_r = float(getattr(settings, "scale_out_r", 0.0))
        self.scale_out_frac = float(getattr(settings, "scale_out_frac", 0.25))
        self.flatten_at_eod = bool(getattr(settings, "flatten_at_eod", True))
        self.max_open_heat_pct = float(getattr(settings, "max_open_heat_pct", 0.06))
        self.revenge_cooldown = settings.revenge_cooldown_min
        self.symbol_cooldown: dict[str, float] = {}
        self.scan_interval = settings.scan_interval
        self.running = False
        self._task: asyncio.Task | None = None
        try:
            self.positions: dict[str, dict] = storage.load_positions_meta()
        except Exception:  # noqa: BLE001
            self.positions = {}
        self.day = self._et_date()
        self.day_start_equity: float | None = None
        self.trades_today = 0
        self.sentiment: dict[str, float] = {}
        self.news: list[dict] = []
        self._news_ts = 0.0
        self.log: deque[dict] = deque(maxlen=400)
        self.last_scan = 0.0
        self.market_open = False
        self.clock: dict = {}
        self.errors = 0
        self.mind = TraderMind()
        self.notifier = get_notifier()
        self.alpha = get_alpha_tracker()
        self.policy = get_policy_learner()
        self.market: dict = {"bias": 0.0, "label": "OFF"}
        self.flatten_on_stop = settings.flatten_on_stop
        self._last_halt = ""
        self.alerts_fired: deque[dict] = deque(maxlen=50)
        self.tape = TapeFeed(broker, self.universe, on_update=on_update)

    # ------------------------------------------------------------------
    def _et_date(self) -> str:
        return datetime.now(ET).strftime("%Y-%m-%d")

    def _log(self, level: str, msg: str) -> None:
        self.log.appendleft({"ts": time.time(), "level": level, "msg": msg})

    def _persist_positions(self) -> None:
        """Save live stops / thesis to SQLite so a restart does not lose them.

        Without this, positions are re-adopted after a restart with a synthetic
        stop (entry - 1.5*ATR), which can cut a working trade at a random level.
        """
        try:
            storage.save_positions_meta(self.positions)
        except Exception:  # noqa: BLE001
            pass

    def _notify(self, text: str, level: str = "info") -> None:
        if not self.notifier.enabled:
            return
        try:
            asyncio.create_task(self.notifier.send(text, level))
        except Exception:  # noqa: BLE001
            pass

    def set_universe(self, symbols: list[str]) -> None:
        self.universe = [s.upper() for s in symbols if s and s.strip()]
        self.tape.update_symbols(self.universe)

    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        await self.tape.start()
        self._log("info", "Bot started")

    async def stop(self) -> None:
        self.running = False
        await self.tape.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self.flatten_on_stop:
            await self._flatten_all()
        await self.notifier.close()
        self._log("info", "Bot stopped")

    async def _flatten_all(self) -> None:
        """Failsafe: flatten every open position (used on shutdown)."""
        try:
            positions = await self.broker.get_positions()
        except Exception as e:  # noqa: BLE001
            self._log("warn", f"flatten: cannot list positions: {e}")
            return
        for p in positions:
            price = p.get("current_price") or await self.broker.get_latest_price(p["symbol"])
            try:
                await self._close_position(p["symbol"], p, price, "flatten")
            except Exception as e:  # noqa: BLE001
                self._log("warn", f"flatten failed {p.get('symbol')}: {e}")
        self._notify("Bot stopped - all positions flattened", "warn")

    async def _loop(self) -> None:
        while self.running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                self._log("error", f"scan error: {e}")
                if self.errors <= 3 or self.errors % 10 == 0:
                    self._notify(f"scan error #{self.errors}: {e}", "error")
            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------
    async def scan_once(self) -> dict:
        today = self._et_date()
        new_day = today != self.day
        if new_day:
            self._log("info", f"New session {today} - resetting daily counters")
            self.day = today
            self.trades_today = 0
            self.day_start_equity = None

        clock = await self.broker.get_clock()
        self.clock = clock or {}
        self.market_open = bool(clock.get("is_open"))
        account = await self.broker.get_account()
        if self.day_start_equity is None:
            self.day_start_equity = account["equity"]
        if new_day:
            self.mind.start_session(account["equity"])
        self.mind.observe_equity(account["equity"])
        if self.mind.halted and self.mind.halt_reason != self._last_halt:
            self._last_halt = self.mind.halt_reason
            self._log("warn", f"MIND HALT: {self.mind.halt_reason}")
            self._notify(f"Risk halt engaged - {self.mind.halt_reason}", "error")

        positions = await self.broker.get_positions()
        pos_syms = {p["symbol"] for p in positions}

        # drop persisted metadata for positions that no longer exist (closed
        # externally / filled stop) so a stale entry can't block re-entry.
        stale = [s for s in self.positions if s not in pos_syms]
        for s in stale:
            self.positions.pop(s, None)
        if stale:
            self._persist_positions()

        storage.log_equity({
            "equity": account["equity"], "cash": account["cash"],
            "buying_power": account["buying_power"],
            "positions_value": account["equity"] - account["cash"],
            "day_pnl": account["day_pnl"],
        })

        if self.market_open:
            await self._refresh_news()
            await self._check_alerts()
            await self._manage_exits(positions)
            positions = await self.broker.get_positions()
            pos_syms = {p["symbol"] for p in positions}
            await self._consider_entries(account, pos_syms)

        self._finalize_daily(account)

        snap = await self.build_snapshot()
        self.last_scan = time.time()
        if self.on_update:
            await self.on_update({"type": "snapshot", "data": snap})
        return snap

    # ------------------------------------------------------------------
    async def _refresh_news(self) -> None:
        if time.time() - self._news_ts < 150:
            return
        try:
            raw = await self.broker.get_news(self.universe, limit=30)
            scored = await self.analyst.score_news(raw)
            self.news = scored
            storage.cache_news([
                {k: v for k, v in n.items() if k in
                 ("ts", "symbol", "headline", "source", "url", "sentiment", "summary")}
                for n in scored
            ])
            agg: dict[str, list[float]] = {}
            for n in scored:
                for s in (n.get("symbols") or ([n["symbol"]] if n.get("symbol") else [])):
                    agg.setdefault(s, []).append(float(n.get("sentiment", 0)))
            self.sentiment = {s: sum(v) / len(v) for s, v in agg.items()}
            self._news_ts = time.time()
        except Exception as e:  # noqa: BLE001
            self._log("warn", f"news refresh failed: {e}")

    def _headlines_for(self, symbol: str, n: int = 6) -> list[str]:
        out = []
        for it in self.news:
            syms = it.get("symbols") or []
            if symbol in syms or it.get("symbol") == symbol:
                out.append(it.get("headline", ""))
            if len(out) >= n:
                break
        if not out:
            out = [it.get("headline", "") for it in self.news[:n]]
        return out

    def _recent_edge(self) -> tuple[float, float]:
        """Win-rate and win/loss ratio for sizing, shrunk toward a neutral prior.

        A handful of trades is statistically meaningless, so raw numbers from a
        tiny (often noisy, losing) sample must not drive the bet sizing. We blend
        the observed stats with a neutral prior (45% win rate, 1.5:1 payoff)
        using a fixed pseudo-count, so the edge only takes over once enough
        trades have accumulated. This prevents a 10-trade cold streak from
        producing an absurd Kelly that idles the whole desk.
        """
        trades = [t for t in storage.recent_trades(limit=80) if t.get("pnl") is not None]
        prior_n, prior_wp, prior_wlr = 20.0, 0.45, 1.5
        n = len(trades)
        if n == 0:
            return prior_wp, prior_wlr
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        raw_wp = len(wins) / n
        avg_w = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
        avg_l = -sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
        raw_wlr = (avg_w / avg_l) if avg_l > 0 else prior_wlr
        wp = (raw_wp * n + prior_wp * prior_n) / (n + prior_n)
        wlr = (raw_wlr * n + prior_wlr * prior_n) / (n + prior_n)
        return wp, max(0.1, wlr)

    async def _check_alerts(self) -> None:
        try:
            fired = await alerts_mod.evaluate(self.broker, notify=self._notify)
        except Exception as e:  # noqa: BLE001
            self._log("warn", f"alert check failed: {e}")
            return
        for a in fired:
            self.alerts_fired.appendleft(a)
            self._log("trade", f"ALERT {a['symbol']} {a.get('kind')} {a.get('op')} "
                               f"{a.get('value')} @ {a.get('last_price')}")

    async def _refresh_market(self) -> None:
        """Cross-asset / breadth leading context (index ETFs)."""
        if not settings.cross_asset_enabled:
            self.market = {"bias": 0.0, "label": "OFF"}
            return
        frames: dict = {}
        for sym in settings.cross_asset_symbols:
            try:
                df = await self.broker.get_bars(sym, TIMEFRAME, 120)
                if df is not None and not df.empty:
                    frames[sym] = df
            except Exception as e:  # noqa: BLE001
                self._log("warn", f"cross-asset {sym} failed: {e}")
        self.market = cross_asset.assess(frames) if frames else {"bias": 0.0, "label": "OFF"}

    # ------------------------------------------------------------------
    async def _manage_exits(self, positions: list[dict]) -> None:
        for p in positions:
            sym = p["symbol"]
            meta = self.positions.get(sym)
            price = p.get("current_price") or await self.broker.get_latest_price(sym)
            if not price:
                continue
            direction = 1 if p["qty"] > 0 else -1
            entry = p["avg_entry"]

            if meta is None:
                # adopt a position we don't know about (e.g. restart)
                atr = entry * 0.01
                meta = {"stop": entry - direction * 1.5 * atr,
                        "target": entry + direction * 3.0 * atr,
                        "opened": time.time(), "high_water": price, "reason": "adopted",
                        "kelly": None, "atr": atr, "risk": 1.5 * atr}
                self.positions[sym] = meta
                self._persist_positions()

            meta["high_water"] = max(meta["high_water"], price) if direction > 0 else min(meta["high_water"], price)
            risk0 = meta.get("risk") or abs(entry - meta["stop"]) or (entry * 0.01)
            atr = meta.get("atr") or (entry * 0.01)
            age_min = (time.time() - meta["opened"]) / 60.0
            exit_reason = None

            # --- flexible stop: a hard disaster backstop always applies, but the
            # tighter structural stop is suspended for a grace period so ordinary
            # noise can't tag a fresh trade (a human "give it room" discipline).
            # The disaster distance is a *bounded* multiple of the intended risk,
            # so even the worst-case fill risks ~1.4x the sized amount, not 4x. ---
            disaster = entry - direction * max(entry * self.disaster_pct,
                                               risk0 * self.stop_grace_mult)
            grace = age_min < self.stop_grace_min and (price - entry) * direction < 0.5 * risk0
            eff_stop = disaster if grace else meta["stop"]

            # --- human-style management: no stall exits, no papercut exits, and no
            # forcing a winner out at an arbitrary target. A position lives until its
            # thesis breaks (structural stop / disaster backstop). Only two things the
            # trader *does* proactively: protect a trade that has paid a full R, and
            # bank a third into real strength while letting the runner ride. ---
            r_now = (price - entry) * direction / risk0 if risk0 else 0.0
            hw = meta["high_water"]
            hw_r = (hw - entry) * direction / risk0 if risk0 else 0.0
            be_r = self.breakeven_r

            if (price - eff_stop) * direction <= 0:
                exit_reason = "disaster stop" if grace else "stop out"
            elif not grace:
                stage = meta.get("stage", 0)
                # 1) protect the trade once it has paid us a full R
                if r_now >= be_r:
                    meta["stop"] = (max(meta["stop"], entry) if direction > 0
                                    else min(meta["stop"], entry))
                # 2) optional partial scale - off by default. Patience: let it run.
                if self.scale_out_r > 0 and stage < 1 and r_now >= self.scale_out_r:
                    if await self._scale_out(sym, p, price, self.scale_out_frac,
                                             f"scale +{self.scale_out_r:.1f}R (runner rides)"):
                        stage = 1
                # 3) trail the runner from the high-water mark, never the noise
                if hw_r >= be_r:
                    trail = hw - self._trail_dist(entry, atr, risk0) * direction
                    meta["stop"] = max(meta["stop"], trail) if direction > 0 else min(meta["stop"], trail)
                meta["stage"] = stage

            # EOD flatten: this is an intraday desk - flat before the bell so an
            # overnight gap cannot turn a managed trade into a disaster.
            if not exit_reason and self.flatten_at_eod:
                try:
                    now_et = datetime.now(ET)
                    if now_et.hour == 15 and now_et.minute >= 55:
                        exit_reason = "EOD flatten"
                except Exception:  # noqa: BLE001
                    pass

            # Patience (default): no clock-based exit at all - a position lives
            # until its thesis breaks (structural stop / disaster / EOD flatten).
            # The optional time-stop only reclaims capital from a trade that
            # NEVER worked (high-water mark never reached +0.5R); a trade that
            # made progress and pulled back is a runner being given room.
            if (not exit_reason and self.time_stop_enabled
                    and age_min > self.max_hold_min and r_now < 0.5 and hw_r < 0.5):
                exit_reason = "time stop (never worked - reclaim capital)"

            if exit_reason:
                await self._close_position(sym, p, price, exit_reason)

    async def _close_position(self, sym: str, p: dict, price: float, reason: str) -> None:
        direction = 1 if p["qty"] > 0 else -1
        side = "sell" if direction > 0 else "buy"
        meta = self.positions.get(sym) or {}
        try:
            order = await self.broker.submit_order(symbol=sym, qty=int(abs(p["qty"])), side=side)
        except Exception as e:  # noqa: BLE001
            self._log("error", f"exit order failed {sym}: {e}")
            return
        exit_price = float(order.get("filled_avg_price") or price)
        entry = p["avg_entry"]
        qty = abs(p["qty"])
        pnl = (exit_price - entry) * qty * direction
        pnl_pct = (exit_price / entry - 1) * direction if entry else 0.0
        storage.log_trade({
            "symbol": sym, "side": "long" if direction > 0 else "short", "qty": qty,
            "entry_price": round(entry, 4), "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 4), "reason": reason,
            "tags": ["exit"], "order_id": order.get("id"),
        })
        storage.log_signal_outcomes(sym, meta.get("signals", []), pnl, pnl_pct,
                                    regime=meta.get("regime"))
        self.positions.pop(sym, None)
        self._persist_positions()
        self.trades_today += 1
        # anti-revenge: after a real loss, stay out of that name for a while so we
        # don't immediately re-buy a losing ticker at a worse price (Douglas).
        if pnl < 0 and ("stop" in reason or "disaster" in reason):
            self.symbol_cooldown[sym] = time.time() + self.revenge_cooldown * 60
            self._log("info", f"cooldown {sym} for {self.revenge_cooldown}m after loss")
        self.mind.observe_trade(pnl)
        self._log("trade", f"CLOSE {sym} {qty} @ {exit_price:.2f} pnl=${pnl:.2f} ({reason})")
        self._notify(f"CLOSE {sym} x{qty} @ {exit_price:.2f} pnl ${pnl:.2f} ({reason})", "trade")

    def _trail_dist(self, entry: float, atr: float, risk0: float) -> float:
        """Trail width for the runner: wide enough to survive noise, not so wide
        it gives the whole move back."""
        return max(atr * self.limits.trail_mult, entry * 0.0035, risk0 * 0.5)

    async def _scale_out(self, sym: str, p: dict, price: float, frac: float, reason: str) -> bool:
        """Sell/fade a fraction of a winning position to bank risk insurance."""
        qty = int(abs(p["qty"]) * frac)
        if qty < 1:
            return False
        direction = 1 if p["qty"] > 0 else -1
        side = "sell" if direction > 0 else "buy"
        try:
            order = await self.broker.submit_order(symbol=sym, qty=qty, side=side)
        except Exception as e:  # noqa: BLE001
            self._log("error", f"scale order failed {sym}: {e}")
            return False
        exit_price = float(order.get("filled_avg_price") or price)
        entry = p["avg_entry"]
        pnl = (exit_price - entry) * qty * direction
        pnl_pct = (exit_price / entry - 1) * direction if entry else 0.0
        storage.log_trade({
            "symbol": sym, "side": "long" if direction > 0 else "short", "qty": qty,
            "entry_price": round(entry, 4), "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 4), "reason": reason,
            "tags": ["scale"], "order_id": order.get("id"),
        })
        self.mind.observe_trade(pnl)
        self._log("trade", f"SCALE {sym} x{qty} @ {exit_price:.2f} pnl=${pnl:.2f} ({reason})")
        self._notify(f"SCALE {sym} x{qty} @ {exit_price:.2f} pnl ${pnl:.2f} ({reason})", "trade")
        return True

    # ------------------------------------------------------------------
    async def _consider_entries(self, account: dict, pos_syms: set[str]) -> None:
        positions = await self.broker.get_positions()
        gross = sum(abs(p["market_value"]) for p in positions)
        state = PortfolioState(
            equity=account["equity"], cash=account["cash"], day_pnl=account["day_pnl"],
            open_positions=len(positions), gross_exposure=gross, trades_today=self.trades_today,
        )
        allowed, blocks = check_portfolio(state, self.limits)
        mind_ok, mind_why = self.mind.can_trade()
        if not mind_ok:
            blocks.append(mind_why)
            allowed = False
        # portfolio heat: cap the sum of open $ risk (entry->stop) across all names
        # so a single correlated shock cannot hit every position at once.
        open_heat = 0.0
        for p in positions:
            m = self.positions.get(p["symbol"]) or {}
            open_heat += abs(p["qty"]) * abs(m.get("risk") or 0.0)
        heat_frac = open_heat / account["equity"] if account["equity"] else 0.0
        if heat_frac >= self.max_open_heat_pct:
            blocks.append(f"portfolio heat {heat_frac:.1%} >= cap {self.max_open_heat_pct:.0%}")
            allowed = False
        win_prob, wl = self._recent_edge()
        await self._refresh_market()

        # one-way-concentration guard: count how many names we already hold on
        # each side so a macro move cannot stop out a whole directional book.
        side_counts = {1: 0, -1: 0}
        for p in positions:
            side_counts[1 if p["qty"] > 0 else -1] += 1

        for sym in self.universe:
            if sym in pos_syms or sym in self.positions:
                continue
            cd_until = self.symbol_cooldown.get(sym, 0.0)
            if cd_until > time.time():
                continue
            try:
                bars = await self.broker.get_bars(sym, TIMEFRAME, BARS)
            except Exception as e:  # noqa: BLE001
                self._log("warn", f"bars failed {sym}: {e}")
                continue
            feat = indicators.compute_features(bars)
            sent = self.sentiment.get(sym, 0.0)
            sparams = {"rr": self.limits.rr, "atr_mult": self.limits.atr_mult}
            ctx = strategy.analyze(sym, bars, news_sentiment=sent, params=sparams, feat=feat,
                                   market=self.market)

            if ctx["action"] == "HOLD" or ctx["confidence"] < 0.15:
                continue

            # higher-timeframe trend confirmation + breakout entry (candidates only)
            htf = None
            if settings.mtf_enabled:
                try:
                    htf_bars = await self.broker.get_bars(sym, settings.mtf_timeframe, 160)
                    htf = mtf.trend_of(htf_bars)
                    bo = mtf.breakout(htf_bars)
                    htf["breakout"] = bo["dir"]
                    htf["breakout_reason"] = bo["reason"]
                except Exception as e:  # noqa: BLE001
                    self._log("warn", f"mtf bars failed {sym}: {e}")
                ctx = strategy.analyze(sym, bars, news_sentiment=sent, params=sparams,
                                       feat=feat, htf=htf, market=self.market)

            # LLM narrative layer (only for actual candidates)
            if self.analyst.enabled:
                brief = await self.analyst.market_brief(
                    sym,
                    {"regime": ctx["regime"], "signals": [s["name"] for s in ctx["signals"]],
                     "features": ctx["features"]},
                    self._headlines_for(sym),
                )
                if brief.get("brief") or brief.get("bias"):
                    ctx = strategy.analyze(sym, bars, news_sentiment=sent, llm_brief=brief,
                                           params=sparams, feat=feat, htf=htf, market=self.market)

            # adverse-selection: require more conviction in elevated/toxic flow
            tox = ctx.get("toxicity") or {}
            min_conf = self.limits.min_confidence + float(tox.get("require_conf") or 0.0)
            meets = ctx["confidence"] >= min_conf and ctx["action"] in ("BUY", "SELL")
            decision_row = {
                "symbol": sym, "action": ctx["action"], "confidence": ctx["confidence"],
                "price": ctx["price"], "regime": ctx["regime"], "reasons": ctx["reasons"],
                "features": ctx["features"], "llm": ctx.get("llm", {}), "executed": 0,
            }

            if tox.get("block"):
                decision_row["error"] = tox["reason"]
                storage.log_decision(decision_row)
                continue

            if not meets or not allowed:
                blocker = blocks if not allowed else [f"confidence {ctx['confidence']:.2f} < {min_conf:.2f}"]
                decision_row["error"] = "; ".join(blocker)
                storage.log_decision(decision_row)
                for b in blocks:
                    if "daily loss limit" in b and self._last_halt != b:
                        self._last_halt = b
                        self._notify(f"Daily loss limit hit - {b}", "error")
                continue

            # --- elite day-trader selectivity: refuse low-quality setups so we
            # trade less and only when the odds are genuinely stacked our way ---
            if settings.elite_enabled:
                if settings.elite_session_filter:
                    sok, sreason = elite.session_ok()
                    if not sok:
                        decision_row["error"] = f"elite: {sreason}"
                        storage.log_decision(decision_row)
                        continue
                ev = elite.evaluate(sym, ctx, htf, self.market,
                                    min_rvol=settings.elite_min_rvol,
                                    require_trend=settings.elite_require_trend,
                                    market_veto=settings.elite_market_veto)
                if not ev["ok"]:
                    decision_row["error"] = "elite veto: " + "; ".join(ev["veto"])
                    storage.log_decision(decision_row)
                    continue
                if ev["score"] < settings.elite_min_score:
                    decision_row["error"] = f"elite score {ev['score']:.2f} < {settings.elite_min_score:.2f}"
                    storage.log_decision(decision_row)
                    continue
                ctx["reasons"].append("elite: " + " · ".join(ev["notes"]))
                ctx["elite"] = ev
                try:
                    ctx["thesis"] = elite.thesis(sym, ctx, htf)
                except Exception as e:  # noqa: BLE001
                    self._log("warn", f"thesis {sym} failed: {e}")

            ctx = strategy.size_decision(ctx, account["equity"], self.limits, win_prob, wl)
            mult = self.mind.size_multiplier()
            base_qty = ctx["sizing"].get("qty", 0)
            qty = int(base_qty * mult)
            ctx["sizing"]["mind_mult"] = round(mult, 3)
            ctx["sizing"]["qty_raw"] = base_qty
            ctx["sizing"]["qty"] = qty
            if qty < 1:
                if ctx["sizing"].get("tox_dampen", 1.0) == 0:
                    decision_row["error"] = (ctx.get("toxicity") or {}).get("reason", "toxic flow")
                elif ctx["sizing"].get("dampen", 1.0) < 1:
                    decision_row["error"] = f"dampened off (x{ctx['sizing']['dampen']:.2f})"
                elif base_qty >= 1:
                    decision_row["error"] = "size 0 (risk/notional constraints)"
                else:
                    decision_row["error"] = f"mind sized down x{mult:.2f} ({self.mind.state})"
                storage.log_decision(decision_row)
                continue

            direction = ctx["direction"]
            if side_counts.get(direction, 0) >= self.limits.max_positions_per_side:
                side_name = "long" if direction > 0 else "short"
                decision_row["error"] = (f"side cap: already {side_counts[direction]} {side_name} "
                                         f"positions (max {self.limits.max_positions_per_side}) - "
                                         f"refusing to stack a one-way bet")
                storage.log_decision(decision_row)
                continue

            side = "buy" if ctx["action"] == "BUY" else "sell"
            try:
                order = await self.broker.submit_order(
                    symbol=sym, qty=qty, side=side,
                    stop_loss={"stop": ctx["stop"]}, take_profit={"target": ctx["target"]},
                )
            except Exception as e:  # noqa: BLE001
                decision_row["error"] = f"order failed: {e}"
                storage.log_decision(decision_row)
                self._log("error", f"order failed {sym}: {e}")
                continue

            direction = ctx["direction"]
            self.positions[sym] = {
                "stop": ctx["stop"], "target": ctx["target"], "opened": time.time(),
                "high_water": ctx["entry"], "reason": ", ".join(s["name"] for s in ctx["signals"]),
                "signals": [s["name"] for s in ctx["signals"]],
                "regime": ctx["regime"],
                "kelly": ctx["sizing"].get("kelly"),
                "atr": ctx.get("atr_raw") or ctx["entry"] * 0.01,
                "risk": abs(ctx["entry"] - ctx["stop"]) or ctx["entry"] * 0.01,
                "thesis": ctx.get("thesis"),
            }
            decision_row.update({"executed": 1, "qty": qty, "order_id": order.get("id")})
            decision_row["features"] = {**ctx["features"], "sizing": ctx["sizing"],
                                        "mtf_mult": ctx.get("mtf_mult"),
                                        "mtf_label": (ctx.get("mtf") or {}).get("label"),
                                        "market": (ctx.get("market") or {}).get("label"),
                                        "toxic": (ctx.get("toxicity") or {}).get("level"),
                                        "thesis": ctx.get("thesis"),
                                        "elite": ctx.get("elite")}
            storage.log_decision(decision_row)
            mtf_tag = (ctx.get("mtf") or {}).get("label", "OFF")
            mkt_tag = (ctx.get("market") or {}).get("label", "OFF")
            self._log("trade", f"OPEN {ctx['action']} {sym} x{qty} @ {ctx['entry']:.2f} "
                               f"stop {ctx['stop']:.2f} tgt {ctx['target']:.2f} conf {ctx['confidence']:.2f} "
                               f"[{self.mind.state} x{mult:.2f}] MTF:{mtf_tag} MKT:{mkt_tag}")

    # ------------------------------------------------------------------
    def _finalize_daily(self, account: dict) -> None:
        day_start = datetime.now(ET).strftime("%Y-%m-%d")
        # start-of-day ts in ET midnight
        midnight = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
        since = midnight.timestamp()
        trades = storage.recent_trades(since=since, limit=1000)
        equity_pts = storage.equity_series(since=since, limit=20000)
        if not equity_pts:
            return
        from .stats import daily_stats
        s = daily_stats(day_start, trades, equity_pts)
        storage.upsert_daily_stats(day_start, s)

    # ------------------------------------------------------------------
    async def close_symbol(self, symbol: str) -> dict:
        positions = await self.broker.get_positions()
        p = next((x for x in positions if x["symbol"] == symbol), None)
        if not p:
            return {"ok": False, "error": "no position"}
        price = p.get("current_price") or await self.broker.get_latest_price(symbol)
        await self._close_position(symbol, p, price, "manual")
        return {"ok": True}

    def set_risk_profile(self, profile: str) -> dict:
        self.risk_profile = profile
        self.limits = profile_limits(profile)
        storage.set_setting("risk_profile", profile)
        return {"risk_profile": profile, "limits": self.limits.__dict__}

    # ------------------------------------------------------------------
    async def build_snapshot(self) -> dict:
        account = await self.broker.get_account()
        positions = await self.broker.get_positions()
        orders = await self.broker.get_orders(limit=40)
        decisions = storage.recent_decisions(limit=60)
        news = storage.recent_news(limit=40)
        day_stats = storage.daily_stats_series(limit=30)
        return {
            "mode": self.broker.mode,
            "bot": {
                "running": self.running,
                "market_open": self.market_open,
                "clock": dict(self.clock),
                "last_scan": self.last_scan,
                "scan_interval": self.scan_interval,
                "universe": self.universe,
                "limits": self.limits.__dict__,
                "trades_today": self.trades_today,
                "day": self.day,
                "day_start_equity": self.day_start_equity,
                "errors": self.errors,
                "flatten_on_stop": self.flatten_on_stop,
                "notify": {"enabled": self.notifier.enabled, "kind": self.notifier.kind,
                           "sent": self.notifier.sent, "last_error": self.notifier.last_error},
                "mtf": {"enabled": settings.mtf_enabled, "timeframe": settings.mtf_timeframe,
                        "align_boost": settings.mtf_align_boost,
                        "conflict_penalty": settings.mtf_conflict_penalty,
                        "block_on_conflict": settings.mtf_block_on_conflict},
                "alpha": {"enabled": settings.alpha_decay_enabled,
                          "half_life_days": settings.alpha_half_life_days,
                          "weights": self.alpha.edge_weights()},
                "rl": {"enabled": settings.rl_enabled,
                       "min_obs": settings.rl_min_obs,
                       "arms": self.policy.summary()},
                "market": dict(self.market),
                "risk_profile": self.risk_profile,
                "real_data_only": settings.real_data_only,
                "cross_asset": {"enabled": settings.cross_asset_enabled,
                                "symbols": settings.cross_asset_symbols,
                                "weight": settings.cross_asset_weight},
                "toxic": {"enabled": settings.toxic_enabled,
                          "vpin_high": settings.toxic_vpin_high,
                          "vpin_extreme": settings.toxic_vpin_extreme,
                          "block": settings.toxic_block},
                "llm": {"provider": self.analyst.provider, "enabled": self.analyst.enabled,
                        "last_error": self.analyst.last_error},
            },
            "account": account,
            "positions": positions,
            "orders": orders,
            "decisions": decisions,
            "news": news,
            "daily_stats": day_stats,
            "log": list(self.log)[:60],
            "tape": self.tape.snapshot(),
            "psyche": self.mind.snapshot(),
            "regime_method": settings.regime_method,
            "universe_size": storage.universe_count(),
            "alerts_fired": list(self.alerts_fired)[:20],
            "tracked": [
                {"symbol": k, "stop": v["stop"], "target": v["target"],
                 "opened": v["opened"], "reason": v["reason"],
                 "thesis": v.get("thesis"),
                 "stage": v.get("stage", 0), "high_water": v.get("high_water")}
                for k, v in self.positions.items()
                for k, v in self.positions.items()
            ],
        }
