"""Provider selection. `auto` picks the first configured cloud provider, else the offline synthesizer."""

from __future__ import annotations

import os
from typing import Any

from app.config import Settings, get_settings
from app.llm.base import LLM, LLMResponse


class OfflineLLM:
    """No model calls. The workflow uses deterministic template synthesis from verified evidence.

    This keeps the platform fully functional (numbers, citations, verification, benchmark for
    experiments D/E) without any API key, and is the reproducible baseline for cost/latency.
    """

    provider = "offline"
    model = "template-synthesizer"
    offline = True

    def complete(self, system: str, user: str, max_tokens: int = 4000, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        raise RuntimeError("OfflineLLM does not generate text; callers must use template synthesis")


def build_llm(settings: Settings | None = None, provider: str | None = None) -> LLM:
    s = settings or get_settings()
    choice = (provider or s.llm_provider or "auto").lower()
    if choice == "auto":
        if s.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            choice = "anthropic"
        elif s.openai_api_key or os.environ.get("OPENAI_API_KEY"):
            choice = "openai"
        elif s.gemini_api_key or os.environ.get("GEMINI_API_KEY"):
            choice = "gemini"
        else:
            choice = "offline"
    if choice == "anthropic":
        from app.llm.anthropic_provider import AnthropicLLM

        return AnthropicLLM(s.llm_model or None, s.anthropic_api_key or None, s.llm_effort, s.llm_timeout_seconds)
    if choice in ("openai", "gemini", "ollama"):
        from app.llm.openai_compat_provider import OpenAICompatLLM

        key = {
            "openai": s.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
            "gemini": s.gemini_api_key or os.environ.get("GEMINI_API_KEY", ""),
            "ollama": "ollama",
        }[choice]
        base = s.ollama_base_url if choice == "ollama" else None
        return OpenAICompatLLM(choice, s.llm_model or None, key or None, base, s.llm_timeout_seconds, s.llm_min_interval_seconds, s.llm_rate_limit_retries)
    return OfflineLLM()
