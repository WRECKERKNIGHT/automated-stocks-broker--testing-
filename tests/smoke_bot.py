import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio, json, time

from app import storage, strategy
from app.alpaca import get_broker
from app.analyst import Analyst
from app.bot import TradingBot


async def main():
    storage.init_db()
    broker = get_broker()
    analyst = Analyst()
    bot = TradingBot(broker, analyst)
    print("mode:", broker.mode)

    # bars sanity
    df = await broker.get_bars("AAPL", "5Min", 260)
    print("bars:", len(df), "last close:", round(float(df['close'].iloc[-1]), 2))

    # strategy sanity
    ctx = strategy.analyze("AAPL", df, news_sentiment=0.2)
    print("action:", ctx["action"], "conf:", ctx["confidence"], "regime:", ctx["regime"])
    print("signals:", [s["name"] for s in ctx["signals"]])

    # run a few scans
    for i in range(6):
        snap = await bot.scan_once()
        print(f"scan {i}: equity={snap['account']['equity']} positions={len(snap['positions'])} "
              f"decisions={len(snap['decisions'])} news={len(snap['news'])} log={snap['log'][:1]}")
        await asyncio.sleep(0.5)
    print("bot log head:", json.dumps(snap["log"][:5], indent=0))
    await analyst.close()
    await broker.close()


asyncio.run(main())
