import os
import sys
import time
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import backtest, wfo
from app.alpaca import get_broker


async def main():
    broker = get_broker()
    df = await broker.get_bars("NVDA", "5Min", 420)
    print("bars:", len(df), "mode:", broker.__class__.__name__)

    t0 = time.time()
    plan = backtest.build_plan("NVDA", df, stride=10, regime_method="heuristic")
    print(f"plan entries: {len(plan)} in {time.time()-t0:.2f}s")

    t0 = time.time()
    res = wfo.walk_forward("NVDA", df, n_folds=4, stride=10,
                           regime_method="heuristic", min_trades=2)
    print(f"wfo total: {time.time()-t0:.2f}s")
    s = res.get("summary", {})
    print("folds:", len(res.get("folds", [])))
    for f in res.get("folds", []):
        print(f"  fold {f['fold']}: IS exp={f['is_expectancy']} ({f['is_trades']}t) "
              f"-> OOS exp={f['oos_expectancy']} ({f['oos_trades']}t) pnl={f['oos_pnl']}")
    print("mean IS exp:", s.get("mean_is_expectancy"))
    print("mean OOS exp:", s.get("mean_oos_expectancy"))
    print("WFE:", s.get("walk_forward_efficiency"))
    print("PBO:", s.get("pbo"), "over", s.get("pbo_combos"), "combos")
    print("verdict:", s.get("verdict"))


asyncio.run(main())