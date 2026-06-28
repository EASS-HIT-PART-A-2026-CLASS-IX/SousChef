"""
Tests for the async refresh worker (scripts/refresh.py).

Uses fake httpx-like and redis-like async doubles so no network or real Redis
is touched. Covers: happy path, idempotency skip, and retry-on-transient-failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

# Make the repo-root `scripts` package importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import refresh  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeRedis:
    """Minimal async stand-in supporting set(nx=, ex=) and exists()."""

    def __init__(self, existing: set[str] | None = None):
        self._keys: set[str] = set(existing or set())

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self._keys:
            return None
        self._keys.add(key)
        return True

    async def exists(self, key):
        return 1 if key in self._keys else 0


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=None
            )


class FakeClient:
    """Async client whose .get returns scripted responses or raises."""

    def __init__(self, responses):
        # responses: dict[path] -> FakeResponse | Exception | list of those
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, path, **kwargs):
        self.calls.append(path)
        item = self._responses[path]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_refresh_recipe_processed():
    client = FakeClient({"/recipes/1/enhance": FakeResponse(200, {"tips": "ok"})})
    redis = FakeRedis()
    status = await refresh.refresh_recipe(1, client=client, redis=redis, ttl=3600)
    assert status == "processed"
    assert client.calls == ["/recipes/1/enhance"]


@pytest.mark.anyio
async def test_refresh_recipe_skipped_when_key_exists():
    client = FakeClient({"/recipes/1/enhance": FakeResponse(200, {"tips": "ok"})})
    redis = FakeRedis(existing={"refresh:1"})
    status = await refresh.refresh_recipe(1, client=client, redis=redis, ttl=3600)
    assert status == "skipped"
    # Must NOT have made the HTTP call when idempotency key already present.
    assert client.calls == []


@pytest.mark.anyio
async def test_refresh_recipe_retries_then_succeeds():
    client = FakeClient(
        {
            "/recipes/1/enhance": [
                httpx.ConnectError("boom"),
                FakeResponse(200, {"tips": "ok"}),
            ]
        }
    )
    redis = FakeRedis()
    status = await refresh.refresh_recipe(
        1, client=client, redis=redis, ttl=3600, max_retries=3, backoff_base=0
    )
    assert status == "processed"
    assert len(client.calls) == 2


@pytest.mark.anyio
async def test_refresh_recipe_fails_after_max_retries():
    client = FakeClient({"/recipes/1/enhance": httpx.ConnectError("boom")})
    redis = FakeRedis()
    status = await refresh.refresh_recipe(
        1, client=client, redis=redis, ttl=3600, max_retries=3, backoff_base=0
    )
    assert status == "failed"
    assert len(client.calls) == 3


@pytest.mark.anyio
async def test_run_refresh_summary():
    client = FakeClient(
        {
            "/recipes": FakeResponse(200, [{"id": 1}, {"id": 2}]),
            "/recipes/1/enhance": FakeResponse(200, {"tips": "ok"}),
            "/recipes/2/enhance": FakeResponse(200, {"tips": "ok"}),
        }
    )
    redis = FakeRedis(existing={"refresh:2"})  # 2 already done -> skipped
    summary = await refresh.run_refresh(client=client, redis=redis, concurrency=2, ttl=3600)
    assert summary == {"processed": 1, "skipped": 1, "failed": 0}
