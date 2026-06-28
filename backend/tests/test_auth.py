"""
Auth tests: password hashing, JWT issuance/validation, and the protected
DELETE /recipes/{id} route. All self-contained — no network, no real secrets
beyond the test env vars set in conftest-style monkeypatching below.
"""
from __future__ import annotations

import datetime as dt

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import auth
from app.database import get_session


# ── Test env / fixtures ───────────────────────────────────────────────────────

TEST_SECRET = "test-secret-key"
ADMIN_USER = "admin"
ADMIN_PW = "s3cret-pw"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """Configure a known admin credential + JWT secret for every test."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", auth.hash_password(ADMIN_PW))


@pytest.fixture(name="client")
def client_fixture():
    """A client with a real in-memory DB but NO get_current_user override —
    so auth is actually exercised here."""
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def _make_recipe(client: TestClient) -> int:
    resp = client.post("/recipes", json={"name": "Temp"})
    assert resp.status_code == 201
    return resp.json()["id"]


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_and_verify_roundtrip():
    h = auth.hash_password("hunter2")
    assert h != "hunter2"
    assert auth.verify_password("hunter2", h) is True
    assert auth.verify_password("wrong", h) is False


# ── Token issuance ────────────────────────────────────────────────────────────

def test_obtain_token_happy_path(client: TestClient):
    resp = client.post("/token", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    payload = jwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"])
    assert payload["sub"] == ADMIN_USER
    assert payload["role"] == "admin"


def test_obtain_token_bad_password(client: TestClient):
    resp = client.post("/token", data={"username": ADMIN_USER, "password": "nope"})
    assert resp.status_code == 401


# ── Protected route ───────────────────────────────────────────────────────────

def test_delete_with_valid_token(client: TestClient):
    recipe_id = _make_recipe(client)
    token = client.post(
        "/token", data={"username": ADMIN_USER, "password": ADMIN_PW}
    ).json()["access_token"]
    resp = client.delete(
        f"/recipes/{recipe_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 204


def test_delete_without_token_is_401(client: TestClient):
    recipe_id = _make_recipe(client)
    resp = client.delete(f"/recipes/{recipe_id}")
    assert resp.status_code == 401


def test_delete_with_expired_token_is_401(client: TestClient):
    recipe_id = _make_recipe(client)
    expired = jwt.encode(
        {
            "sub": ADMIN_USER,
            "role": "admin",
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    resp = client.delete(
        f"/recipes/{recipe_id}", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401


def test_delete_with_wrong_role_is_403(client: TestClient):
    recipe_id = _make_recipe(client)
    viewer = jwt.encode(
        {
            "sub": "someone",
            "role": "viewer",
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    resp = client.delete(
        f"/recipes/{recipe_id}", headers={"Authorization": f"Bearer {viewer}"}
    )
    assert resp.status_code == 403
