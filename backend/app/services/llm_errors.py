"""Turn provider exceptions into something a user can act on.

Every LLM failure used to surface as "check that an LLM provider API key is
configured" — actively misleading when the real cause is a rate limit or a
daily quota, where the key is fine and the only useful advice is "wait" or
"add a fallback provider".

Classification is done on the exception *type name* and message text rather
than by importing litellm, so this module stays cheap to import (litellm is
deliberately off the startup path — see llm_router.get_router) and keeps
working across litellm's exception-hierarchy reshuffles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class LLMErrorKind(str, Enum):
    QUOTA = "quota"  # daily/monthly allowance spent — waiting minutes won't help
    RATE_LIMIT = "rate_limit"  # too fast right now — retrying shortly will help
    AUTH = "auth"  # key missing, invalid or lacking access
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"  # provider 5xx / overloaded
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LLMErrorInfo:
    kind: LLMErrorKind
    message: str  # shown to the user, in the assistant bubble
    retry_after_seconds: int | None = None
    provider_detail: str | None = None  # raw text, for the UI's "details" toggle

    @property
    def is_retryable(self) -> bool:
        return self.kind in (LLMErrorKind.RATE_LIMIT, LLMErrorKind.UNAVAILABLE, LLMErrorKind.TIMEOUT)


# Providers spell this a dozen ways; match the stable substrings.
_QUOTA_HINTS = (
    "quota exceeded",
    "resource_exhausted",
    "insufficient_quota",
    "exceeded your current quota",
    "billing details",
    "requestsperday",
    "per day",
    "credit balance is too low",
)
_AUTH_HINTS = (
    "api key",
    "api_key",
    "unauthorized",
    "authentication",
    "invalid_api_key",
    "permission denied",
    "no api key configured",
)
_CONTEXT_HINTS = ("context window", "context_length", "maximum context", "too many tokens")

_RETRY_PATTERNS = (
    re.compile(r'"?retryDelay"?[":\s]+"?(\d+(?:\.\d+)?)s', re.IGNORECASE),
    re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    re.compile(r"try again in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    re.compile(r"retry-after[\":\s]+(\d+)", re.IGNORECASE),
)


def _retry_after(text: str) -> int | None:
    for pattern in _RETRY_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                return max(1, round(float(m.group(1))))
            except ValueError:
                continue
    return None


def classify(exc: BaseException) -> LLMErrorInfo:
    """Map a provider/litellm exception to a user-facing explanation."""
    raw = str(exc)
    text = raw.lower()
    type_name = type(exc).__name__.lower()
    retry = _retry_after(raw)

    is_quota = any(h in text for h in _QUOTA_HINTS)
    is_rate = "ratelimit" in type_name or "rate limit" in text or "429" in text

    # Quota is checked before rate limit: providers return 429 for both, but a
    # spent daily allowance is not something "retry in a few seconds" fixes,
    # and telling the user to retry would just loop them.
    if is_quota:
        return LLMErrorInfo(
            kind=LLMErrorKind.QUOTA,
            message=(
                "Your LLM provider's quota is used up, so I can't generate an answer right now. "
                "This is a limit on the API key, not a problem with your documents — retrieval "
                "still works. Wait for the quota to reset, switch to a key with remaining "
                "allowance, or add another provider to FALLBACK_MODELS so requests can fail over."
            ),
            retry_after_seconds=retry,
            provider_detail=raw[:800],
        )

    if is_rate:
        wait = f" Try again in about {retry}s." if retry else " Try again shortly."
        return LLMErrorInfo(
            kind=LLMErrorKind.RATE_LIMIT,
            message=("The LLM provider is rate-limiting requests." + wait),
            retry_after_seconds=retry,
            provider_detail=raw[:800],
        )

    if "timeout" in type_name or "timed out" in text or "timeout" in text:
        return LLMErrorInfo(
            kind=LLMErrorKind.TIMEOUT,
            message="The language model took too long to respond. Try again, or ask a shorter question.",
            retry_after_seconds=retry,
            provider_detail=raw[:800],
        )

    if any(h in text for h in _CONTEXT_HINTS):
        return LLMErrorInfo(
            kind=LLMErrorKind.CONTEXT_LENGTH,
            message=(
                "The question plus retrieved context exceeded the model's context window. "
                "Try a narrower question, or reduce RERANK_TOP_K so fewer chunks are sent."
            ),
            provider_detail=raw[:800],
        )

    # Checked after quota/rate: provider quota errors often mention "billing"
    # and "API key" in the same blob, and misreading one as an auth failure
    # sends the user off to regenerate a key that was never broken.
    if any(h in text for h in _AUTH_HINTS) or "auth" in type_name:
        return LLMErrorInfo(
            kind=LLMErrorKind.AUTH,
            message=(
                "The LLM provider rejected the API key. Check that a valid key is set in "
                "backend/.env for the configured PRIMARY_MODEL, then restart the backend."
            ),
            provider_detail=raw[:800],
        )

    if "unavailable" in type_name or "503" in text or "overloaded" in text or "internalserver" in type_name:
        return LLMErrorInfo(
            kind=LLMErrorKind.UNAVAILABLE,
            message="The LLM provider is temporarily unavailable. Try again in a moment.",
            retry_after_seconds=retry,
            provider_detail=raw[:800],
        )

    return LLMErrorInfo(
        kind=LLMErrorKind.UNKNOWN,
        message="I couldn't reach the language model just now. Please try again.",
        provider_detail=raw[:800],
    )
