"""Smoke test for the market-data features: universe, scanner, research, ideas,
analytics, alerts, journal. Runs against whatever broker is configured."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import alerts as alerts_mod
from app import analytics, ideas, research, scanner, storage, universe
from app.alpaca import get_broker


async def main():
    storage.init_db()
    broker = get_broker()
    print("mode:", broker.mode)

    n = await universe.ensure_universe(broker, force=True)
    print("universe loaded:", n, "| sectors:", list(universe.sector_breakdown().items())[:6])

    mv = await scanner.movers(broker, top=5)
    print("movers gainers:", [m["symbol"] for m in mv["gainers"]])
    print("movers losers :", [m["symbol"] for m in mv["losers"]])

    ma = await scanner.most_active(broker, top=5)
    print("most active  :", [(m["symbol"], m["volume"]) for m in ma])

    sc = await scanner.scan(broker, universe_syms=None, watchlist=["AAPL", "MSFT", "NVDA"],
                            full=False, filters={"min_price": 5, "min_volume": 100000},
                            sort="change_pct", limit=8)
    print(f"scan: scanned={sc['scanned']} with_data={sc['with_data']} matched={sc['total_matched']}")
    for r in sc["rows"][:5]:
        print(f"   {r['symbol']:6} {r['price']:>9.2f} {r['change_pct']:+7.2f}% "
              f"vol={r['volume']:>12,} rsi={r.get('rsi')} {r['sector']}")

    res = await research.research(broker, "AAPL", sentiment=0.1)
    print("research AAPL:", res.get("rating"), res.get("score"),
          "| 52w", res["stats"]["low_52w"], "-", res["stats"]["high_52w"],
          "| rsi", res["stats"]["rsi"], "| thesis", len(res["thesis"]), "risks", len(res["risks"]))

    idl = await ideas.ideas(broker, candidates=[r["symbol"] for r in sc["rows"]] + ["AAPL", "TSLA"],
                            sentiment={"AAPL": 0.2}, market={"bias": 0.1, "label": "UP"})
    print("ideas:", idl["total"], "|", idl["briefing"]["headline"][:90])
    for i in idl["ideas"][:4]:
        print(f"   {i['symbol']:6} {i['action']:4} conf={i['confidence']:.2f} "
              f"entry={i['entry']} stop={i['stop']} tgt={i['target']} sig={i['signals']}")

    account = await broker.get_account()
    positions = await broker.get_positions()
    an = await analytics.portfolio_analytics(broker, account, positions, market={"bias": 0.1, "label": "UP"})
    print("analytics: gross_pct=%.1f cash_pct=%.1f hhi=%.3f trades=%d pf=%s dd_pct=%s" % (
        an["gross_pct"], an["cash_pct"], an["concentration"]["hhi"],
        an["trade_stats"]["trades"], an["trade_stats"]["profit_factor"],
        an["equity_metrics"]["max_drawdown_pct"]))

    # alerts: one impossible, one guaranteed
    pid = storage.add_alert({"symbol": "AAPL", "kind": "price", "op": ">", "value": 999999, "note": "impossible"})
    aid2 = storage.add_alert({"symbol": "AAPL", "kind": "price", "op": "<", "value": 999999, "note": "will fire"})
    fired = await alerts_mod.evaluate(broker)
    print("alert evaluation fired:", [(f["symbol"], f["note"]) for f in fired])
    storage.delete_alert(pid)
    storage.delete_alert(aid2)

    jid = storage.add_journal({"symbol": "AAPL", "side": "long", "pnl": 12.5,
                               "tags": ["test"], "note": "smoke"})
    print("journal entries:", len(storage.recent_journal()))
    storage.delete_journal(jid)
    print("journal after delete:", len(storage.recent_journal()))

    await broker.close()
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
