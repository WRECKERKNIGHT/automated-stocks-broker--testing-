import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app import storage
from app.alpaca import get_broker
from app.analyst import Analyst
from app.bot import TradingBot
from app.server import app, state


async def _main():
    storage.init_db()
    state.broker = get_broker()
    state.analyst = Analyst()
    state.bot = TradingBot(state.broker, state.analyst)
    await state.bot.start()
    await asyncio.sleep(5)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/status")
        j = r.json()
        print("GET /api/status ->", r.status_code, "mode=", j.get("mode"), "running=", j.get("bot", {}).get("running"))

        r = await c.get("/api/market/bars", params={"symbol": "AAPL", "timeframe": "5Min", "limit": 200})
        j = r.json()
        print("GET /api/market/bars ->", r.status_code, "candles=", len(j.get("candles", [])),
              "regime=", j.get("analysis", {}).get("regime"), "action=", j.get("analysis", {}).get("action"))

        r = await c.get("/api/market/depth", params={"symbol": "AAPL", "frames": 90})
        d = r.json()
        print("GET /api/market/depth ->", r.status_code, "levels=", len(d.get("cells", [])),
              "frames=", len(d.get("times", [])), "demo=", d.get("demo"))

        r = await c.post("/api/backtest", json={"symbol": "AAPL", "timeframe": "5Min", "limit": 300,
                                                "rr": 2.0, "atr_mult": 1.5, "min_conf": 0.5, "stride": 6})
        s = r.json().get("stats", {})
        print("POST /api/backtest ->", r.status_code, "trades=", s.get("num_trades"), "pnl=", s.get("total_pnl"))

        r = await c.post("/api/optimize", json={"symbol": "NVDA", "timeframe": "5Min", "limit": 300,
                                                "stride": 16, "folds": 3, "regime_method": "heuristic"})
        j = r.json()
        print("POST /api/optimize ->", r.status_code, "job=", j.get("job_id"))
        jid = j["job_id"]
        jj = {"status": "running"}
        for _ in range(120):
            await asyncio.sleep(1)
            jj = (await c.get(f"/api/optimize/{jid}")).json()
            if jj.get("status") != "running":
                break
        print("GET /api/optimize/{job} ->", jj.get("status"))
        if jj.get("status") == "done":
            sm = jj["result"].get("summary", {})
            print("   folds=", len(jj["result"].get("folds", [])), "WFE=", sm.get("walk_forward_efficiency"),
                  "PBO=", sm.get("pbo"), "verdict=", sm.get("verdict"))
        else:
            print("   ", jj)

    await state.bot.stop()
    await state.analyst.close()
    await state.broker.close()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    finally:
        # Terminate the ProcessPoolExecutor's child processes before a hard exit,
        # otherwise they are orphaned and linger (leak / CPU saturation).
        try:
            import app.server as _srv
            if getattr(_srv, "_opt_pool", None) is not None:
                _srv._opt_pool.shutdown(wait=True, cancel_futures=True)
        except Exception:
            pass
        sys.stdout.flush()
        os._exit(0)  # non-daemon threads keep the interpreter alive; force exit
