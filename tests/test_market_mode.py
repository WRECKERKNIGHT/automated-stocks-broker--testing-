"""Smoke test for market-mode plumbing (offline).

Exercises config helpers, FX classification, the market context in storage
and broker dispatch without touching the network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, storage, universe
from app.alpaca import get_broker


def main() -> int:
    s = config.settings
    assert s.market() in ("stocks", "forex")
    assert s.watchlist_for("forex"), "forex watchlist must be non-empty"
    assert s.cross_asset_for("forex"), "forex cross-assets must be non-empty"
    for sym, group in (("EUR_USD", "Major"), ("GBP_JPY", "Minor"),
                       ("XAU_USD", "Metal"), ("USD_TRY", "Exotic")):
        got = universe.classify(sym)
        assert got == group, (sym, got, group)
    assert universe.classify("AAPL") == "Technology"
    keep = storage.get_market()
    storage.set_market("forex")
    assert storage.get_market() == "forex"
    storage.set_market(keep)
    fx = get_broker("forex")
    assert fx.mode == "FOREX" and fx.synthetic_tape is True
    print("market-mode smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
