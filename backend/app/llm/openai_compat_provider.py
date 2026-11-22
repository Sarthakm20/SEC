"""OpenAI-compatible adapter: OpenAI, Google Gemini (OpenAI-compatible endpoint) and local Ollama.

Model defaults:
  - OpenAI: gpt-4.1-mini
  - Gemini: gemini-2.0-flash (free tier on Google AI Studio)
  - Ollama: llama3.1
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.llm.base import LLMError, LLMResponse

PROVIDERS: dict[str, dict[str, str | None]] = {
    "openai": {"base_url": None, "default_model": "gpt-4.1-mini"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-3.8-flash"},
    "ollama": {"base_url": "http://localhost:11434/v1", "default_model": "llama3.1"},
}


class OpenAICompatLLM:
    offline = False

    def __init__(self, provider: str, model: str | None, api_key: str | None, base_url: str | None = None, timeout: float = 120.0) -> None:
        from openai import OpenAI

        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        cfg = PROVIDERS[provider]
        self.provider = provider
        self.model = model or str(cfg["default_model"])

        if provider == "gemini" and not api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add GEMINI_API_KEY to your D:\\SEC\\.env file.", retryable=False)
        if provider == "openai" and not api_key:
            raise LLMError("OPENAI_API_KEY is not set. Add OPENAI_API_KEY to your D:\\SEC\\.env file.", retryable=False)

        self._client = OpenAI(
            api_key=api_key or ("ollama" if provider == "ollama" else None),
            base_url=base_url or cfg["base_url"],
            timeout=timeout,
            max_retries=2,
        )

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

        # Handle rate limits with backoff for free tiers (especially Gemini 15 RPM)
        max_attempts = 3
        backoff_delay = 2.0
        resp = None

        for attempt in range(max_attempts):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    **kwargs,
                )
                break
            except openai.RateLimitError as exc:
                if attempt < max_attempts - 1:
                    time.sleep(backoff_delay)
                    backoff_delay *= 2
                    continue
                raise LLMError(f"{self.provider} rate limit (quota exhausted or too many requests)", retryable=True) from exc
            except openai.APIStatusError as exc:
                raise LLMError(f"{self.provider} API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500) from exc
            except openai.APIConnectionError as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
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
