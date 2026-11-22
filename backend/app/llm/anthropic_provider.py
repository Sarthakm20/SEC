"""Anthropic (Claude) adapter using the official SDK."""

from __future__ import annotations

from typing import Any

import anthropic

from app.llm.base import LLMError, LLMResponse

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicLLM:
    provider = "anthropic"
    offline = False

    def __init__(self, model: str | None = None, api_key: str | None = None, effort: str = "medium", timeout: float = 120.0) -> None:
        self.model = model or DEFAULT_MODEL
        self.effort = effort
        # api_key=None lets the SDK resolve ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login` profile
        self._client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout, max_retries=2)

    def complete(self, system: str, user: str, max_tokens: int = 4000, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        output_config: dict[str, Any] = {"effort": self.effort}
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        try:
            resp = self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                # server-side fallback: a safety-classifier decline is re-run on a recommended model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit: {exc.message}", retryable=True) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic authentication failed — check ANTHROPIC_API_KEY") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Anthropic bad request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API", retryable=True) from exc

        if resp.stop_reason == "refusal":
            category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise LLMError(f"model declined the request (category: {category})")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=resp.model,
            provider=self.provider,
            stop_reason=resp.stop_reason,
        )
