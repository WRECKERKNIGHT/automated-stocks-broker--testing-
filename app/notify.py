"""Watchdog notifications (Telegram / Discord / Slack / generic webhook).

The bot is fully autonomous, so the failure modes that matter are silent ones:
an API error storm, a lost data feed, or hitting the daily loss limit. This module
pings your phone when they happen so you never have to watch the screen.

Configure one of:
  NOTIFY_WEBHOOK_URL   full webhook / bot endpoint
  NOTIFY_KIND           auto | telegram | discord | slack | generic
  NOTIFY_TELEGRAM_CHAT  chat id (telegram only)

Failures to notify are swallowed - a broken notifier must never break trading.
"""
from __future__ import annotations

import httpx

from .config import settings


class Notifier:
    def __init__(self, url: str | None = None, kind: str | None = None,
                 telegram_chat: str | None = None) -> None:
        self.url = (url if url is not None else settings.notify_url).strip()
        self.kind = (kind if kind is not None else settings.notify_kind).strip().lower()
        self.telegram_chat = (telegram_chat if telegram_chat is not None
                              else settings.notify_telegram_chat).strip()
        self._client: httpx.AsyncClient | None = None
        self.last_error: str | None = None
        self.sent = 0

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _resolve_kind(self) -> str:
        if self.kind and self.kind != "auto":
            return self.kind
        u = self.url.lower()
        if "discord" in u:
            return "discord"
        if "telegram" in u or "api.telegram.org" in u:
            return "telegram"
        if "slack" in u or "hooks.slack" in u:
            return "slack"
        return "generic"

    def build_request(self, text: str) -> dict:
        """Pure payload builder (unit-testable, no network)."""
        kind = self._resolve_kind()
        if kind == "telegram":
            return {"method": "POST", "json": {"chat_id": self.telegram_chat,
                                               "text": text, "parse_mode": "HTML"}}
        if kind == "discord":
            return {"method": "POST", "json": {"content": text}}
        if kind == "slack":
            return {"method": "POST", "json": {"text": text}}
        return {"method": "POST", "json": {"text": text}}

    async def send(self, text: str, level: str = "info") -> bool:
        if not self.enabled:
            return False
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=6.0)
            req = self.build_request(f"[{level.upper()}] {text}")
            r = await self._client.request(req["method"], self.url, json=req["json"])
            self.sent += 1
            self.last_error = None
            return r.status_code < 400
        except Exception as e:  # noqa: BLE001
            self.last_error = repr(e)
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


def get_notifier() -> Notifier:
    return Notifier()
