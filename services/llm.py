from __future__ import annotations

import logging
import re
from typing import AsyncGenerator, Optional
from collections import deque

from config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self) -> None:
        self._ready = False
        self._error: Optional[str] = None
        self._client = None
        self._model = (settings.llm_model or "").strip()
        self._base_url = (settings.llm_base_url or "").strip()
        self._history: deque[dict] = deque(maxlen=12)  # 6 turns (user+assistant)
        self._system_prompt = (settings.llm_system_prompt or "").strip() or "请用中文口语化简短回复，1-2句。"

        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=self._base_url,
                timeout=settings.llm_timeout,
            )
            self._ready = True
            self._error = None
        except Exception as exc:
            self._error = str(exc)
            logger.warning("LLM client init failed: %s", exc)

    @staticmethod
    def _normalize_reply_text(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        cleaned = cleaned.replace("\r", "\n")
        cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.S)
        cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
        cleaned = re.sub(r"\s*([，。！？；：、,.!?;:])\s*", r"\1", cleaned)
        cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
        cleaned = re.sub(r"\n+", " ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    async def stream_reply(self, text: str) -> AsyncGenerator[str, None]:
        """Stream LLM response tokens. Saves normalized reply to history after completion."""
        if not self._ready or self._client is None:
            return

        accumulated = ""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    *list(self._history),
                    {"role": "user", "content": text},
                ],
                max_tokens=settings.llm_max_tokens,
                temperature=max(0.1, min(1.2, settings.llm_temperature)),
                stream=True,
            )
            async for chunk in response:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    accumulated += delta
                    yield delta
        except Exception as exc:
            self._error = str(exc)
            logger.warning("LLM stream failed: %s", exc)
            return

        normalized = self._normalize_reply_text(accumulated)
        if normalized:
            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": normalized})

    @property
    def health(self) -> dict:
        return {
            "ready": self._ready,
            "model": self._model,
            "base_url": self._base_url,
            "history_items": len(self._history),
            "error": self._error,
        }

    def clear_history(self) -> None:
        self._history.clear()
