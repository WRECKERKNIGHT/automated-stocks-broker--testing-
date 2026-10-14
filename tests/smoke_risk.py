"""Smoke test: risk overlays (volatility dampener) + watchdog notifier payloads."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.notify import Notifier
from app.risk import RiskLimits, position_size
from app import strategy


def main() -> None:
    limits = RiskLimits()

    base = position_size(100_000, 100.0, 99.0, risk_pct=0.01, kelly_f=0.1, max_position_pct=0.2)
    print("base size:", base)
    assert base["qty"] > 0

    ctx = {"action": "BUY", "direction": 1, "price": 100.0, "stop": 99.0, "entry": 100.0,
           "target": 102.0, "rr": 2.0, "features": {"atr_pct": 1.0}}
    strategy.size_decision(ctx, 100_000, limits, 0.55, 2.0)
    hot_qty = ctx["sizing"]["qty"]
    print("normal vol qty:", hot_qty, "dampen", ctx["sizing"]["vol_dampen"])
    assert ctx["sizing"]["vol_dampen"] == 1.0

    ctx2 = {"action": "BUY", "direction": 1, "price": 100.0, "stop": 99.0, "entry": 100.0,
            "target": 102.0, "rr": 2.0, "features": {"atr_pct": 3.0}}
    strategy.size_decision(ctx2, 100_000, limits, 0.55, 2.0)
    print("hot vol qty:", ctx2["sizing"]["qty"], "dampen", ctx2["sizing"]["vol_dampen"])
    assert ctx2["sizing"]["vol_dampen"] == 0.5
    assert ctx2["sizing"]["qty"] <= hot_qty

    ctx3 = {"action": "BUY", "direction": 1, "price": 100.0, "stop": 99.0, "entry": 100.0,
            "target": 102.0, "rr": 2.0, "features": {"atr_pct": 6.0}}
    strategy.size_decision(ctx3, 100_000, limits, 0.55, 2.0)
    print("extreme vol qty:", ctx3["sizing"]["qty"], "dampen", ctx3["sizing"]["vol_dampen"])
    assert ctx3["sizing"]["qty"] == 0

    for kind, url in (("telegram", "https://api.telegram.org/botX/sendMessage"),
                      ("discord", "https://discord.com/api/webhooks/1/2"),
                      ("slack", "https://hooks.slack.com/services/x"),
                      ("generic", "https://example.com/hook")):
        n = Notifier(url=url, kind=kind, telegram_chat="123")
        req = n.build_request("hello")
        print(kind, "->", req["json"])
        if kind == "telegram":
            assert req["json"]["chat_id"] == "123" and req["json"]["text"] == "hello"
        elif kind == "discord":
            assert req["json"]["content"] == "hello"
        else:
            assert req["json"]["text"] == "hello"

    auto = Notifier(url="https://discord.com/api/webhooks/1/2", kind="auto")
    assert auto._resolve_kind() == "discord"
    assert Notifier(url="", kind="auto").enabled is False
    print("ALL RISK/NOTIFY CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
