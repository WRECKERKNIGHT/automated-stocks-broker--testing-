import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time

from app import regime, storage
from app.alpaca import get_broker
from app.analyst import Analyst
from app.bot import TradingBot


async def main():
    storage.init_db()
    broker = get_broker()
    analyst = Analyst()

    # ---- HMM regime (fit runs in background; poll until ready) ----
    df = await broker.get_bars("NVDA", "5Min", 300)
    t0 = time.time()
    r1 = regime.classify(df, method="hmm", symbol="NVDA")
    for _ in range(40):
        if r1.get("hmm_status") == "ready":
            break
        await asyncio.sleep(0.25)
        r1 = regime.classify(df, method="hmm", symbol="NVDA")
    r2 = regime.classify(df, method="hybrid", symbol="NVDA")
    print(f"HMM ready in {time.time()-t0:.2f}s -> state={r1.get('state')} "
          f"regime={r1['regime']} probs={r1.get('state_probs')} loglik={r1.get('loglik')}")
    print(f"HYBRID -> {r2['regime']} (heuristic={r2.get('heuristic_regime')})")
    t1 = time.time()
    regime.classify(df, method="hmm", symbol="NVDA")
    print(f"HMM cached call: {time.time()-t1:.4f}s")

    # ---- live tape (demo) ----
    bot = TradingBot(broker, analyst)
    await bot.tape.start()
    await asyncio.sleep(3.5)
    snap = bot.tape.snapshot()
    s = snap["book"]["AAPL"]
    print(f"TAPE demo={snap['demo']} AAPL last={s['last']} bid={s['bid']}x{s['bid_size']} "
          f"ask={s['ask']}x{s['ask_size']} spread={s['spread']} imb={s['imbalance']} "
          f"cumD={s['cum_delta']} prints={len(s['trades'])}")
    print("tape symbols:", list(snap["book"].keys()))
    await bot.tape.stop()
    await analyst.close()
    await broker.close()


asyncio.run(main())
