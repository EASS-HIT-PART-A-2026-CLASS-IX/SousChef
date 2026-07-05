"""
Tests for the /health endpoint and the rate-limit middleware headers.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import ratelimit
from app.database import get_session


@pytest.fixture(name="client")
def client_fixture():
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    ratelimit.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    ratelimit.reset()
    SQLModel.metadata.drop_all(engine)


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_reports_version(self, client: TestClient):
        resp = client.get("/health")
        assert resp.json()["version"]


# ── Rate limiting ─────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_rate_limit_headers_present(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "120")
        ratelimit.reset()
        resp = client.get("/recipes")
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "120"
        assert int(resp.headers["X-RateLimit-Remaining"]) < 120
        assert 0 <= int(resp.headers["X-RateLimit-Reset"]) <= 60

    def test_remaining_decreases_per_request(self, client: TestClient):
        first = int(client.get("/recipes").headers["X-RateLimit-Remaining"])
        second = int(client.get("/recipes").headers["X-RateLimit-Remaining"])
        assert second == first - 1

    def test_exceeding_limit_returns_429(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        ratelimit.reset()
        assert client.get("/recipes").status_code == 200
        assert client.get("/recipes").status_code == 200
        resp = client.get("/recipes")
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Remaining"] == "0"
        assert int(resp.headers["Retry-After"]) > 0

    def test_health_is_exempt_from_rate_limit(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
        ratelimit.reset()
        for _ in range(3):
            assert client.get("/health").status_code == 200
