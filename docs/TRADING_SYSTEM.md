# AI Trader - Trading System Design

> **This is an educational, paper-trading system. It is not financial advice,
> and it makes no profit guarantee.** The walk-forward optimiser will honestly
> report `NO OUT-OF-SAMPLE EDGE` when a parameter set does not generalise. Treat
> every number in the dashboard as a measurement, not a promise.

---

## 1. What this is

AI Trader is a fully automated, intraday **US-equity day-trading bot**. It:

- connects to **Alpaca** and trades a **paper** account (real orders, real fills,
  real P&L - just not real money by default),
- reads **real market data** (Alpaca IEX feed: bars, latest trades, quotes,
  news) - it will **refuse to fabricate prices** when `REAL_DATA_ONLY=true`,
- decides entirely on its own - no human clicks a buy or a sell,
- explains itself: every decision, entry, exit, scale and veto is written to a
  SQLite journal and streamed to a dark-terminal dashboard.

It is deliberately built around **one idea**: a good trader is mostly a *risk
manager and a refuser of bad trades*, not a predictor. The engine therefore
spends most of its intelligence on *when NOT to trade* and *how to hold a trade
that is working*.

---

## 2. The trading loop (how it works, end to end)

The bot runs `TradingBot.scan_once()` on an interval (`SCAN_INTERVAL_SEC`,
default 60s while the market is open). One scan is:

```
 clock ─┐
 account ┤                        ┌─ _refresh_news()   → headlines + sentiment
        │                         │
  new day? reset counters         ├─ _manage_exits()   → BE / scale / trail / stop
        │                         │
 market open? ─────────────────── ┤
        │                         ├─ _consider_entries() → the whole decision stack
        │                         │
        └─────────────────────────┴─ _finalize_daily()  → daily stats snapshot
                                        │
                                        └─ build_snapshot() → WebSocket → dashboard
```

`app/bot.py` is the orchestrator. Everything else is a specialist module it
calls:

| Stage | Module | Job |
|---|---|---|
| Data | `app/alpaca.py` | Broker: account, positions, bars, latest price, news, order submit |
| Features | `app/indicators.py` | RSI, EMA/VWAP, ATR, ADX, RVOL, structure, volume profile |
| Regime | `app/regime.py`, `app/hmm.py` | Trend / range / volatile classification (hybrid) |
| Breadth | `app/cross_asset.py` | Index/leader alignment ("don't fight the tape") |
| Toxic flow | `app/microstructure.py` | VPIN / adverse-selection defence |
| Signal | `app/strategy.py` | Score factors → action, confidence, stop, target |
| Multi-timeframe | `app/mtf.py` | Higher-timeframe trend + breakout confirmation |
| Narrative | `app/analyst.py` | Optional LLM read of headlines/context (off by default) |
| Selectivity | `app/elite.py` | **The Trader's Brain** - refuse bad setups, emit a thesis |
| Sizing/limits | `app/risk.py` | Position size, exposure, daily-loss, R-multiples |
| Psychology | `app/psyche.py` | Pause on give-back, hard stop on daily loss, recover |
| Memory | `app/storage.py` | SQLite journal (decisions, trades, equity, stats) |
| Learning | `app/alpha.py`, `app/rl.py` | Contextual-bandit trust + policy learner |
| Validation | `app/backtest.py`, `app/wfo.py` | Historical replay + walk-forward |
| API/UI | `app/server.py`, `web/` | FastAPI + WebSocket + TradingView charts |

---

## 3. The entry decision stack (on what basis it trades)

For each symbol in the watchlist, in order:

1. **Data gate** - fetch real 5-minute bars (`BARS=260`). If the feed is down
   and `REAL_DATA_ONLY=true`, log an error and skip; never invent data.
2. **Feature computation** - `indicators.compute_features()` produces the raw
   evidence: momentum (RSI/EMA slope), trend strength (ADX), participation
   (RVOL), volatility (ATR%), position vs VWAP/value-area, and swing structure.
3. **Regime detection** - classify the tape as TREND / RANGE / VOLATILE so the
   same signal is interpreted correctly in context.
4. **Toxicity check** (`microstructure.vpin`) - volume-clock VPIN. If flow is
   toxic (informed/adverse), either **block** the entry or **raise** the
   confidence required, so we don't get picked off by faster money.
5. **Signal scoring** (`strategy.analyze`) - multi-factor scoring with
   multi-timeframe confirmation and market breadth. Output: `action`
   (BUY/SELL/HOLD), `confidence`, `direction`, `reasons`, plus a **structural
   stop** and an R-multiple target.
6. **Confidence gate** - `confidence >= min_confidence (+ toxicity premium)`.
7. **The Trader's Brain** (`elite.evaluate`) - the selectivity gate. See §4.
8. **Sizing** (`strategy.size_decision` → `risk.position_size`) - risk-based
   sizing from the stop distance, then scaled by the psyche layer and dampeners.
9. **Execution** - market order via the broker. If it fills, the position's
   **thesis** (from `elite.thesis`) is stored and shown on the dashboard.

Every rejected symbol is journaled with the reason (low confidence, toxic flow,
elite veto, size 0, cooldown, ...), so you can *audit why the bot did nothing* -
which is most of the time, by design.

### Where the edge is supposed to come from

- **Trend alignment**: trading with the higher-timeframe line of least
  resistance (Livermore / PTJ).
- **Participation**: favoring names with relative-volume expansion (Zanger /
  Wyckoff).
- **Location**: buying pullbacks to value (VWAP/value-area) or liquidity-sweep
  reversals rather than chasing the middle of a range (Brooks).
- **Regime fit**: the same signal is weighted differently in a trend vs chop.
- **Breadth**: aligning with the index/leader complex instead of fighting it.

---

## 4. The Trader's Brain (`app/elite.py`)

This module encodes *how a disciplined human day trader thinks*, distilled from
the writing of:

| Trader | Idea it contributes |
|---|---|
| **Richard Wyckoff** | Trade with institutional intent; buy the spring / sell the upthrust; wait for the phase. |
| **Jesse Livermore** | Trade the main movement, not the ticks; wait for the pivotal point; never average a loser; sit tight. |
| **Paul Tudor Jones** | Defence first; don't fight the tape; the best trade is often the one you don't make. |
| **Mark Minervini** | Only confirmed uptrends; buy strength; risk 1-2%; only A+ setups. |
| **Linda Raschke** | Big moves come from volatility expansion; if it doesn't work quickly the odds weren't there. |
| **Al Brooks** | Trade with context; never trade the middle of a range. |
| **Dan Zanger** | The biggest gains are leaders on volume expansion. |
| **Ed Seykota** | Cut losses, ride winners, manage risk, know when to do nothing. |
| **Mark Douglas** | Think in probabilities; obey the process; never revenge-trade. |

It does three jobs:

1. **SESSION** - `session_phase()` knows the character of each part of the
   session (opening drive, morning trend, midday lull, afternoon trend, power
   hour). Breakouts are penalised in the midday lull; `session_ok()` refuses
   entries before 09:35 and after 15:50.
2. **SELECT** - `evaluate()` returns a quality verdict `{ok, score, notes, veto}`
   that *vetoes* fights-with-trend, dead-volume and choppy-tape setups and
   *scores* the rest (HTF alignment, RVOL, ADX, setup type, session, breadth,
   conviction). A trade must clear `elite_min_score` (default 0.45).
3. **THESIS** - `thesis()` turns a raw signal into a human plan:
   `setup / side / trigger / invalidation / objective / risk_per_share /
   expected_hold / patience`. This is what makes the position *manageable by
   idea* instead of by noise - the exit logic holds the trade while the thesis
   is intact and exits when it breaks.

`context_block()` also feeds a compact version of this playbook into the LLM
analyst prompt (`app/analyst.py`), so the optional narrative layer is grounded
in the same rules.

---

## 5. Exit & position management (the "trade like a human" core)

Implemented in `TradingBot._manage_exits()` and `_close_position()`. The design
philosophy: **a position is held until its thesis breaks - not until a clock or
a small red candle says so.**

Rules, in order:

1. **Disaster backstop (always on).** A hard stop at `max(DISASTER_STOP_PCT of
   price, STOP_GRACE_MULT × R)` from entry. This is the only thing that can take
   you out in the first minutes of a trade.
2. **Grace period.** For the first `STOP_GRACE_MIN` minutes, the *tight*
   structural stop is suspended (only the disaster backstop applies) **and only
   while the trade is near flat** (less than +0.5R). Ordinary noise cannot tag a
   fresh trade.
3. **Break-even after +1R.** Once the trade has paid a full unit of risk, the
   stop moves to entry (`limits.trail_after_r`). From here the trade is
   risk-free.
4. **Partial scale-out into strength.** At ~+2R, sell a third
   (`_scale_out(..., 0.34, ...)`) to bank insurance - then **let the rest run**.
5. **Trailing runner.** Once the high-water mark is +1R or better, trail the
   stop from the *high-water mark* by `_trail_dist()` =
   `max(ATR × trail_mult, 0.35% of price, 0.5R)`. Wide enough to survive noise,
   tight enough not to give back a big move.
6. **No target-based exit.** There is intentionally **no "target hit" full
   exit**. A hard target caps a winner; the trail lets it ride.
7. **No stall exit.** The old "cut trades that go nowhere after 90 min" rule is
   **removed**. There is only a loose `MAX_HOLD_MIN` time cap (default 360 min)
   that fires *only when the trade is still near flat* (`< 0.5R`) - i.e. it
   reclaims capital from genuinely dead trades but **never cuts a runner**.
8. **Anti-revenge cooldown.** After a real stop-out loss, the symbol is put on a
   `REVENGE_COOLDOWN_MIN` (45 min) cool-down so the bot cannot immediately
   re-buy a loser at a worse price (Douglas: don't revenge-trade).
9. **EOD / failsafe flatten.** `FLATTEN_ON_STOP` (optional) flattens everything
   on shutdown so nothing is carried into the close.

The previous loss post-mortem drove this rework: the bot had been taking
0.18-1.3% stops *inside the noise band* and force-closing flat trades with a
"stall exit", producing a string of -$ outcomes. The new rules widen effective
risk to structure, remove the papercut exits, and let winners run.

---

## 6. Risk model (`app/risk.py`)

Three profiles, selectable at runtime (`RISK_PROFILE`, `/api/profile`):

| | conservative | balanced (default) | aggressive |
|---|---|---|---|
| Risk per trade | 0.75% | ~1% | 1.5% |
| Max position % | 15% | - | 25% |
| Max open positions | 8 | **12** | 16 |
| Max trades/day | 25 | **40** | 60 |
| Gross exposure cap | 0.8× | - | 1.5× |
| Daily loss limit | 2% | - | 5% |
| Min confidence | 0.58 | **0.50** | 0.45 |
| R:R target | 2.2 | - | 2.0 |
| Stop ATR mult | 2.2 | **2.0** | 2.0 |
| Trail mult | 3.0 | **2.5** | 2.5 |
| Trail after | 2.0R | **1.5R** | 1.5R |

Key mechanics:

- **Position size** is risk-based: `qty = (equity × risk_per_trade) / stop_distance`,
  capped by max-position% and notional constraints. The **stop distance sets the
  size**, so a wider (structural) stop automatically means a smaller position.
- **Structural stops** (`risk.structural_stops`): placed where the idea is
  *wrong* (below/above the swing), not at a blind ATR distance, then floored to
  `min_stop_pct` (0.6%) and `ATR × atr_floor_mult` (1.2) so it stays outside the
  noise, and capped at `max_stop_pct` (3%).
- **Portfolio checks** (`risk.check_portfolio`): open positions, gross exposure,
  daily loss, trades-per-day - any breach blocks new entries and journals why.

---

## 7. Psychology & learning layers

- **`app/psyche.py` (`TraderMind`)** - "coded emotions". Tracks the day's P&L
  and pauses (not permanently halts) on profit give-back; a daily-loss breach
  hard-stops new risk. `POST /api/mind/resume` lets the operator clear a
  recoverable pause. It also emits a **size multiplier** the entry path applies.
- **`app/alpha.py`** - a contextual-bandit "trust" layer that adapts how much it
  believes each signal in each context, from realised outcomes.
- **`app/rl.py`** - a light policy learner that tracks `rl_ceil`-bounded
  adjustments.
- **`app/backtest.py` / `app/wfo.py`** - replay history and walk-forward
  optimisation. The WFO is intentionally honest and will print
  `NO OUT-OF-SAMPLE EDGE` rather than overfit a curve.
- **`app/knowledge.py`** - 100+ trading books distilled into lessons injected
  into the analyst prompt (`app/analyst.py`).
- **`app/pulse.py`, `app/ideas.py`, `app/research.py`, `app/alerts.py`,
  `app/analytics.py`** - supporting tools: market pulse, trade ideas, per-name
  research, alert rules, and analytics.

---

## 8. Persistence (`app/storage.py` → `data/aitrader.db`)

SQLite, one file. Principal tables:

| Table | Contents |
|---|---|
| `trades` | every fill: symbol, side, qty, entry/exit, pnl, pnl_pct, reason, tags |
| `decisions` | every candidate: action, confidence, reasons, features, error/veto |
| `equity` | equity curve samples for charting & stats |
| `daily_stats` | per-day win/loss/turnover snapshots |
| `signal_outcomes` | realised P&L attributed back to signals (for the bandit) |
| `universe` | cached tradable universe + metadata |
| `news`, `journal`, `alerts`, `optimize_runs`, `app_settings` | supporting state |

`reason` on each trade is the ground truth for the post-mortem: `stop out`,
`disaster stop`, `scale +2.0R (runner rides)`, `time stop (flat - reclaim
capital)`, `flatten`, etc.

---

## 9. Interface (`app/server.py` + `web/`)

- FastAPI exposes `/api/status` (a full `build_snapshot()` of account, bot,
  positions, decisions, news, daily stats, log, tape, psyche, tracked positions
  incl. each position's **thesis**), `/api/profile`, `/api/mind/resume`, the
  knowledge/coach/pulse/library routes, and a `/ws` WebSocket for live pushes.
- The dashboard is a dark terminal UI (TradingView Lightweight Charts) with a
  chart that can **follow** the selected symbol, an 18-section rail, the sim/live
  badge, and position cards that show the current **thesis** and stage.
- Desktop mode is a chromeless app window started by `launch.py` / `AI Trader.bat`.

---

## 10. What it depends on

**Hard dependencies (the bot cannot trade without these):**

- **Alpaca account + API keys** (`ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY`).
  With `ALPACA_PAPER=true` orders hit the paper endpoint. With no keys at all,
  the app falls back to an offline **DEMO** broker (synthetic data) - clearly
  badged, and never used while `REAL_DATA_ONLY=true` and keys are present.
- **Alpaca market-data feed** - `ALPACA_DATA_FEED=iex` (the free feed). It is a
  *partial* feed: it can miss prints and has no full SIP depth. That is a real
  disadvantage vs. paid feeds and is a known source of noise.
- **The market being open.** The bot only manages/enters during regular hours
  (`get_clock().is_open`); it does not trade the pre/post market.
- **Network + a running Python process** (server on `HOST:PORT`, default
  `127.0.0.1:8000`).
- **Python 3.11+** with `requirements.txt` (httpx, fastapi, uvicorn, numpy,
  pandas, websockets).

**Soft / optional dependencies:**

- **An LLM provider** (`LLM_PROVIDER`, default `none` = pure quant). Optional
  and off by default; if enabled it only *adds narrative and a bias nudge*, it
  never sizes or executes.
- **A notification webhook / Telegram** for trade & alert pushes (optional).

**Environmental realities to respect:**

- **Latency**: this is an HTTP-polling bot (`SCAN_INTERVAL_SEC=60`), not a
  colocated HFT system. It is built for intraday swings.
- **Rate limits**: a 58-symbol universe polled every 60s plus MTF bars is a lot
  of IEX calls - tune `SCAN_INTERVAL_SEC` / `WATCHLIST` to your feed's limits.
- **Slippage & fees**: market orders on IEX can fill away from the signal price;
  paper fills can be optimistic. Real P&L will differ.

---

## 11. Honest limitations

- **No guarantee of edge.** The system is a well-structured *process*, not a
  money printer. WFO can and does report no out-of-sample edge.
- **Small sample.** Early live results (e.g. the first handful of trades) are
  noise; judge the process over hundreds of trades, not the last few.
- **Partial data.** IEX is not the consolidated tape; signals can be late or
  thin in less-liquid names.
- **Cognitive layer is a model, not a person.** `elite.py` encodes *rules* of
  good traders; it cannot read true order flow or news nuance the way a human
  can. It reduces bad trades; it does not create information.
- **Overfitting risk.** More parameters = more ways to fit noise. Prefer stable
  defaults and walk-forward evidence over tuning.

---

## 12. Configuration reference (most-used)

| Variable | Default | Meaning |
|---|---|---|
| `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` | - | Alpaca paper keys |
| `ALPACA_PAPER` | `true` | Paper vs live endpoint |
| `ALPACA_DATA_FEED` | `iex` | Market-data feed |
| `WATCHLIST` | (58 liquid names) | The traded universe |
| `SCAN_INTERVAL_SEC` | 60 | Seconds between scans (market open) |
| `RISK_PROFILE` | `balanced` | conservative / balanced / aggressive |
| `REAL_DATA_ONLY` | `true` | Never fabricate prices |
| `ELITE_ENABLED` | `true` | Turn the selectivity gate on/off |
| `ELITE_MIN_SCORE` | 0.45 | Minimum quality score to enter |
| `ELITE_REQUIRE_TREND` | `true` | Veto trades against the HTF trend |
| `ELITE_SESSION_FILTER` | `true` | Skip open-crash / closing-drift windows |
| `STOP_GRACE_MIN` | 8 | Minutes the tight stop is suspended |
| `DISASTER_STOP_PCT` | 0.008 | Disaster backstop as fraction of price |
| `MAX_HOLD_MIN` | 360 | Time cap (flat trades only) |
| `REVENGE_COOLDOWN_MIN` | 45 | Per-symbol cool-down after a stop |
| `STOP_GRACE_MULT` | 1.4 | Disaster distance as multiple of R |
| `FLATTEN_ON_STOP` | `false` | Flatten all on shutdown |
| `LLM_PROVIDER` | `none` | Optional narrative layer |
