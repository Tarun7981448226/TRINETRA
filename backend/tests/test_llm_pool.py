import asyncio

import pytest

from app.config import get_settings
from app.core import llm


@pytest.fixture
def fake_litellm(monkeypatch):
    """A fake LiteLLM where some models are 'out of quota'."""
    calls, broken = [], {}

    async def fake_call(model, messages, temperature, max_tokens, json_mode, reasoning=None):
        calls.append(model)
        if model in broken:
            raise broken[model]
        return f"hi from {model}"

    monkeypatch.setattr(llm, "_call", fake_call)
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "g")
    monkeypatch.setattr(s, "groq_api_key", "q")
    monkeypatch.setattr(s, "trinetra_models_smart", "gemini/a,groq/b")
    monkeypatch.setattr(s, "trinetra_models_fast", "groq/c")
    llm._benched_until.clear()
    yield calls, broken
    llm._benched_until.clear()


class RateLimitError(Exception):
    pass


def test_pool_order_and_last_resort(fake_litellm):
    assert llm.pool("smart") == ["gemini/a", "groq/b", "groq/c"]
    assert llm.pool("fast") == ["groq/c", "gemini/a", "groq/b"]


def test_models_without_keys_are_skipped(fake_litellm, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    assert llm.pool("smart") == ["groq/b", "groq/c"]


def test_daily_quota_benches_model_for_hours(fake_litellm):
    calls, broken = fake_litellm
    broken["gemini/a"] = RateLimitError("429 Quota exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert asyncio.run(llm.complete([{"role": "user", "content": "x"}])) == "hi from groq/b"
    calls.clear()
    assert asyncio.run(llm.complete([{"role": "user", "content": "x"}])) == "hi from groq/b"
    assert calls == ["groq/b"]  # didn't waste time retrying the exhausted model
    import time
    assert llm._benched_until["gemini/a"] - time.time() > 3600


def test_per_minute_limit_benches_briefly(fake_litellm):
    _, broken = fake_litellm
    broken["gemini/a"] = RateLimitError("429 tokens per minute")
    asyncio.run(llm.complete([{"role": "user", "content": "x"}]))
    import time
    assert 0 < llm._benched_until["gemini/a"] - time.time() <= 65


def test_everything_down_raises_cleanly(fake_litellm):
    _, broken = fake_litellm
    for m in ("gemini/a", "groq/b", "groq/c"):
        broken[m] = RuntimeError("503 overloaded")
    with pytest.raises(llm.LLMUnavailable):
        asyncio.run(llm.complete([{"role": "user", "content": "x"}]))


def test_guest_pool_puts_its_own_models_first(fake_litellm, monkeypatch):
    monkeypatch.setattr(get_settings(), "trinetra_models_guest", "groq/b,gemini/z")
    assert llm.pool("guest") == ["groq/b", "gemini/z", "gemini/a", "groq/c"]
