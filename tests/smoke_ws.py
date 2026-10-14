import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import os

import websockets


async def main():
    port = os.getenv("WSPORT", "8000")
    uri = f"ws://127.0.0.1:{port}/ws"
    got = {"snapshot": 0, "tape": 0}
    async with websockets.connect(uri) as ws:
        for _ in range(12):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            t = m.get("type")
            if t in got:
                got[t] += 1
                if t == "snapshot" and got[t] == 1:
                    print("snapshot keys:", sorted(m["data"].keys()))
                if t == "tape" and got[t] == 1:
                    b = m["data"]["book"]["AAPL"]
                    print("tape AAPL:", b["bid"], b["ask"], "prints", len(b["trades"]))
    print("received:", got)


asyncio.run(main())
