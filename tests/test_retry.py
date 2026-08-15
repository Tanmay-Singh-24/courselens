"""Shared Groq retry helper — transient statuses retry, permanent ones don't.

Fully offline: no API calls, and time.sleep is patched out so the suite stays fast.
"""
import httpx
import groq
import pytest

from backend import retry as R


# How the Groq SDK maps HTTP statuses to typed exceptions; anything else >=500
# lands on InternalServerError.
_EXC_BY_STATUS = {
    400: groq.BadRequestError,
    401: groq.AuthenticationError,
    403: groq.PermissionDeniedError,
    404: groq.NotFoundError,
    422: groq.UnprocessableEntityError,
    429: groq.RateLimitError,
}


def api_error(status):
    """Build the exception the SDK would raise for `status`, with a real response
    attached so `status_code` is populated exactly as in production."""
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=status, request=request,
                              json={"error": {"message": "over capacity"}})
    exc_cls = _EXC_BY_STATUS.get(status, groq.InternalServerError)
    return exc_cls("boom", response=response, body=None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Never actually wait during tests."""
    monkeypatch.setattr(R.time, "sleep", lambda s: None)


# ── retryable ────────────────────────────────────────────────────────────────
def test_503_succeeds_on_retry():
    """The reported production failure: capacity 503 mid-ingest must recover."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise api_error(503)
        return "caption"

    assert R.call_with_retry(flaky) == "caption"
    assert len(calls) == 2          # failed once, then succeeded


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 529])
def test_all_transient_statuses_are_retried(status):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise api_error(status)
        return "ok"

    assert R.call_with_retry(flaky) == "ok"
    assert len(calls) == 2


def test_connection_errors_are_retried():
    calls = []
    request = httpx.Request("POST", "https://api.groq.com/")

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise groq.APIConnectionError(request=request)
        return "ok"

    assert R.call_with_retry(flaky) == "ok"


# ── non-retryable ────────────────────────────────────────────────────────────
def test_401_fails_immediately_without_retrying():
    """Auth failures are permanent — retrying hides the real problem."""
    calls = []

    def bad_key():
        calls.append(1)
        raise api_error(401)

    with pytest.raises(groq.AuthenticationError):
        R.call_with_retry(bad_key)
    assert len(calls) == 1          # no retry


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_other_client_errors_fail_immediately(status):
    calls = []

    def bad_request():
        calls.append(1)
        raise api_error(status)

    with pytest.raises(groq.APIStatusError):
        R.call_with_retry(bad_request)
    assert len(calls) == 1


# ── exhaustion ───────────────────────────────────────────────────────────────
def test_exhaustion_reraises_original_after_max_attempts():
    calls = []

    def always_busy():
        calls.append(1)
        raise api_error(503)

    with pytest.raises(groq.InternalServerError):   # ORIGINAL exception, not wrapped
        R.call_with_retry(always_busy, attempts=4)
    assert len(calls) == 4                          # exactly max attempts


def test_backoff_is_capped_and_jittered(monkeypatch):
    """Full jitter: every delay in [0, min(cap, base*2**n)] — never a fixed schedule."""
    delays = []
    monkeypatch.setattr(R.time, "sleep", lambda s: delays.append(s))

    def always_busy():
        raise api_error(503)

    with pytest.raises(groq.InternalServerError):
        R.call_with_retry(always_busy, attempts=6, base=2.0, cap=30.0)

    assert len(delays) == 5                          # one sleep between each attempt
    assert all(0 <= d <= 30.0 for d in delays)       # capped
    for i, d in enumerate(delays):
        assert d <= min(30.0, 2.0 * (2 ** i))        # within this attempt's window


def test_on_retry_callback_fires_per_retry():
    seen = []
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise api_error(502)
        return "ok"

    R.call_with_retry(flaky, on_retry=lambda e, a, d: seen.append(a))
    assert seen == [1, 2]
