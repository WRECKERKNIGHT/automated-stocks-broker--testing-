# AI Trader

A fully automated **paper-trading** bot for US stocks with a real-time terminal
dashboard. It trades a real Alpaca paper account on real IEX market data, with
strict risk management, a quant signal engine, an elite day-trader selectivity
gate, "coded emotions", and a strict **no fake data** policy.

> **Not financial advice.** Paper trading only by default. There is no profit
> guarantee. Walk-forward optimization reports honestly when there is no
> out-of-sample edge.

## Features

- **Real data only** - Alpaca IEX feed for prices, bars and news. Synthetic
  random-walk data is used *only* when no API keys are configured. `REAL_DATA_ONLY`
  ensures a dropped feed surfaces an error instead of fabricated numbers.
- **Quant engine** - multi-factor signal scoring with multi-timeframe
  confirmation, regime detection, cross-asset breadth, toxic-flow (VPIN)
  defence, alpha decay and a contextual-bandit trust layer.
- **Elite playbook** - a selectivity gate modeled on elite day traders
  (session filter, higher-timeframe trend alignment, RVOL, chop veto).
- **Human-style risk** - structural swing-based stops with a grace period, a
  disaster backstop, break-even after +1R, a partial scale-out into strength,
  and a trailing runner. There are deliberately **no stall exits and no papercut
  exits**: a position is held until its thesis breaks, not until a clock runs out.
- **The Trader's Brain** (`app/elite.py`) - each entry is framed as a human
  trade plan (setup, trigger, invalidation, objective, expected hold + patience)
  grounded in the writing of Wyckoff, Livermore, PTJ, Minervini, Raschke, Brooks,
  Zanger, Seykota and Douglas.
- **Risk realities** - `conservative` / `balanced` / `aggressive` profiles.
- **Coded emotions** - a psyche layer that pauses (not permanently halts) on
  profit give-back, and hard-stops on daily loss.
- **Knowledge base** - 100+ trading books distilled into lessons injected into
  the analyst prompt.
- **Dashboard** - FastAPI + WebSocket + TradingView Lightweight Charts, dark
  terminal theme, desktop app window via a chromeless browser profile.

## Quick start

```bat
:: 1. install dependencies
python -m pip install -r requirements.txt

:: 2. configure credentials
copy .env.example .env
::    then edit .env and add your Alpaca paper keys

:: 3. run
python run.py
::    open http://127.0.0.1:8000
```

Or launch the desktop app (starts the server and opens an app window):

```bat
AI Trader.bat
```

## Configuration

All configuration is via environment variables / `.env` (see `.env.example`).
Key settings: Alpaca keys, `RISK_PROFILE`, `REAL_DATA_ONLY`, `WATCHLIST` (the
traded universe), the `ELITE_*` gate, and the human-style stop management block
(`STOP_GRACE_MIN`, `DISASTER_STOP_PCT`, `MAX_HOLD_MIN`, `REVENGE_COOLDOWN_MIN`,
`STOP_GRACE_MULT`).

For a deep explanation of what this is, how it trades, on what basis, and what
it depends on, see **[docs/TRADING_SYSTEM.md](docs/TRADING_SYSTEM.md)**.

## Project layout

```
app/      trading engine, broker, risk, server, knowledge, elite playbook
web/      dashboard (index.html, app.js, styles.css)
data/     SQLite store + logs (git-ignored)
tests/    smoke tests
tools/    utilities (headless UI inspector)
run.py    server entry point
launch.py desktop launcher
```

## Tests

```bat
python tests\smoke_risk.py
python tests\smoke_bot.py
python tests\smoke_api.py
python tests\smoke_market.py
python tests\smoke_psyche.py
```

## Market modes: Stocks and Forex

AI Trader trades one market at a time and can switch live from the dashboard
drawer (the **Stocks / Forex** button). Stock mode uses the Alpaca paper
broker; Forex mode uses a free public price feed with simulated order fills,
so no forex broker keys are required. Both modes share the same SQLite store,
so the **Overall** tab shows combined stats across every market. The drawer
can also warm up the learning pipeline for the new universe (**Train**).

Key settings: `MARKET_MODE` (`stocks` default), `FOREX_WATCHLIST`.
