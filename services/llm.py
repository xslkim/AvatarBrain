from __future__ import annotations

import logging
import re
import asyncio
from threading import Thread
from typing import AsyncGenerator, Optional
from collections import deque

from config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self) -> None:
        self._ready = False
        self._error: Optional[str] = None
        self._provider = (settings.llm_provider or "openai").strip().lower()
        self._client = None
        self._model = (settings.llm_model or "").strip()
        self._base_url = (settings.llm_base_url or "").strip()
        self._local_model_path = (settings.llm_local_model_path or "").strip()
        self._device = "cpu"
        self._tokenizer = None
        self._local_model = None
        self._history: deque[dict] = deque(maxlen=12)  # 6 turns (user+assistant)
        self._system_prompt = (settings.llm_system_prompt or "").strip() or "请用中文口语化简短回复，1-2句。"

        if self._provider == "local":
            self._init_local_model()
        else:
            self._init_openai_client()

    def _init_openai_client(self) -> None:
        target_base_url = (settings.llm_base_url or "").strip()
        target_model = (settings.llm_model or "").strip()
        if not settings.llm_api_key or not target_base_url or not target_model:
            self._error = "LLM_API_KEY/LLM_BASE_URL/LLM_MODEL must be configured for openai mode"
            logger.warning(self._error)
            self._ready = False
            return
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=target_base_url,
                timeout=settings.llm_timeout,
            )
            self._base_url = target_base_url
            self._model = target_model
            self._ready = True
            self._error = None
        except Exception as exc:
            self._error = str(exc)
            self._ready = False
            logger.warning("LLM client init failed: %s", exc)

    def _init_local_model(self) -> None:
        if not self._local_model_path:
            self._error = "LLM_LOCAL_MODEL_PATH must be configured for local mode"
            self._ready = False
            logger.warning(self._error)
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            requested_device = (settings.llm_device or "auto").strip().lower()
            if requested_device == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = requested_device

            self._tokenizer = AutoTokenizer.from_pretrained(self._local_model_path, trust_remote_code=True)
            self._local_model = AutoModelForCausalLM.from_pretrained(
                self._local_model_path,
                dtype=torch.float16 if self._device == "cuda" else torch.float32,
                trust_remote_code=True,
            )
            self._local_model.to(self._device)
            self._local_model.eval()
            self._model = self._local_model_path
            self._base_url = ""
            self._ready = True
            self._error = None
        except Exception as exc:
            self._error = str(exc)
            self._ready = False
            logger.warning("Local LLM init failed: %s", exc)

    def switch_provider(self, provider: str) -> tuple[bool, str]:
        target = (provider or "").strip().lower()
        if target not in {"openai", "local"}:
            return False, "provider must be one of: openai, local"
        if target == self._provider:
            if target == "local" and not self._ready:
                self._init_local_model()
            elif target == "openai" and not self._ready:
                self._init_openai_client()
            if not self._ready:
                return False, self._error or f"{target} is not ready"
            return True, f"provider unchanged: {target}"

        prev_provider = self._provider
        if target == "local":
            self._init_local_model()
        else:
            self._init_openai_client()

        if not self._ready:
            failed_reason = self._error or f"switch to {target} failed"
            # Restore previous provider runtime state on switch failure.
            if prev_provider == "local":
                self._init_local_model()
            else:
                self._init_openai_client()
            self._provider = prev_provider
            return False, failed_reason

        self._provider = target
        self.clear_history()
        return True, f"switched to {target}"

    @staticmethod
    def _normalize_reply_text(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        cleaned = cleaned.replace("\r", "\n")
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.S | re.I)
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
        if self._provider == "local":
            if not self._ready:
                return
            async for delta in self._stream_reply_local(text):
                yield delta
            return

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

    async def _stream_reply_local(self, text: str) -> AsyncGenerator[str, None]:
        if not self._ready or self._local_model is None or self._tokenizer is None:
            return

        import torch
        from transformers import TextIteratorStreamer

        messages = [
            {"role": "system", "content": self._system_prompt},
            *list(self._history),
            {"role": "user", "content": text},
        ]
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            # Some templates don't expose `enable_thinking`.
            prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self._tokenizer([prompt], return_tensors="pt").to(self._device)
        streamer = TextIteratorStreamer(self._tokenizer, skip_prompt=True, skip_special_tokens=True)

        generation_error: dict[str, Exception] = {}
        generation_kwargs = {
            **model_inputs,
            "max_new_tokens": max(32, int(settings.llm_max_tokens)),
            "do_sample": False,  # Lower latency and more stable output for voice assistant use.
            "streamer": streamer,
        }

        def _run_generate() -> None:
            try:
                with torch.inference_mode():
                    self._local_model.generate(**generation_kwargs)
            except Exception as exc:  # pragma: no cover - runtime/model specific
                generation_error["error"] = exc

        thread = Thread(target=_run_generate, daemon=True)
        thread.start()

        accumulated = ""
        streamer_iter = iter(streamer)
        while True:
            token_text = await asyncio.to_thread(next, streamer_iter, None)
            if token_text is None:
                break
            if not token_text:
                continue
            accumulated += token_text
            yield token_text

        await asyncio.to_thread(thread.join)
        if "error" in generation_error:
            exc = generation_error["error"]
            self._error = str(exc)
            logger.warning("Local LLM generation failed: %s", exc)
            return

        normalized = self._normalize_reply_text(accumulated)
        if not normalized:
            return
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": normalized})

    @property
    def health(self) -> dict:
        return {
            "provider": self._provider,
            "ready": self._ready,
            "model": self._model,
            "base_url": self._base_url,
            "device": self._device,
            "history_items": len(self._history),
            "error": self._error,
        }

    def clear_history(self) -> None:
        self._history.clear()
