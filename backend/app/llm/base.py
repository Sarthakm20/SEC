"""Provider-agnostic LLM interface + token/cost accounting (Recommendations §5.1–5.2)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol

from app.models import Usage

# USD per 1M tokens (input, output). Prices change — override with LLM_PRICE_INPUT / LLM_PRICE_OUTPUT.
PRICES: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
    # Gemini (Google AI Studio paid tier; free tier is $0)
    "gemini-3.8-flash": (0.10, 0.40),
    "gemini-3.5-flash-lite": (0.05, 0.20),
    "gemini-3.7-flash": (0.10, 0.40),
    "gemini-4-argon": (2.00, 8.00),
    "gemini-2.5-flash": (0.10, 0.40),
    "gemini-2.0-flash": (0.10, 0.40),
    # OpenAI
    "gpt-4.1-mini": (0.15, 0.60),
    "gpt-4.1": (2.50, 10.00),
}


class LLMError(RuntimeError):
    """Provider failure after the SDK's own retries (rate limit, outage, auth, refusal...)."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    stop_reason: str | None = None


class LLM(Protocol):
    provider: str
    model: str
    offline: bool

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 4000,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class UsageTracker:
    """Accumulates per-request usage; one tracker per answered question."""

    def __init__(self, price_override: tuple[float, float] | None = None) -> None:
        self.usage = Usage()
        self._lock = threading.Lock()
        self._override = price_override

    def record_llm(self, resp: LLMResponse) -> None:
        with self._lock:
            u = self.usage
            u.provider, u.model = resp.provider, resp.model
            u.input_tokens += resp.input_tokens
            u.output_tokens += resp.output_tokens
            u.llm_calls += 1
            pin, pout = self._override or PRICES.get(resp.model, (0.0, 0.0))
            u.estimated_cost_usd = round(
                u.estimated_cost_usd + resp.input_tokens / 1e6 * pin + resp.output_tokens / 1e6 * pout, 6
            )

    def record_embedding(self, n: int = 1) -> None:
        with self._lock:
            self.usage.embedding_calls += n

    def record_rerank(self, n: int = 1) -> None:
        with self._lock:
            self.usage.rerank_calls += n
