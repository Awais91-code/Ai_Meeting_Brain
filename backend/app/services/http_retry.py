"""
Shared retry policy for outbound calls to the LLM / embedding provider
(OpenRouter). Centralized here so every service (embeddings, llm,
summary) retries transient failures the same way, instead of each
service inventing its own logic.

Retries:
    - HTTP 429 (rate limited)
    - HTTP 502 / 503 / 504 (upstream temporarily overloaded / down)
    - Network timeouts
    - Connection errors

Does NOT retry:
    - 400 / 401 / 403 / 404 and any other client-side or permanent error

Retries use exponential backoff with a hard cap of 4 total attempts,
so a meeting can never get stuck retrying forever.
"""

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def is_retryable_error(exception: BaseException) -> bool:
    if isinstance(exception, requests.exceptions.Timeout):
        return True

    if isinstance(exception, requests.exceptions.ConnectionError):
        return True

    if isinstance(exception, requests.exceptions.HTTPError):
        response = exception.response
        return bool(
            response is not None
            and response.status_code in RETRYABLE_STATUS_CODES
        )

    return False


def llm_retry():
    """Decorator: retry a function up to 4 times on transient errors."""
    return retry(
        retry=retry_if_exception(is_retryable_error),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )


def raise_for_retryable_status(response: requests.Response) -> None:
    """
    Raise HTTPError only for retryable statuses, so tenacity can catch
    and retry them specifically. Non-2xx/non-retryable statuses are
    left for the caller to handle (e.g. fall back to a canned answer)
    instead of raising, since those are permanent failures.
    """
    if response.status_code in RETRYABLE_STATUS_CODES:
        response.raise_for_status()
