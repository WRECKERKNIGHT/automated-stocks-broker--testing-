"""see.py - headless-Chrome UI inspector via the Chrome DevTools Protocol.

Why: lets a text-only agent "look at" the web dashboard by extracting the
rendered DOM state, computed styles, console errors and failed network
requests, plus saving a PNG screenshot for a human.

Usage:
    python tools/see.py [url]        # default http://127.0.0.1:8000/
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
PORT = 9333
_url_args = [a for a in sys.argv[1:] if a.startswith("http")]
URL = _url_args[0] if _url_args else "http://127.0.0.1:8000/"
SHOT = os.path.join(tempfile.gettempdir(), "opencode", "ui.png")

SECTIONS_JS = r'''
(async () => {
  const SECS = ["reasoning","scanner","research","ideas","portfolio","journal",
                "alerts","coach","library","pulse","equity","trades","daily","mind","today","backtest","wfo","depth"];
  const SLOW = {"scanner":10000,"research":5000,"ideas":40000,"portfolio":8000,
                "coach":2500,"library":2500,"pulse":12000};
  const out = [];
  for (const s of SECS) {
    const btn = document.querySelector('.railbtn[data-sec="' + s + '"]');
    if (!btn) { out.push({ sec: s, missing: true }); continue; }
    btn.click();
    await new Promise((r) => setTimeout(r, SLOW[s] || 1200));
    const p = document.getElementById("tab-" + s);
    const active = document.querySelector(".railbtn.active");
    out.push({
      sec: s,
      active: active ? active.dataset.sec : null,
      visible: p ? getComputedStyle(p).display !== "none" : false,
      title: (document.getElementById("dockTitle") || {}).textContent || "",
      chars: p ? (p.innerText || "").length : 0,
      text: p ? (p.innerText || "").replace(/\s+/g, " ").slice(0, 220) : "",
    });
  }
  return out;
})()
'''

REPORT_JS = r'''
(() => {
  const txt = (id) => { const e = document.getElementById(id);
    return e ? (e.innerText || e.textContent || "").trim().replace(/\s+/g, " ") : null; };
  const vis = (id) => { const e = document.getElementById(id); if (!e) return "missing";
    const c = getComputedStyle(e);
    return (c.display !== "none" && c.visibility !== "hidden" && c.opacity !== "0") ? "visible" : "hidden"; };
  const box = (sel) => { const e = document.querySelector(sel); if (!e) return null;
    const r = e.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y) }; };
  const cs = (sel, p) => { const e = document.querySelector(sel); return e ? getComputedStyle(e).getPropertyValue(p).trim() : null; };
  const root = document.documentElement;
  return {
    tone: root.dataset.tone,
    accentVar: cs(":root", "--accent") || cs("html", "--accent"),
    brandBg: cs(".brand", "color"),
    bodyBg: cs("body", "background-color"),
    fontFamily: cs("body", "font-family"),
    conn: txt("connState"),
    botState: txt("botState"),
    botButton: txt("botToggle"),
    mkt: txt("mkt"),
    equity: txt("equity"),
    daypnl: txt("daypnl"),
    npos: txt("npos"),
    banner: vis("mktBanner"),
    bannerText: (txt("mktBannerTitle") || "") + " " + (txt("mktBannerText") || ""),
    chartOverlay: vis("chartClosed"),
    chartOverlayText: txt("chartClosedText"),
    chartPrice: txt("chartPrice"),
    chartBox: box("#chart"),
    chartCanvas: document.querySelectorAll("#chart canvas").length,
    vpBox: box("#vpCanvas"),
    tickerCount: document.querySelectorAll("#tickerItems .bitem").length,
    signals: document.querySelectorAll("#signalBar .chip").length,
    posRows: document.querySelectorAll("#tab-positions tbody tr").length,
    activeTab: (document.querySelector(".tab.active") || {}).textContent || null,
    toasts: [...document.querySelectorAll(".toast")].map(x => x.innerText.replace(/\s+/g," ")),
    errorOverlay: !!document.getElementById("errOverlay"),
  };
})()
'''


async def main():
    try:
        import websockets
    except ImportError:
        print("need: pip install websockets"); return

    chrome = next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None)
    if not chrome:
        print("no chrome/edge found"); return

    tmp = tempfile.mkdtemp(prefix="cdp_")
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", f"--user-data-dir={tmp}",
         "--window-size=1680,1050", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ws_url = None
    for _ in range(60):
        try:
            data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
            ws_url = next((t["webSocketDebuggerUrl"] for t in data
                           if t.get("type") == "page"), None)
            if ws_url:
                break
        except Exception:
            pass
        await asyncio.sleep(0.25)
    if not ws_url:
        print("could not find chrome page target"); proc.kill(); return

    pending, console, errors, netfail = {}, [], [], []
    counter = 0
    try:
        async with websockets.connect(ws_url, max_size=None) as ws:
            async def send(method, params=None, timeout=25):
                nonlocal counter
                counter += 1
                mid = counter
                fut = asyncio.get_event_loop().create_future()
                pending[mid] = fut
                await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                return await asyncio.wait_for(fut, timeout=timeout)

            async def reader():
                async for raw in ws:
                    msg = json.loads(raw)
                    if "id" in msg and msg["id"] in pending:
                        fut = pending.pop(msg["id"])
                        if not fut.done():
                            fut.set_result(msg.get("result", msg.get("error")))
                        continue
                    m, p = msg.get("method"), msg.get("params", {})
                    if m == "Runtime.consoleAPICalled":
                        console.append({"type": p.get("type"),
                                        "args": [a.get("value") for a in p.get("args", [])]})
                    elif m == "Runtime.exceptionThrown":
                        d = p.get("exceptionDetails", {})
                        errors.append(d.get("exception", {}).get("description") or d.get("text"))
                    elif m == "Log.entryAdded":
                        e = p.get("entry", {})
                        if e.get("level") in ("error", "warning"):
                            errors.append(f"[{e.get('level')}] {e.get('text')}")
                    elif m == "Network.loadingFailed":
                        netfail.append(p.get("errorText"))

            rt = asyncio.create_task(reader())
            for m in ("Runtime.enable", "Log.enable", "Page.enable", "Network.enable"):
                await send(m)
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(9)
            res = await send("Runtime.evaluate",
                             {"expression": REPORT_JS, "returnByValue": True})
            sections = None
            if "--sections" in sys.argv:
                sres = await send("Runtime.evaluate",
                                  {"expression": SECTIONS_JS, "returnByValue": True,
                                   "awaitPromise": True}, timeout=200)
                sections = (sres.get("result", {}) or {}).get("value") if isinstance(sres, dict) else None
                await asyncio.sleep(1)
            shot = await send("Page.captureScreenshot", {"format": "png"})
            rt.cancel()

        report = (res.get("result", {}) or {}).get("value") if isinstance(res, dict) else None
        print(json.dumps({"report": report, "sections": sections, "console": console,
                          "errors": errors, "netfail": netfail}, indent=2))
        png = base64.b64decode(shot["data"]) if isinstance(shot, dict) and "data" in shot else b""
        os.makedirs(os.path.dirname(SHOT), exist_ok=True)
        with open(SHOT, "wb") as f:
            f.write(png)
        print(f"\nscreenshot -> {SHOT} ({len(png)} bytes)")
    finally:
        proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
