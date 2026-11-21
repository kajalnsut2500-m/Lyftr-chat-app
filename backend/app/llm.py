"""LiteLLM gateway: key pool with failover, response cache, per-request usage."""
import logging
from dataclasses import dataclass
from typing import Optional

import litellm
from litellm.caching.caching import Cache

log = logging.getLogger("llm")
litellm.suppress_debug_info = True


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    source: str  # LIVE_INFERENCE or LLM_CACHE
    model: str
    input_tokens: int
    output_tokens: int
    key_id: Optional[str]
    fallback_attempts: int


def init_cache() -> None:
    """Enable LiteLLM's built-in in-memory cache, then warm it up."""
    litellm.cache = Cache(type="local")
    _warm_up()


def _warm_up() -> None:
    """The first cache hit lazily imports a lot of code (slow). Do one mocked store + hit at
    startup so the first real cache hit is fast. Uses mock_response: no provider call, no key."""
    try:
        msgs = [{"role": "user", "content": "__warmup__"}]
        for _ in range(2):
            litellm.completion(model="gemini/warmup", messages=msgs, api_key="warmup",
                               mock_response="warmup", num_retries=0)
    except Exception as exc:
        log.warning("cache warm-up failed: %s", type(exc).__name__)


def cache_enabled() -> bool:
    return litellm.cache is not None


def _extra_kwargs(key: str) -> dict:
    """Hook for tests: extra kwargs for litellm.completion (e.g. mock_response)."""
    return {}


def complete(messages, keys, model, simulate=None, timeout=30) -> LLMResult:
    """Try each key in order. Fail over to the next key on ANY failure."""
    simulate = simulate or {}
    failed = 0
    for i, key in enumerate(keys, start=1):
        key_id = f"key_{i}"
        status = simulate.get(key_id) or simulate.get("*")
        if status:  # simulated failure: behave as if the provider returned this status
            failed += 1
            continue
        kwargs = dict(model=model, messages=messages, api_key=key, timeout=timeout, num_retries=0)
        if simulate:
            kwargs["cache"] = {"no-cache": True}  # always make a real call while simulating
        kwargs.update(_extra_kwargs(key))
        try:
            resp = litellm.completion(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("empty reply")
        except Exception as exc:  # 429, quota, 5xx, timeout, bad key ...
            log.warning("%s failed: %s", key_id, type(exc).__name__)  # never log the key
            failed += 1
            continue
        hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
        usage = getattr(resp, "usage", None)
        return LLMResult(
            reply=text,
            source="LLM_CACHE" if hit else "LIVE_INFERENCE",
            model=model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            key_id=None if hit else key_id,
            fallback_attempts=0 if hit else failed,
        )
    raise AllProvidersUnavailable()
