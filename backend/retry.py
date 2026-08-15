"""CourseLens — shared retry for Groq API calls.

One helper used at every Groq call site (transcription, vision captioning,
generation, grading, concept extraction) so transient provider trouble — a
capacity blip, a rate-limit burst — degrades into a short wait instead of a
failed ingestion.

Retries on transient statuses only. Auth/validation errors (401/403/404/422 and
other 4xx) are permanent: retrying just burns time and hides the real problem, so
they raise immediately. Backoff is exponential with **full jitter**
(`sleep = uniform(0, min(cap, base * 2**attempt))`) — the standard fix for the
thundering herd you'd otherwise create by retrying every figure in a deck on the
same schedule during an outage.
"""
import random
import time

import groq

# Transient: worth another attempt.
#   408 request timeout · 429 rate limited · 500/502/503 upstream trouble
#   529 provider overloaded
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 529})

# Transport-level failures carry no HTTP status but are equally transient.
RETRYABLE_EXCEPTIONS = (groq.APIConnectionError, groq.APITimeoutError)

DEFAULT_ATTEMPTS = 5
DEFAULT_BASE_S = 2.0
DEFAULT_CAP_S = 30.0


def is_retryable(exc):
    """Should this exception be retried?"""
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True
    status = getattr(exc, "status_code", None)
    return status in RETRYABLE_STATUS


def call_with_retry(fn, *, attempts=DEFAULT_ATTEMPTS, base=DEFAULT_BASE_S,
                    cap=DEFAULT_CAP_S, on_retry=None):
    """Call `fn()`, retrying transient Groq failures with jittered backoff.

    Re-raises the original exception once attempts are exhausted (or immediately
    for non-retryable errors), so callers still see the real cause. `on_retry` is
    an optional callback `(exc, attempt, delay)` for logging/UI progress.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc) or attempt == attempts - 1:
                raise
            delay = random.uniform(0, min(cap, base * (2 ** attempt)))
            if on_retry:
                on_retry(exc, attempt + 1, delay)
            time.sleep(delay)
