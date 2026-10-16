"""Central configuration, loaded from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")


def _b(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


# Curated, liquid FX universe used by the merged app's "forex" market mode.
DEFAULT_FOREX_WATCHLIST = (
    "EUR_USD,GBP_USD,USD_JPY,USD_CHF,AUD_USD,USD_CAD,NZD_USD,"
    "EUR_JPY,GBP_JPY,EUR_GBP,EUR_CHF,AUD_JPY,XAU_USD,XAG_USD"
)

# Cross-asset "market breadth" proxies per mode. Stocks lean on index ETFs;
# forex leans on the majors + gold as the risk barometer.
DEFAULT_CROSS_STOCKS = "SPY,QQQ,IWM"
DEFAULT_CROSS_FOREX = "EUR_USD,USD_JPY,XAU_USD"


@dataclass
class Settings:
    # --- Alpaca ---
    alpaca_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY_ID", "").strip())
    alpaca_secret: str = field(default_factory=lambda: os.getenv("ALPACA_API_SECRET_KEY", "").strip())
    alpaca_paper: bool = field(default_factory=lambda: _b("ALPACA_PAPER", True))
    data_feed: str = field(default_factory=lambda: os.getenv("ALPACA_DATA_FEED", "iex").strip())

    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "none").strip().lower())
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434").strip())
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1").strip())
    openai_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip())
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip())
    anthropic_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip())
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest").strip())

    # --- Server ---
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1").strip())
    port: int = field(default_factory=lambda: _i("PORT", 8000))
    start_bot_on_launch: bool = field(default_factory=lambda: _b("START_BOT_ON_LAUNCH", True))
    scan_interval: int = field(default_factory=lambda: _i("SCAN_INTERVAL_SEC", 30))

    # --- Market mode: "stocks" (Alpaca) or "forex" (free public FX feed) ---
    # One process, one dashboard: the mode selects which broker + universe the
    # bot trades. The choice is switchable at runtime from the UI drawer and is
    # persisted in SQLite (app_settings.market_mode) so restarts keep it.
    market_mode: str = field(default_factory=lambda: os.getenv("MARKET_MODE", "stocks").strip().lower())

    # --- Engine ---
    regime_method: str = field(default_factory=lambda: os.getenv("REGIME_METHOD", "hybrid").strip().lower())
    tape_enabled: bool = field(default_factory=lambda: _b("TAPE_ENABLED", True))
    # The free IEX market-data feed rejects subscriptions above a hard symbol
    # limit (405 "symbol limit exceeded"), which silently killed the whole tape.
    tape_max_symbols: int = field(default_factory=lambda: _i("TAPE_MAX_SYMBOLS", 30))

    # --- Multi-timeframe confirmation ---
    mtf_enabled: bool = field(default_factory=lambda: _b("MTF_ENABLED", True))
    mtf_timeframe: str = field(default_factory=lambda: os.getenv("MTF_TIMEFRAME", "15Min").strip())
    mtf_fast: int = field(default_factory=lambda: _i("MTF_FAST", 20))
    mtf_slow: int = field(default_factory=lambda: _i("MTF_SLOW", 50))
    mtf_align_boost: float = field(default_factory=lambda: _f("MTF_ALIGN_BOOST", 1.2))
    mtf_conflict_penalty: float = field(default_factory=lambda: _f("MTF_CONFLICT_PENALTY", 0.5))
    mtf_block_on_conflict: bool = field(default_factory=lambda: _b("MTF_BLOCK_ON_CONFLICT", False))
    mtf_breakout_lookback: int = field(default_factory=lambda: _i("MTF_BREAKOUT_LOOKBACK", 20))

    # --- Cross-asset / market breadth (leading context) ---
    cross_asset_enabled: bool = field(default_factory=lambda: _b("CROSS_ASSET_ENABLED", True))
    cross_asset_symbols: list[str] = field(default_factory=lambda: _list("CROSS_ASSET_SYMBOLS", "SPY,QQQ,IWM"))
    cross_asset_weight: float = field(default_factory=lambda: _f("CROSS_ASSET_WEIGHT", 0.2))

    # --- Adverse-selection / toxic-flow defence ---
    toxic_enabled: bool = field(default_factory=lambda: _b("TOXIC_ENABLED", True))
    toxic_vpin_high: float = field(default_factory=lambda: _f("TOXIC_VPIN_HIGH", 0.45))
    toxic_vpin_extreme: float = field(default_factory=lambda: _f("TOXIC_VPIN_EXTREME", 0.65))
    toxic_size_dampen: float = field(default_factory=lambda: _f("TOXIC_SIZE_DAMPEN", 0.5))
    toxic_conf_penalty: float = field(default_factory=lambda: _f("TOXIC_CONF_PENALTY", 0.05))
    toxic_block: bool = field(default_factory=lambda: _b("TOXIC_BLOCK", False))

    # --- Alpha decay (signal down-weighting) ---
    alpha_decay_enabled: bool = field(default_factory=lambda: _b("ALPHA_DECAY_ENABLED", True))
    alpha_half_life_days: float = field(default_factory=lambda: _f("ALPHA_HALF_LIFE_DAYS", 5.0))
    alpha_min_obs: int = field(default_factory=lambda: _i("ALPHA_MIN_OBS", 5))
    alpha_gain: float = field(default_factory=lambda: _f("ALPHA_GAIN", 0.5))
    alpha_floor: float = field(default_factory=lambda: _f("ALPHA_FLOOR", 0.3))
    alpha_ceil: float = field(default_factory=lambda: _f("ALPHA_CEIL", 1.5))

    # --- RL / contextual bandit (regime-aware signal trust) ---
    rl_enabled: bool = field(default_factory=lambda: _b("RL_ENABLED", True))
    rl_min_obs: int = field(default_factory=lambda: _i("RL_MIN_OBS", 4))
    rl_prior_strength: float = field(default_factory=lambda: _f("RL_PRIOR_STRENGTH", 6.0))
    rl_prior_scale: float = field(default_factory=lambda: _f("RL_PRIOR_SCALE", 0.01))
    rl_gain: float = field(default_factory=lambda: _f("RL_GAIN", 0.5))
    rl_scale: float = field(default_factory=lambda: _f("RL_SCALE", 0.01))
    rl_floor: float = field(default_factory=lambda: _f("RL_FLOOR", 0.4))
    rl_ceil: float = field(default_factory=lambda: _f("RL_CEIL", 1.5))

    # --- Watchdog / notifications ---
    notify_url: str = field(default_factory=lambda: os.getenv("NOTIFY_WEBHOOK_URL", "").strip())
    notify_kind: str = field(default_factory=lambda: os.getenv("NOTIFY_KIND", "auto").strip().lower())
    notify_telegram_chat: str = field(default_factory=lambda: os.getenv("NOTIFY_TELEGRAM_CHAT", "").strip())

    # --- Failsafe ---
    flatten_on_stop: bool = field(default_factory=lambda: _b("FLATTEN_ON_STOP", False))

    # --- Data integrity: never fabricate market data ---------------
    # When true, the app will NOT silently substitute synthetic (random-walk)
    # prices for real Alpaca data. If the live feed drops it surfaces an error
    # and retries instead of showing made-up numbers. Synthetic data is only
    # ever used when no API keys are configured at all (offline DEmo mode).
    real_data_only: bool = field(default_factory=lambda: _b("REAL_DATA_ONLY", True))

    # --- Risk profile: conservative | balanced | aggressive ---
    risk_profile: str = field(default_factory=lambda: os.getenv("RISK_PROFILE", "balanced").strip().lower())

    # --- Elite day-trader playbook (selectivity gate) ---
    elite_enabled: bool = field(default_factory=lambda: _b("ELITE_ENABLED", True))
    elite_min_score: float = field(default_factory=lambda: _f("ELITE_MIN_SCORE", 0.45))
    elite_require_trend: bool = field(default_factory=lambda: _b("ELITE_REQUIRE_TREND", True))
    elite_session_filter: bool = field(default_factory=lambda: _b("ELITE_SESSION_FILTER", True))
    elite_min_rvol: float = field(default_factory=lambda: _f("ELITE_MIN_RVOL", 0.8))
    elite_market_veto: bool = field(default_factory=lambda: _b("ELITE_MARKET_VETO", False))

    # --- Flexible (human-style) stop management ---
    # Patience first: give a fresh trade a lot of room and only exit when the
    # trade is genuinely *wrong* (wide disaster backstop), never on ordinary
    # noise. The old 0.8% disaster stop was inside the daily noise band and is
    # exactly what turned good ideas into a thousand small cuts.
    stop_grace_min: int = field(default_factory=lambda: _i("STOP_GRACE_MIN", 45))
    disaster_stop_pct: float = field(default_factory=lambda: _f("DISASTER_STOP_PCT", 0.035))
    max_hold_min: int = field(default_factory=lambda: _i("MAX_HOLD_MIN", 360))
    # Patience: a trade is held until its thesis breaks (structural stop / EOD),
    # NOT until a clock says so. The time-stop is therefore off by default and,
    # when enabled, only reclaims capital from a trade that never worked at all.
    time_stop_enabled: bool = field(default_factory=lambda: _b("TIME_STOP_ENABLED", False))
    revenge_cooldown_min: int = field(default_factory=lambda: _i("REVENGE_COOLDOWN_MIN", 45))
    stop_grace_mult: float = field(default_factory=lambda: _f("STOP_GRACE_MULT", 1.6))

    # --- Patience / let-it-run profit management ---
    # Hold until it goes up: protect the trade only after it has paid a full R,
    # never trim a winner by default (set SCALE_OUT_R>0 to bank a tranche), and
    # let the runner trail. Options flatten by the close (day-trading, no gap risk).
    breakeven_r: float = field(default_factory=lambda: _f("BREAKEVEN_R", 1.5))
    scale_out_r: float = field(default_factory=lambda: _f("SCALE_OUT_R", 0.0))
    scale_out_frac: float = field(default_factory=lambda: _f("SCALE_OUT_FRAC", 0.25))
    flatten_at_eod: bool = field(default_factory=lambda: _b("FLATTEN_AT_EOD", True))

    # --- Signal quality: require confluence, refuse to fade a trend ---
    min_confluence: int = field(default_factory=lambda: _i("MIN_CONFLUENCE", 2))
    antifade_enabled: bool = field(default_factory=lambda: _b("ANTIFADE_ENABLED", True))

    # --- Portfolio heat guard (sum of open $ risk) ---
    max_open_heat_pct: float = field(default_factory=lambda: _f("MAX_OPEN_HEAT_PCT", 0.06))

    # --- Market universe / scanner / research ---
    scanner_cache_sec: int = field(default_factory=lambda: _i("SCANNER_CACHE_SEC", 120))
    scanner_enrich_top: int = field(default_factory=lambda: _i("SCANNER_ENRICH_TOP", 30))
    universe_snapshot_chunk: int = field(default_factory=lambda: _i("UNIVERSE_SNAPSHOT_CHUNK", 400))
    research_news_limit: int = field(default_factory=lambda: _i("RESEARCH_NEWS_LIMIT", 12))
    ideas_max: int = field(default_factory=lambda: _i("IDEAS_MAX", 24))

    # --- Universe ---
    watchlist: list[str] = field(default_factory=lambda: [
        s.strip().upper()
        for s in os.getenv("WATCHLIST", (
            "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,AVGO,NFLX,CRM,ADBE,ORCL,INTC,"
            "QCOM,MU,AMAT,LRCX,PLTR,COIN,UBER,SHOP,SNOW,PANW,NOW,ARM,SMCI,MSTR,CRWD,"
            "DDOG,ZS,NET,HOOD,SOFI,PYPL,MARA,RIOT,CLSK,NIO,RIVN,LCID,F,GM,ABNB,DKNG,"
            "DIS,XOM,CVX,LLY,SPY,QQQ,IWM,SMH,SOXL,TQQQ,ARKK,XLE,XLF"
        )).split(",")
        if s.strip()
    ])

    # --- Forex universe (used when market_mode == "forex") ---
    forex_watchlist: list[str] = field(default_factory=lambda: [
        s.strip().upper()
        for s in os.getenv("FOREX_WATCHLIST", DEFAULT_FOREX_WATCHLIST).split(",")
        if s.strip()
    ])

    @property
    def trading_base(self) -> str:
        return "https://paper-api.alpaca.markets" if self.alpaca_paper else "https://api.alpaca.markets"

    @property
    def data_base(self) -> str:
        return "https://data.alpaca.markets"

    @property
    def alpaca_enabled(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)

    @property
    def mode(self) -> str:
        if self.alpaca_enabled:
            return "PAPER" if self.alpaca_paper else "LIVE"
        return "DEMO"

    # ---- market-mode helpers -------------------------------------------------
    def market(self) -> str:
        """Normalised active market: always "stocks" or "forex"."""
        return "forex" if str(self.market_mode).lower() == "forex" else "stocks"

    def watchlist_for(self, mode: str | None = None) -> list[str]:
        """The tradeable universe for a given market (defaults to the active one)."""
        m = (mode or self.market()).lower()
        return list(self.forex_watchlist) if m == "forex" else list(self.watchlist)

    def cross_asset_for(self, mode: str | None = None) -> list[str]:
        """Market-breadth proxies appropriate to the market."""
        m = (mode or self.market()).lower()
        if m == "forex":
            return [s.strip().upper() for s in
                    os.getenv("CROSS_ASSET_SYMBOLS_FOREX", DEFAULT_CROSS_FOREX).split(",") if s.strip()]
        return list(self.cross_asset_symbols)


settings = Settings()
