"""AI Trader - server entry point.

Serves the FastAPI app (REST API + WebSocket + static dashboard) with uvicorn.
Bot auto-start and all wiring are handled by the app lifespan in app/server.py.

Usage:
    python run.py            # serve on settings.host : settings.port
"""
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app.config import settings  # noqa: E402
from app.server import app  # noqa: E402


def main() -> None:
    print(f"AI Trader - mode={settings.mode} - http://{settings.host}:{settings.port}")
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
