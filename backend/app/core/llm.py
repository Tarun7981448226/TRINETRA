"""One door to every language model — a pool of free models, so TRINETRA never goes silent.

Tiers:
  smart — deeper thinking (talking to you, planning, coaching)
  fast  — quick, frequent jobs (classify, extract memories, read your mood)

Each tier is an ordered pool (TRINETRA_MODELS_SMART / TRINETRA_MODELS_FAST in .env). Free tiers have
small per-model allowances (e.g. 20 requests/day on some Gemini models, 8k tokens/minute on Groq), so a
model that hits its limit is benched — a minute for per-minute limits, hours for daily ones — and the
next model in the pool answers instead. Add Claude later with e.g. anthropic/claude-sonnet-5-5.
"""
import logging
import time
from typing import Literal

from app.config import get_settings

log = logging.getLogger("trinetra.llm")

Tier = Literal["smart", "fast"]

OFFLINE_REPLY = (
    "My thinking engine isn't connected yet — add a free GEMINI_API_KEY or GROQ_API_KEY "
    "to .env and I'll come fully alive."
)

_benched_until: dict[str, float] = {}  # model → unix time it may be tried again


class LLMUnavailable(RuntimeError):
    pass


def _has_key(model: str) -> bool:
    s = get_settings()
    provider = model.split("/", 1)[0]
    return {"gemini": bool(s.gemini_api_key), "groq": bool(s.groq_api_key)}.get(provider, True)


def pool(tier: Tier) -> list[str]:
    s = get_settings()
    primary = s.trinetra_models_smart if tier == "smart" else s.trinetra_models_fast
    backup = s.trinetra_models_fast if tier == "smart" else s.trinetra_models_smart
    ordered = []
    for m in [*primary.split(","), *backup.split(",")]:  # the other tier's pool is the last resort
        m = m.strip()
        if m and m not in ordered and _has_key(m):
            ordered.append(m)
    return ordered


def _bench(model: str, error: Exception) -> None:
    msg = str(error)
    if "PerDay" in msg or "per day" in msg.lower():
        seconds = 6 * 3600  # daily allowance gone
    elif "429" in msg or "RateLimit" in type(error).__name__ or "RESOURCE_EXHAUSTED" in msg:
        seconds = 65  # per-minute limit
    else:
        seconds = 30  # outage / overloaded
    _benched_until[model] = time.time() + seconds
    log.warning("benched %s for %ss (%s)", model, seconds, type(error).__name__)


# Both providers speak the OpenAI chat format, so one tiny client covers them (no 150 MB SDK —
# TRINETRA must fit in a serverless function).
ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}


class ProviderError(RuntimeError):
    pass


class RateLimitError(ProviderError):
    pass


async def _call(model: str, messages: list[dict], temperature: float, max_tokens: int, json_mode: bool,
                reasoning: str | None = None) -> str:
    import httpx

    provider, name = model.split("/", 1)
    url = ENDPOINTS.get(provider)
    if url is None:
        raise ProviderError(f"unknown provider '{provider}' in {model}")
    s = get_settings()
    key = {"gemini": s.gemini_api_key, "groq": s.groq_api_key}[provider]
    body = {"model": name, "messages": messages, "max_tokens": max_tokens}
    if not name.startswith("gemini-3"):  # Gemini 3 deprecates sampling params
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning and (name.startswith("gemini-3") or name.startswith("openai/gpt-oss")):
        body["reasoning_effort"] = reasoning  # thinking models: less thinking = much faster replies
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
    if r.status_code == 429:
        raise RateLimitError(f"429 {r.text[:3000]}")  # long enough to include the quota id (PerDay vs per-minute)
    if r.status_code >= 400:
        raise ProviderError(f"{r.status_code} {r.text[:200]}")
    return r.json()["choices"][0]["message"].get("content") or ""


async def complete(
    messages: list[dict],
    tier: Tier = "smart",
    temperature: float = 0.7,
    max_tokens: int = 800,
    json_mode: bool = False,
    reasoning: str | None = None,
) -> str:
    """`reasoning` ("minimal"/"low"/"medium"/"high") caps how long thinking models think; None = their default."""
    models = pool(tier)
    if not models:
        raise LLMUnavailable(OFFLINE_REPLY)

    now = time.time()
    ready = [m for m in models if _benched_until.get(m, 0) <= now]
    # If everything is benched, try the one that frees up soonest rather than giving up.
    candidates = ready or sorted(models, key=lambda m: _benched_until.get(m, 0))[:1]

    last_error: Exception | None = None
    for model in candidates:
        try:
            text = await _call(model, messages, temperature, max_tokens, json_mode, reasoning)
            if text.strip():
                return text
            last_error = ProviderError(f"{model} returned an empty reply")
        except Exception as e:  # rate limit, outage, bad key — bench it and try the next one
            _bench(model, e)
            last_error = e
    raise LLMUnavailable(f"All models failed: {type(last_error).__name__}")
