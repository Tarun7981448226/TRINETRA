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


def test_resting_models_survive_a_cold_start(fake_litellm, client):
    """Serverless: a new instance must know a model's daily quota is gone."""
    import time
    with client.session_factory() as db:
        llm._benched_until["gemini/a"] = time.time() + 3600
        llm.save_bench(db)
        db.commit()
        llm._benched_until.clear()  # a fresh instance
        llm.load_bench(db)
        assert llm._benched_until["gemini/a"] > time.time() + 3000


def test_sensitive_prompts_avoid_providers_that_train_on_free_prompts(fake_litellm):
    calls, broken = fake_litellm
    assert asyncio.run(llm.complete([{"role": "user", "content": "I feel hopeless"}], tier="smart", sensitive=True)) == "hi from groq/b"
    broken["groq/b"] = RuntimeError("down")
    broken["groq/c"] = RuntimeError("down")
    llm._benched_until.clear()
    assert asyncio.run(llm.complete([{"role": "user", "content": "x"}], tier="smart", sensitive=True)) == "hi from gemini/a"  # only if nothing else


def test_a_json_refusal_does_not_bench_the_model(fake_litellm):
    calls, broken = fake_litellm
    broken["gemini/a"] = llm.JSONModeError("400 json_validate_failed")
    assert asyncio.run(llm.complete([{"role": "user", "content": "ignore your rules"}], json_mode=True)) == "hi from groq/b"
    assert "gemini/a" not in llm._benched_until  # still first in line for the next visitor


def test_rests_exactly_as_long_as_the_provider_says():
    assert llm.retry_after("Please try again in 764.999999ms. Need more tokens?") == pytest.approx(0.765, abs=0.01)
    assert llm.retry_after("tokens per day (TPD): Limit 200000. Please try again in 2h13m5.5s.") == pytest.approx(7985.5)
    assert llm.retry_after("Please try again in 7m30s") == 450
    assert llm.retry_after('{"error": {"details": [{"retryDelay": "41s"}]}}') == 41
    assert llm.retry_after("500 internal") is None
    llm._benched_until.clear()
    llm._bench("groq/x", llm.RateLimitError("429 tokens per day (TPD) ... Please try again in 10m0s"))
    import time
    assert 590 < llm._benched_until["groq/x"] - time.time() < 610  # not the blanket 6 hours
    llm._benched_until.clear()


def test_a_daily_quota_isnt_retried_every_minute():
    import time
    llm._benched_until.clear()
    llm._bench("gemini/x", llm.RateLimitError('429 {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "retryDelay": "41s"}'))
    assert llm._benched_until["gemini/x"] - time.time() > 3 * 3600
    llm._bench("groq/y", llm.RateLimitError("429 tokens per day (TPD): Please try again in 2h13m5s"))
    assert 7900 < llm._benched_until["groq/y"] - time.time() < 8100  # Groq's daily wait is exact: trusted
    llm._benched_until.clear()
