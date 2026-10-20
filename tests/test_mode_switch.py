"""Smoke test for the market-switch endpoint (offline).

Drives GET/POST /api/mode through the ASGI app with a stub bot and a stubbed
universe loader, so the contract is verified without touching the network or
the cached universe table. The previous market mode + persisted setting are
restored before the process exits.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app import config, elite, storage, universe
from app.alpaca import get_broker
from app import server as srv


class _StubBot:
    """Minimal stand-in for TradingBot: records the hot-swap, never trades."""

    def __init__(self) -> None:
        self.running = False
        self.applied = None

    def apply_market(self, mode, broker, watchlist):
        self.applied = (mode, getattr(broker, "mode", ""), list(watchlist))


async def _main() -> int:
    storage.init_db()
    s = config.settings
    orig_market = storage.get_market()
    orig_mode = s.market_mode
    orig_persisted = storage.get_setting("market_mode")
    orig_broker = srv.state.broker
    orig_ensure = universe.ensure_universe

    async def _offline_universe(broker, *, force=False):
        return 0

    srv.state.bot = _StubBot()
    srv.state.broker = get_broker("stocks")
    universe.ensure_universe = _offline_universe
    try:
        transport = httpx.ASGITransport(app=srv.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            start = (await c.get("/api/mode")).json()
            assert start["mode"] in ("stocks", "forex"), start
            assert start["running"] is False, start

            target = "forex" if start["mode"] == "stocks" else "stocks"
            r = await c.post("/api/mode", json={"mode": target})
            got = r.json()
            assert r.status_code == 200, (r.status_code, got)
            assert got["ok"] and got["changed"] is True, got
            assert got["mode"] == target, got
            assert got["running"] is False, got
            assert got["watchlist"], got
            assert srv.state.bot.applied is not None, "bot must be hot-swapped"
            assert srv.state.bot.applied[0] == target, srv.state.bot.applied
            assert srv.state.bot.applied[2], srv.state.bot.applied
            print(f"POST /api/mode ({start['mode']} -> {target}) -> ok, "
                  f"broker={got['broker']}, watchlist={len(got['watchlist'])}")

            again = (await c.post("/api/mode", json={"mode": target})).json()
            assert again["changed"] is False, again
            print("POST /api/mode (same mode) -> changed=false")

            back = (await c.post("/api/mode", json={"mode": start["mode"]})).json()
            assert back["changed"] is True and back["mode"] == start["mode"], back
            print(f"POST /api/mode ({target} -> {start['mode']}) -> restored")
        print("market-switch smoke OK")
        return 0
    finally:
        universe.ensure_universe = orig_ensure
        s.market_mode = orig_mode
        storage.set_market(orig_market)
        elite.set_market(orig_mode)
        srv.state.broker = orig_broker
        if orig_persisted is None:
            conn = storage._conn()
            conn.execute("DELETE FROM app_settings WHERE key='market_mode'")
            conn.commit()
            conn.close()
        else:
            storage.set_setting("market_mode", orig_persisted)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
