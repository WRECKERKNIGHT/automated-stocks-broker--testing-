"""AI Trader - desktop launcher.

Starts the FastAPI server (run.py) as a background process, waits for it to
come up on the configured port, then opens the dashboard in a chromeless
Chrome/Edge app window using a dedicated profile directory (.appdata) so it
looks and behaves like a native desktop app.

Usage:
    python launch.py            # server + app window
    python launch.py --browser  # server + normal browser tab
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPDATA_DIR = HERE / ".appdata"

sys.path.insert(0, str(HERE))
try:
    from app.config import settings  # noqa: E402
    HOST, PORT = settings.host, settings.port
except Exception:  # noqa: BLE001
    HOST, PORT = "127.0.0.1", 8000

URL = f"http://{HOST}:{PORT}/"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_for_server(timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(HOST, PORT):
            return True
        time.sleep(0.4)
    return False


def _find_browser() -> str | None:
    for path in CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    return None


def start_server() -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [sys.executable, str(HERE / "run.py")],
        cwd=str(HERE),
        creationflags=creationflags,
    )


def open_app_window(browser: str | None, plain: bool) -> None:
    if browser and not plain:
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                browser,
                f"--app={URL}",
                f"--user-data-dir={APPDATA_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1440,900",
            ],
            cwd=str(HERE),
        )
    else:
        import webbrowser

        webbrowser.open(URL)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Trader desktop launcher")
    parser.add_argument("--browser", action="store_true", help="use the default browser instead of an app window")
    args = parser.parse_args()

    if _port_open(HOST, PORT):
        print(f"Server already running at {URL}")
    else:
        print("Starting AI Trader server ...")
        start_server()
        if _wait_for_server():
            print(f"Server up at {URL}")
        else:
            print("Warning: server did not respond in time; opening anyway.")

    browser = _find_browser()
    open_app_window(browser, args.browser)
    print("Dashboard launched. Close this window to stop the launcher (server keeps running).")


if __name__ == "__main__":
    main()
