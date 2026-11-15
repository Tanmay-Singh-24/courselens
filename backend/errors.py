"""CourseLens — user-facing error messages.

Turns provider exceptions into one plain sentence a visitor can act on. By the time
one of these surfaces, the shared retry has already tried with backoff, so the
useful message is what to do next. The full traceback always goes to the log.
"""
import logging
import os
import traceback

import groq


def is_rate_limit(e):
    return getattr(e, "status_code", None) == 429 or "rate_limit" in str(e).lower()


def friendly_message(e, subject=None):
    logging.exception("request failed%s", f" [{subject}]" if subject else "")
    what = f"{subject}: " if subject else ""
    status = getattr(e, "status_code", None)
    if is_rate_limit(e):
        return (f"{what}the free-tier model limit is reached (this demo runs on one free "
                "API key). Please try again in a minute.")
    if status in (408, 500, 502, 503, 529) or isinstance(
            e, (groq.APIConnectionError, groq.APITimeoutError)):
        return (f"{what}the model provider is busy right now. We retried automatically; "
                "please try again in a minute.")
    if status in (401, 403):
        return f"{what}the server's API key was rejected. This is a configuration issue."
    where = ""
    tb = traceback.extract_tb(e.__traceback__)
    if tb:
        where = f" at {os.path.basename(tb[-1].filename)}:{tb[-1].lineno}"
    return f"{what}something went wrong ({type(e).__name__}{where}). Please try again."
