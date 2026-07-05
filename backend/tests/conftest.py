"""
Shared test configuration.

The rate limiter is process-global and keyed by client IP; every TestClient
request comes from the same fake IP, so without a reset + generous limit the
full suite would trip 429s mid-run. Individual rate-limit tests override
RATE_LIMIT_PER_MINUTE themselves.
"""
import pytest

from app import ratelimit


@pytest.fixture(autouse=True)
def _rate_limit_off(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "100000")
    ratelimit.reset()
    yield
    ratelimit.reset()
