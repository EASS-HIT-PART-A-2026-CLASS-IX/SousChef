"""
Minimal in-memory rate limiter (fixed 60-second window, per client IP).

Configured via RATE_LIMIT_PER_MINUTE (default 120; 0 or negative disables).
State is process-local — good enough for a single-container local stack.
"""
from __future__ import annotations

import os
import time

# ip -> (window_id, request_count)
_buckets: dict[str, tuple[int, int]] = {}

WINDOW_SECONDS = 60
EXEMPT_PATHS = {"/health"}


def limit_per_minute() -> int:
    try:
        return int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    except ValueError:
        return 120


def reset() -> None:
    """Clear all buckets (used by tests)."""
    _buckets.clear()


def hit(client_ip: str) -> tuple[bool, dict[str, str]]:
    """
    Register one request for `client_ip`.

    Returns (allowed, headers) where headers always carry the X-RateLimit-*
    trio and, when the limit is exceeded, a Retry-After hint.
    """
    limit = limit_per_minute()
    now = time.time()
    seconds_to_reset = WINDOW_SECONDS - int(now) % WINDOW_SECONDS

    if limit <= 0:  # disabled
        return True, {}

    window = int(now) // WINDOW_SECONDS
    stored_window, count = _buckets.get(client_ip, (window, 0))
    if stored_window != window:
        count = 0
    count += 1
    _buckets[client_ip] = (window, count)

    remaining = max(limit - count, 0)
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(seconds_to_reset),
    }
    if count > limit:
        headers["Retry-After"] = str(seconds_to_reset)
        return False, headers
    return True, headers
