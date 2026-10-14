"""LLM analyst - the 'hybrid' narrative layer.

The deterministic quant engine decides *what* to trade. This layer reads the
news flow and market context and produces a sentiment/bias score + a plain
English brief that (a) nudges the signal aggregation and (b) is shown on the
dashboard so every decision is explainable.

Providers: none (lexicon) | ollama | openai | anthropic.
Always degrades gracefully to the lexicon scorer, so the bot never blocks.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any

import httpx

from .config import settings
from . import knowledge

_POS = {
    "beat", "beats", "surge", "surges", "rally", "soar", "soars", "record", "upgrade",
    "upgrades", "outperform", "raises", "raised", "guidance", "buyback", "growth",
    "profit", "bullish", "strong", "wins", "win", "contract", "partnership", "expands",
    "breakthrough", "approval", "approved", "dividend", "momentum", "optimistic", "tops",
}
_NEG = {
    "miss", "misses", "plunge", "plunges", "crash", "slump", "downgrade", "downgrades",
    "underperform", "cuts", "cut", "warns", "warning", "weak", "loss", "losses", "bearish",
    "probe", "investigation", "lawsuit", "fraud", "recall", "layoffs", "bankruptcy",
    "default", "selloff", "concern", "concerns", "slashes", "halts", "delays", "risk",
}
_STRONG = {"massive", "huge", "significantly", "sharply", "surges", "plunges"}


def lexicon_sentiment(text: str) -> float:
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    strong = sum(1 for w in words if w in _STRONG)
    raw = (pos - neg) / max(1, math_sqrt_words(len(words)))
    raw *= 1 + 0.3 * strong
    return float(max(-1.0, min(1.0, raw * 1.6)))


def math_sqrt_words(n: int) -> float:
    return max(3.0, n ** 0.5)


class Analyst:
    def __init__(self) -> None:
        self.provider = settings.llm_provider if settings.llm_provider in ("ollama", "openai", "anthropic") else "none"
        self._client = httpx.AsyncClient(timeout=25.0)
        self._cache: dict[str, dict] = {}
        self._last_call = 0.0
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self.provider != "none"

    # ------------------------------------------------------------------
    async def score_news(self, items: list[dict]) -> list[dict]:
        """Enrich news items with a sentiment score in [-1, 1] and a tag."""
        # demo items already carry a seeded sentiment - honour it
        out: list[dict] = []
        to_llm: list[dict] = []
        for it in items:
            if "_seed_sent" in it:
                it = dict(it)
                it["sentiment"] = float(it["_seed_sent"])
                it["summary"] = it.get("summary") or it.get("headline", "")
                out.append(it)
            else:
                it = dict(it)
                it["sentiment"] = lexicon_sentiment(it.get("headline", "") + " " + it.get("summary", ""))
                it["summary"] = it.get("summary") or it.get("headline", "")
                out.append(it)
                if self.enabled:
                    to_llm.append(it)
        if self.enabled and to_llm:
            try:
                scores = await self._llm_score_batch(to_llm)
                for it in out:
                    key = self._key(it.get("headline", ""))
                    if key in scores:
                        it["sentiment"] = scores[key]
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
        return out

    def _key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:16]

    async def _llm_score_batch(self, items: list[dict]) -> dict[str, float]:
        headlines = [it.get("headline", "")[:200] for it in items[:15]]
        prompt = (
            "You are a senior equity market analyst. For each headline, rate market impact "
            "sentiment from -1.0 (very bearish) to +1.0 (very bullish). Respond ONLY as a JSON "
            "array of objects with keys 'i' (index) and 's' (score).\n\n"
            + json.dumps(headlines)
        )
        text = await self._complete(prompt)
        scores: dict[str, float] = {}
        try:
            arr = json.loads(_extract_json(text))
            for row in arr:
                i = int(row.get("i", -1))
                if 0 <= i < len(items):
                    scores[self._key(items[i].get("headline", ""))] = float(max(-1, min(1, row.get("s", 0))))
        except Exception:
            # fall back to per-line parse
            nums = re.findall(r"-?\d+\.?\d*", text)
            for i, n in enumerate(nums[:len(items)]):
                scores[self._key(items[i].get("headline", ""))] = float(max(-1, min(1, float(n))))
        return scores

    async def market_brief(self, symbol: str, context: dict, headlines: list[str]) -> dict:
        """Narrative risk read on a specific setup. Returns {bias, brief}."""
        if not self.enabled or not headlines:
            return {"bias": 0.0, "brief": "", "provider": self.provider}
        try:
            grounding = knowledge.context_block(context or {}, limit=6)
        except Exception:  # noqa: BLE001
            grounding = ""
        try:
            from . import elite
            grounding = (grounding + "\n" + elite.context_block(limit=3)).strip()
        except Exception:  # noqa: BLE001
            pass
        prompt = (
            f"You are a ruthless risk manager reviewing a {symbol} setup. "
            f"Context: {json.dumps(context)}\nRecent headlines: {json.dumps(headlines[:8])}\n"
            + (grounding + "\n" if grounding else "")
            + "In <=50 words, state whether the news flow supports or contradicts the setup and the "
            "key risk. End with a JSON line: {\"bias\": <-1..1>}."
        )
        try:
            text = await self._complete(prompt)
            bias = 0.0
            m = re.search(r'"bias"\s*:\s*(-?\d+\.?\d*)', text)
            if m:
                bias = float(max(-1, min(1, float(m.group(1)))))
            brief = re.sub(r'\{.*"bias".*\}', "", text).strip()
            return {"bias": bias, "brief": brief[:400], "provider": self.provider}
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return {"bias": 0.0, "brief": "", "provider": self.provider}

    # ------------------------------------------------------------------
    async def _complete(self, prompt: str) -> str:
        # small throttle so a fast loop can't hammer a local model
        gap = time.time() - self._last_call
        if gap < 1.5:
            await asyncio.sleep(1.5 - gap)
        self._last_call = time.time()

        if self.provider == "ollama":
            r = await self._client.post(
                settings.ollama_host.rstrip("/") + "/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
            )
            r.raise_for_status()
            return r.json().get("response", "")
        if self.provider == "openai":
            r = await self._client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_key}"},
                json={"model": settings.openai_model,
                      "messages": [{"role": "user", "content": prompt}],
                      "response_format": {"type": "json_object"}, "temperature": 0.2},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        if self.provider == "anthropic":
            r = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.anthropic_key, "anthropic-version": "2023-06-01"},
                json={"model": settings.anthropic_model, "max_tokens": 512,
                      "messages": [{"role": "user", "content": prompt}]},
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        return ""

    async def close(self) -> None:
        await self._client.aclose()


def _extract_json(text: str) -> str:
    m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    return m.group(1) if m else text
