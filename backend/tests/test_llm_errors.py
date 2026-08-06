"""The classifier exists because every LLM failure used to render as
"check that an LLM provider API key is configured" — which is wrong, and
actively misleading, for the most common failure on a free-tier key.

Payloads below are real provider responses captured from this project.
"""

from app.services.llm_errors import LLMErrorKind, classify


class RateLimitError(Exception):
    """Stands in for litellm.RateLimitError — classification keys off the type
    name and message, so it doesn't need litellm imported."""


class AuthenticationError(Exception):
    pass


class Timeout(Exception):
    pass


class ServiceUnavailableError(Exception):
    pass


GEMINI_DAILY_QUOTA = (
    "litellm.RateLimitError: geminiException - "
    '{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan '
    "and billing details. Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, "
    'model: gemini-3.6-flash", "status": "RESOURCE_EXHAUSTED", '
    '"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "38s"}]}}'
)


def test_daily_quota_is_reported_as_quota_not_auth():
    info = classify(RateLimitError(GEMINI_DAILY_QUOTA))
    assert info.kind is LLMErrorKind.QUOTA
    # The whole point: it must not send the user off to fix a working key.
    assert "api key" not in info.message.lower() or "limit on the API key" in info.message
    assert "quota" in info.message.lower()


def test_quota_message_reassures_that_retrieval_still_worked():
    info = classify(RateLimitError(GEMINI_DAILY_QUOTA))
    assert "retrieval" in info.message.lower()


def test_retry_delay_is_parsed_from_the_provider_payload():
    assert classify(RateLimitError(GEMINI_DAILY_QUOTA)).retry_after_seconds == 38


def test_quota_is_not_advertised_as_retryable():
    # A spent daily allowance is not fixed by retrying in 38s; saying so would
    # just loop the user.
    assert classify(RateLimitError(GEMINI_DAILY_QUOTA)).is_retryable is False


def test_plain_rate_limit_is_distinct_from_quota_and_is_retryable():
    info = classify(RateLimitError("429 rate limit exceeded, please retry in 12s"))
    assert info.kind is LLMErrorKind.RATE_LIMIT
    assert info.retry_after_seconds == 12
    assert info.is_retryable is True


def test_openai_style_insufficient_quota_is_quota():
    info = classify(RateLimitError("Error code: 429 - insufficient_quota: exceeded your current quota"))
    assert info.kind is LLMErrorKind.QUOTA


def test_anthropic_style_low_credit_is_quota():
    info = classify(RateLimitError("Your credit balance is too low to access the API"))
    assert info.kind is LLMErrorKind.QUOTA


def test_genuine_auth_failure_is_still_reported_as_auth():
    info = classify(AuthenticationError("Incorrect API key provided: sk-xxx. Unauthorized."))
    assert info.kind is LLMErrorKind.AUTH
    assert "key" in info.message.lower()


def test_timeout_is_classified_and_suggests_a_shorter_question():
    info = classify(Timeout("Connection timed out. Timeout passed=30.0"))
    assert info.kind is LLMErrorKind.TIMEOUT
    assert info.is_retryable is True


def test_provider_503_is_unavailable_and_retryable():
    info = classify(ServiceUnavailableError("503 model is overloaded, please try again later"))
    assert info.kind is LLMErrorKind.UNAVAILABLE
    assert info.is_retryable is True


def test_context_window_overflow_points_at_rerank_top_k():
    info = classify(ValueError("This model's maximum context length is 8192 tokens"))
    assert info.kind is LLMErrorKind.CONTEXT_LENGTH
    assert "RERANK_TOP_K" in info.message


def test_unrecognised_failure_falls_back_without_blaming_the_key():
    info = classify(RuntimeError("some totally novel provider failure"))
    assert info.kind is LLMErrorKind.UNKNOWN
    assert "api key" not in info.message.lower()


def test_provider_detail_is_captured_but_bounded():
    info = classify(RateLimitError("x" * 5000))
    assert info.provider_detail is not None
    assert len(info.provider_detail) <= 800


def test_classifier_never_raises_on_odd_exceptions():
    for exc in (Exception(), ValueError(""), RuntimeError(None)):
        assert classify(exc).kind is not None
