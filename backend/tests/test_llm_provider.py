"""Free-tier behaviour of the OpenAI-compatible adapter (Gemini): pacing, 429 waits, daily-quota fail-fast."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.llm import openai_compat_provider as mod
from app.llm.base import LLMError


def _rate_limit(body: dict) -> openai.RateLimitError:
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return openai.RateLimitError("rate limited", response=httpx.Response(429, request=req), body=body)


def _ok():
    msg = SimpleNamespace(content="hello")
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1), model="m")


@pytest.fixture
def llm(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    mod._last_call.clear()
    m = mod.OpenAICompatLLM("gemini", "test-model", "fake-key", min_interval=0)
    m.sleeps = sleeps
    return m


def _script(llm, outcomes):
    calls = iter(outcomes)

    def create(**_):
        o = next(calls)
        if isinstance(o, Exception):
            raise o
        return o

    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_per_minute_429_waits_server_delay_then_succeeds(llm):
    _script(llm, [_rate_limit({"message": "Resource exhausted. Please retry in 7.5s."}), _ok()])
    assert llm.complete("s", "u").text == "hello"
    assert llm.sleeps == [8.5]  # suggested delay + 1 s margin


def test_daily_quota_fails_fast_without_retrying(llm):
    _script(llm, [_rate_limit({"message": "Quota exceeded for metric: GenerateRequestsPerDayPerProjectPerModel-FreeTier"})])
    with pytest.raises(LLMError) as e:
        llm.complete("s", "u")
    assert "daily quota" in str(e.value) and not e.value.retryable
    assert llm.sleeps == []


def test_gives_up_after_configured_retries(llm):
    llm.max_rate_limit_retries = 2
    _script(llm, [_rate_limit({"message": "slow down"})] * 3)
    with pytest.raises(LLMError):
        llm.complete("s", "u")
    assert llm.sleeps == [15.0, 30.0]  # no server hint: 15 s, 30 s


def test_calls_are_paced(monkeypatch):
    clock = {"t": 100.0}
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mod.time, "sleep", lambda s: (sleeps.append(round(s, 3)), clock.__setitem__("t", clock["t"] + s)))
    mod._last_call.clear()
    m = mod.OpenAICompatLLM("gemini", "test-model", "fake-key")  # provider default pacing
    _script(m, [_ok(), _ok()])
    m.complete("s", "u")
    clock["t"] += 1.0
    m.complete("s", "u")
    assert sleeps == [mod.DEFAULT_MIN_INTERVAL["gemini"] - 1.0]
