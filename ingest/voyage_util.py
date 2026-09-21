"""Shared Voyage AI client helpers: every Voyage call in this repo goes
through retry_voyage() so rate-limit handling lives in exactly one place.

Known constraint (observed 2026-08-02, documented in README): the account's
Voyage tier allows roughly 3 requests/minute and ~10K tokens/minute, and
requests whose own token count exceeds the per-minute budget appear to be
refused outright rather than queued. Callers should keep single requests
under ~7K tokens (~48 corpus chunks) and expect long waits on bulk work.

Backoff: exponential with full jitter (0.5x-1.5x of the nominal delay),
capped at 5 minutes per attempt, giving up after max_wait seconds total.
"""

import random
import time

import voyageai

EMBED_MODEL = "voyage-3.5-lite"


def retry_voyage(call, max_wait: float = 3600):
    """Run `call()` (any Voyage SDK invocation), waiting out rate limits."""
    delay = 10.0
    waited = 0.0
    while True:
        try:
            return call()
        except voyageai.error.RateLimitError:
            if waited >= max_wait:
                raise
            pause = delay * (0.5 + random.random())
            time.sleep(pause)
            waited += pause
            delay = min(delay * 2, 300)


def embed_texts(vo, texts, input_type="document", max_wait: float = 3600):
    return retry_voyage(
        lambda: vo.embed(texts, model=EMBED_MODEL, input_type=input_type),
        max_wait=max_wait)
