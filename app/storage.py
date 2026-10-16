"""SQLite persistence: decisions, trades, equity snapshots, daily stats, news."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import DATA_DIR

DB_PATH = DATA_DIR / "aitrader.db"
_lock = threading.RLock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    # busy_timeout lets a reader/writer wait for a brief write lock instead of
    # raising immediately; journal mode is set once in init_db (it is persisted
    # in the DB header, so re-issuing it on every connection only adds lock
    # contention against the live bot).
    c.execute("PRAGMA busy_timeout=30000")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL,
    price REAL,
    qty INTEGER,
    regime TEXT,
    reasons TEXT,
    features TEXT,
    llm TEXT,
    executed INTEGER DEFAULT 0,
    order_id TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    reason TEXT,
    tags TEXT,
    order_id TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    equity REAL,
    cash REAL,
    buying_power REAL,
    positions_value REAL,
    day_pnl REAL
);
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    start_equity REAL,
    end_equity REAL,
    pnl REAL,
    realized_pnl REAL,
    pnl_pct REAL,
    num_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_rate REAL,
    gross_profit REAL,
    gross_loss REAL,
    profit_factor REAL,
    avg_win REAL,
    avg_loss REAL,
    expectancy REAL,
    max_drawdown REAL,
    sharpe REAL,
    best_symbol TEXT,
    worst_symbol TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT,
    headline TEXT,
    source TEXT,
    url TEXT,
    sentiment REAL,
    summary TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS optimize_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    method TEXT,
    bar_limit INTEGER,
    stride INTEGER,
    folds INTEGER,
    grid_size INTEGER,
    wfe REAL,
    pbo REAL,
    mean_is REAL,
    mean_oos REAL,
    oos_pnl REAL,
    verdict TEXT,
    best_params TEXT,
    result TEXT
);
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL,
    regime TEXT,
    pnl REAL,
    ret REAL,
    win INTEGER
);
CREATE TABLE IF NOT EXISTS universe (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    exchange TEXT,
    tradable INTEGER,
    fractionable INTEGER,
    shortable INTEGER,
    sector TEXT,
    updated REAL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT,
    side TEXT,
    entry REAL,
    exit REAL,
    qty REAL,
    pnl REAL,
    rating INTEGER,
    tags TEXT,
    note TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    op TEXT,
    value REAL,
    note TEXT,
    active INTEGER DEFAULT 1,
    triggered INTEGER DEFAULT 0,
    triggered_ts REAL,
    last_price REAL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(ts);
CREATE INDEX IF NOT EXISTS idx_opt_ts ON optimize_runs(ts);
CREATE INDEX IF NOT EXISTS idx_sig_out_ts ON signal_outcomes(ts);
CREATE INDEX IF NOT EXISTS idx_sig_out_name ON signal_outcomes(signal);
CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active, triggered);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db() -> None:
    with _lock:
        c = _conn()
        c.executescript(SCHEMA)
        _migrate(c)
        c.commit()
        c.close()


def _migrate(c: sqlite3.Connection) -> None:
    """Additive migrations for databases created by older versions."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(signal_outcomes)").fetchall()}
    if "regime" not in cols:
        c.execute("ALTER TABLE signal_outcomes ADD COLUMN regime TEXT")


def _insert(table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    with _lock:
        c = _conn()
        cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(row.values()))
        c.commit()
        rid = cur.lastrowid
        c.close()
        return rid


def _query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _lock:
        c = _conn()
        rows = [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]
        c.close()
        return rows


# ----------------------------- writers -----------------------------

def log_decision(d: dict[str, Any]) -> int:
    d = dict(d)
    for k in ("reasons", "features", "llm"):
        if k in d and not isinstance(d[k], str):
            d[k] = json.dumps(d[k], default=str)
    d.setdefault("ts", time.time())
    return _insert("decisions", d)


def log_trade(t: dict[str, Any]) -> int:
    t = dict(t)
    if "tags" in t and not isinstance(t["tags"], str):
        t["tags"] = json.dumps(t["tags"], default=str)
    t.setdefault("ts", time.time())
    return _insert("trades", t)


def log_equity(e: dict[str, Any]) -> int:
    e = dict(e)
    e.setdefault("ts", time.time())
    return _insert("equity", e)


def upsert_daily_stats(date: str, s: dict[str, Any]) -> None:
    s = dict(s)
    s["date"] = date
    if "notes" in s and not isinstance(s["notes"], str):
        s["notes"] = json.dumps(s["notes"], default=str)
    cols = ", ".join(s.keys())
    placeholders = ", ".join(["?"] * len(s))
    updates = ", ".join(f"{k}=excluded.{k}" for k in s if k != "date")
    with _lock:
        c = _conn()
        c.execute(
            f"INSERT INTO daily_stats ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(date) DO UPDATE SET {updates}",
            list(s.values()),
        )
        c.commit()
        c.close()


def cache_news(items: list[dict[str, Any]]) -> None:
    with _lock:
        c = _conn()
        for it in items:
            c.execute(
                "INSERT INTO news (ts, symbol, headline, source, url, sentiment, summary, created) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    it.get("ts", time.time()),
                    it.get("symbol"),
                    it.get("headline"),
                    it.get("source"),
                    it.get("url"),
                    it.get("sentiment"),
                    it.get("summary"),
                    time.time(),
                ),
            )
        c.commit()
        c.close()


# ----------------------------- signal outcomes -----------------------------

def log_signal_outcomes(symbol: str, signals: list[str], pnl: float, ret: float,
                        regime: str | None = None, ts: float | None = None) -> None:
    """Attribute a realised trade to each signal that was active at entry."""
    sigs = [s for s in (signals or []) if s]
    if not sigs:
        return
    ts = ts or time.time()
    win = 1 if pnl > 0 else 0
    with _lock:
        c = _conn()
        for s in sigs:
            c.execute(
                "INSERT INTO signal_outcomes (ts, symbol, signal, regime, pnl, ret, win) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts, symbol, s, regime, float(pnl), float(ret), win),
            )
        c.commit()
        c.close()


# ----------------------------- optimize runs -----------------------------

def save_optimize_run(symbol: str, timeframe: str, method: str, bar_limit: int,
                      stride: int, folds: int, result: dict[str, Any]) -> int:
    s = (result or {}).get("summary", {}) or {}
    row = {
        "ts": time.time(),
        "symbol": symbol,
        "timeframe": timeframe,
        "method": method,
        "bar_limit": bar_limit,
        "stride": stride,
        "folds": folds,
        "grid_size": (result or {}).get("grid_size"),
        "wfe": s.get("walk_forward_efficiency"),
        "pbo": s.get("pbo"),
        "mean_is": s.get("mean_is_expectancy"),
        "mean_oos": s.get("mean_oos_expectancy"),
        "oos_pnl": s.get("oos_total_pnl"),
        "verdict": s.get("verdict"),
        "best_params": json.dumps(s.get("best_full_sample_params") or {}, default=str),
        "result": json.dumps(result or {}, default=str),
    }
    return _insert("optimize_runs", row)


# ----------------------------- readers -----------------------------

def recent_decisions(limit: int = 100, symbol: str | None = None) -> list[dict]:
    if symbol:
        return _query("SELECT * FROM decisions WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, limit))
    return _query("SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,))


def recent_trades(limit: int = 200, since: float | None = None) -> list[dict]:
    if since:
        return _query("SELECT * FROM trades WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, limit))
    return _query("SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,))


def equity_series(since: float | None = None, limit: int = 5000) -> list[dict]:
    if since:
        return _query("SELECT * FROM equity WHERE ts>=? ORDER BY ts ASC LIMIT ?", (since, limit))
    return _query("SELECT * FROM equity ORDER BY ts ASC LIMIT ?", (limit,))


def daily_stats_series(limit: int = 400) -> list[dict]:
    return _query("SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (limit,))


def recent_news(limit: int = 60, since: float | None = None) -> list[dict]:
    if since:
        return _query("SELECT * FROM news WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, limit))
    return _query("SELECT * FROM news ORDER BY ts DESC LIMIT ?", (limit,))


def all_trades() -> list[dict]:
    return _query("SELECT * FROM trades ORDER BY ts ASC")


def recent_signal_outcomes(limit: int = 3000) -> list[dict]:
    return _query(
        "SELECT ts, symbol, signal, regime, pnl, ret, win FROM signal_outcomes "
        "ORDER BY ts DESC LIMIT ?",
        (limit,),
    )


def recent_optimize_runs(limit: int = 30) -> list[dict]:
    rows = _query(
        "SELECT id, ts, symbol, timeframe, method, bar_limit, stride, folds, grid_size, "
        "wfe, pbo, mean_is, mean_oos, oos_pnl, verdict, best_params "
        "FROM optimize_runs ORDER BY ts DESC LIMIT ?",
        (limit,),
    )
    for r in rows:
        try:
            r["best_params"] = json.loads(r.get("best_params") or "{}")
        except (ValueError, TypeError):
            r["best_params"] = {}
    return rows


def get_optimize_run(run_id: int) -> dict | None:
    rows = _query("SELECT * FROM optimize_runs WHERE id=?", (run_id,))
    if not rows:
        return None
    r = rows[0]
    for k in ("best_params", "result"):
        try:
            r[k] = json.loads(r.get(k) or "{}")
        except (ValueError, TypeError):
            r[k] = {}
    return r


# ----------------------------- universe cache -----------------------------

def replace_universe(rows: list[dict[str, Any]]) -> int:
    """Bulk-replace the cached tradable universe."""
    with _lock:
        c = _conn()
        c.execute("DELETE FROM universe")
        c.executemany(
            "INSERT OR REPLACE INTO universe "
            "(symbol, name, exchange, tradable, fractionable, shortable, sector, updated) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (r.get("symbol"), r.get("name"), r.get("exchange"),
                 1 if r.get("tradable") else 0, 1 if r.get("fractionable") else 0,
                 1 if r.get("shortable") else 0, r.get("sector"), time.time())
                for r in rows
            ],
        )
        c.commit()
        c.close()
    return len(rows)


def get_universe() -> list[dict]:
    return _query("SELECT * FROM universe ORDER BY symbol")


def universe_meta() -> dict[str, dict]:
    return {r["symbol"]: r for r in _query("SELECT * FROM universe")}


def universe_count() -> int:
    rows = _query("SELECT COUNT(*) AS n FROM universe")
    return int(rows[0]["n"]) if rows else 0


# ----------------------------- journal -----------------------------

def add_journal(entry: dict[str, Any]) -> int:
    entry = dict(entry)
    if "tags" in entry and not isinstance(entry["tags"], str):
        entry["tags"] = json.dumps(entry["tags"], default=str)
    entry.setdefault("ts", time.time())
    entry["created"] = time.time()
    return _insert("journal", entry)


def recent_journal(limit: int = 200, symbol: str | None = None) -> list[dict]:
    if symbol:
        return _query("SELECT * FROM journal WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, limit))
    return _query("SELECT * FROM journal ORDER BY ts DESC LIMIT ?", (limit,))


def delete_journal(entry_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute("DELETE FROM journal WHERE id=?", (entry_id,))
        c.commit()
        c.close()


# ----------------------------- alerts -----------------------------

def add_alert(a: dict[str, Any]) -> int:
    a = dict(a)
    a.setdefault("ts", time.time())
    a.setdefault("active", 1)
    a.setdefault("triggered", 0)
    return _insert("alerts", a)


def recent_alerts(limit: int = 200, only_active: bool = False) -> list[dict]:
    if only_active:
        return _query("SELECT * FROM alerts WHERE active=1 AND triggered=0 ORDER BY ts DESC LIMIT ?", (limit,))
    return _query("SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,))


def active_alerts() -> list[dict]:
    return _query("SELECT * FROM alerts WHERE active=1 AND triggered=0")


def update_alert(alert_id: int, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        c = _conn()
        c.execute(f"UPDATE alerts SET {sets} WHERE id=?", (*fields.values(), alert_id))
        c.commit()
        c.close()


def delete_alert(alert_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
        c.commit()
        c.close()


# ----------------------------- app settings (key/value) -----------------------------

def get_setting(key: str, default: str | None = None) -> str | None:
    rows = _query("SELECT value FROM app_settings WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def set_setting(key: str, value: str) -> None:
    with _lock:
        c = _conn()
        c.execute("INSERT INTO app_settings(key, value) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        c.commit()
        c.close()
