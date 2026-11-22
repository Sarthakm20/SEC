"""OpenAI-compatible adapter: OpenAI, Google Gemini (OpenAI-compatible endpoint) and local Ollama.

Model defaults:
  - OpenAI: gpt-4.1-mini
  - Gemini: gemini-3.8-flash (free tier on Google AI Studio; set LLM_MODEL to a current free model)
  - Ollama: llama3.1

Free-tier handling (Gemini): calls are paced client-side (LLM_MIN_INTERVAL_SECONDS, default 6 s = 10 req/min),
per-minute 429s wait for the server's suggested retry delay, and an exhausted *daily* quota fails fast so
callers fall back to the deterministic answer instead of stalling.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from app.llm.base import LLMError, LLMResponse

PROVIDERS: dict[str, dict[str, str | None]] = {
    "openai": {"base_url": None, "default_model": "gpt-4.1-mini"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-3.8-flash"},
    "ollama": {"base_url": "http://localhost:11434/v1", "default_model": "llama3.1"},
}


# seconds between calls when LLM_MIN_INTERVAL_SECONDS is not set (free tiers are limited per minute)
DEFAULT_MIN_INTERVAL = {"gemini": 6.0, "openai": 0.0, "ollama": 0.0}
_DAILY_QUOTA = re.compile(r"per\s*day|perday|daily", re.I)
_RETRY_IN = re.compile(r"retry(?:\s+in|Delay\W+)\s*\W*([\d.]+)\s*s", re.I)

_pace_lock = threading.Lock()
_last_call: dict[str, float] = {}


def _retry_delay(exc: Exception, fallback: float) -> float:
    """Gemini puts the wait in the error body ("retryDelay": "37s" / "Please retry in 37.2s")."""
    m = _RETRY_IN.search(str(getattr(exc, "body", "") or "") + " " + str(exc))
    return min(float(m.group(1)) + 1.0, 90.0) if m else fallback


def _detail(exc: Exception) -> str:
    """The provider's own error text (e.g. "model not found", "overloaded"), not just the status code."""
    body = getattr(exc, "body", None)
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        err = body.get("error", body)
        msg = err.get("message") if isinstance(err, dict) else str(err)
        if msg:
            return str(msg)[:300]
    return str(getattr(exc, "message", exc))[:300]


class OpenAICompatLLM:
    offline = False

    def __init__(
        self,
        provider: str,
        model: str | None,
        api_key: str | None,
        base_url: str | None = None,
        timeout: float = 120.0,
        min_interval: float | None = None,
        max_rate_limit_retries: int = 3,
    ) -> None:
        from openai import OpenAI

        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        cfg = PROVIDERS[provider]
        self.provider = provider
        self.model = model or str(cfg["default_model"])
        self.min_interval = DEFAULT_MIN_INTERVAL.get(provider, 0.0) if min_interval is None else max(0.0, min_interval)
        self.max_rate_limit_retries = max_rate_limit_retries

        if provider == "gemini" and not api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add GEMINI_API_KEY to your D:\\SEC\\.env file.", retryable=False)
        if provider == "openai" and not api_key:
            raise LLMError("OPENAI_API_KEY is not set. Add OPENAI_API_KEY to your D:\\SEC\\.env file.", retryable=False)

        self._client = OpenAI(
            api_key=api_key or ("ollama" if provider == "ollama" else None),
            base_url=base_url or cfg["base_url"],
            timeout=timeout,
            max_retries=0,  # retries are handled below, with free-tier aware waits
        )

    def _pace(self) -> None:
        """Space calls at least `min_interval` apart (shared by all instances of this provider in the process)."""
        if self.min_interval <= 0:
            return
        with _pace_lock:
            wait = _last_call.get(self.provider, 0.0) + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_call[self.provider] = time.monotonic()

    def complete(self, system: str, user: str, max_tokens: int = 4000, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        import openai

        kwargs: dict[str, Any] = {}
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
            user = user + "\n\nRespond with a single raw JSON object (no markdown code blocks) matching this schema:\n" + json.dumps(json_schema)

        # Gemini and Ollama endpoints expect `max_tokens`. Only newer OpenAI models (o1/o3) mandate `max_completion_tokens`.
        if self.provider == "openai" and self.model.startswith(("o1", "o3")):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        resp = None
        attempts = self.max_rate_limit_retries + 1
        for attempt in range(attempts):
            self._pace()
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    **kwargs,
                )
                break
            except openai.RateLimitError as exc:
                if _DAILY_QUOTA.search(str(getattr(exc, "body", "") or "") + " " + str(exc)):
                    # waiting will not help until the quota resets; fail fast so the caller falls back
                    raise LLMError(f"{self.provider} daily quota exhausted for {self.model}; try tomorrow or use --limit", retryable=False) from exc
                if attempt < attempts - 1:
                    time.sleep(_retry_delay(exc, fallback=15.0 * (attempt + 1)))
                    continue
                raise LLMError(f"{self.provider} rate limit: still limited after {attempts} attempts", retryable=True) from exc
            except openai.APIStatusError as exc:
                if exc.status_code >= 500 and attempt < attempts - 1:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise LLMError(f"{self.provider} API error {exc.status_code} ({self.model}): {_detail(exc)}", retryable=exc.status_code >= 500) from exc
            except openai.APIConnectionError as exc:
                if attempt < attempts - 1:
                    time.sleep(2.0)
                    continue
                raise LLMError(f"could not reach {self.provider}", retryable=True) from exc

        if resp is None or not resp.choices:
            raise LLMError(f"{self.provider} returned an empty response")

        choice = resp.choices[0]
        usage = resp.usage
        raw_text = choice.message.content or ""

        # Strip markdown fences if JSON was requested
        if json_schema is not None and raw_text.strip().startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
            raw_text = re.sub(r"\s*```$", "", cleaned)

        return LLMResponse(
            text=raw_text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=resp.model or self.model,
            provider=self.provider,
            stop_reason=choice.finish_reason,
        )
