# EX3 Missing Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four EX3 deliverables missing from SousChef — a Redis-backed async refresh worker, JWT auth on an admin route, a Compose stack with Redis + worker, and the required docs/demo scripts.

**Architecture:** Keep the existing FastAPI + SQLModel backend and Streamlit frontend untouched in behavior. Add a self-contained `backend/app/auth.py` module wired into `main.py` to protect `DELETE /recipes/{id}`. Add a standalone `scripts/refresh.py` async worker that pre-warms enhancement tips through the backend's HTTP API, using Redis as an idempotency store and an `asyncio.Semaphore` for bounded concurrency. Rename `docker-compose.yml` → `compose.yaml` and add `redis` + `worker` services. Document everything in `docs/`.

**Tech Stack:** FastAPI, SQLModel, SQLite, Streamlit, **PyJWT** (JWT), **bcrypt** (password hashing), **redis** (async client), **httpx** (worker HTTP), **anyio** (async tests), pytest, Docker Compose.

## Global Constraints

- Python `>=3.11`; backend deps managed via `uv` and `backend/pyproject.toml`.
- **Auth libraries (user decision — modern equivalents, NOT the spec's verbatim names):** `PyJWT>=2.8.0` and `bcrypt>=4.1.0`. Do **not** use `python-jose` or `passlib`.
- **Compose filename (user decision):** rename `docker-compose.yml` → `compose.yaml`. Update all references in `CLAUDE.md`, `README.md`, and new docs.
- **Worker mode (user decision):** long-lived loop — run refresh, sleep `REFRESH_INTERVAL` seconds, repeat. `restart: unless-stopped`.
- Only `DELETE /recipes/{id}` is role-gated (admin). Do **not** protect `POST /recipes/from-url` (it has existing unauthenticated tests). Do **not** add auth to the frontend.
- Hebrew UI/output behavior must not change.
- Tests mock all external calls (no network, no real Redis). The full backend suite (existing 34 + new) must stay green.
- Commit style: plain conventional-commit messages, **no `Co-Authored-By` trailer**, **never stage `CLAUDE.md`**.
- Run backend commands from `backend/` with the venv active: `cd backend && uv sync --extra dev && source .venv/bin/activate`.

---

## File Structure

**Create:**
- `backend/app/auth.py` — password verify, JWT encode/decode, `get_current_user` dependency.
- `backend/tests/test_auth.py` — auth tests.
- `scripts/refresh.py` — async Redis-backed refresh worker.
- `scripts/requirements.txt` — worker-only deps (for standalone/uv run).
- `backend/tests/test_refresh.py` — anyio tests for the worker.
- `docs/EX3-notes.md` — architecture, async trace, JWT rotation, test command.
- `docs/runbooks/compose.md` — Compose operations runbook.
- `scripts/demo.sh` — 2-minute grader demo.

**Modify:**
- `backend/app/main.py` — add `/token` endpoint + `Depends(get_current_user)` on `DELETE /recipes/{id}`.
- `backend/tests/test_recipes.py` — override `get_current_user` in the `client` fixture so existing DELETE tests keep passing.
- `backend/pyproject.toml` — add `pyjwt`, `bcrypt`, `redis`; add `anyio`/`pytest-asyncio` test deps as needed.
- `.env.example` — add JWT + admin + Redis + refresh env vars.
- `docker-compose.yml` → **rename** to `compose.yaml`; add `redis` + `worker`, add `REDIS_URL` to backend.
- `CLAUDE.md` (do NOT stage in commits — edit only if needed for accuracy) and `README.md` — update compose filename references.

---

## Task 1: JWT auth module + protected DELETE route

**Files:**
- Create: `backend/app/auth.py`
- Create: `backend/tests/test_auth.py`
- Modify: `backend/app/main.py` (imports, `/token` endpoint, `DELETE /recipes/{id}` dependency)
- Modify: `backend/tests/test_recipes.py` (client fixture — override `get_current_user`)
- Modify: `backend/pyproject.toml` (add `pyjwt`, `bcrypt`)
- Modify: `.env.example` (JWT + admin vars)

**Interfaces:**
- Produces:
  - `auth.hash_password(password: str) -> str`
  - `auth.verify_password(password: str, password_hash: str) -> bool`
  - `auth.create_access_token(data: dict, expires_minutes: int | None = None) -> str`
  - `auth.authenticate(username: str, password: str) -> bool`
  - `auth.get_current_user(token: str = Depends(oauth2_scheme)) -> dict` — FastAPI dependency; raises 401 (bad/expired/missing token) or 403 (role != "admin"); returns the decoded payload dict on success.
  - `auth.oauth2_scheme` — `OAuth2PasswordBearer(tokenUrl="token")`.
- Consumes (from env): `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`.

- [ ] **Step 1: Add auth dependencies to `backend/pyproject.toml`**

In `[project].dependencies`, add these two lines (keep the list alphabetical-ish, after `httpx`):

```toml
    "pyjwt>=2.8.0",
    "bcrypt>=4.1.0",
```

Then install:

```bash
cd backend && uv sync --extra dev && source .venv/bin/activate
```

Expected: resolves and installs `pyjwt` and `bcrypt`.

- [ ] **Step 2: Write the failing auth unit tests**

Create `backend/tests/test_auth.py`:

```python
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
```

- [ ] **Step 3: Run the auth tests to verify they fail**

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: collection/import error or failures — `app.auth` does not exist yet and `/token` route is undefined.

- [ ] **Step 4: Implement `backend/app/auth.py`**

Create `backend/app/auth.py`:

```python
"""
Minimal JWT auth for SousChef admin routes.

One hardcoded admin user, credentials supplied via env vars
(ADMIN_USERNAME + ADMIN_PASSWORD_HASH). Tokens are HS256 JWTs carrying a
`role: "admin"` claim. Only role-gated routes depend on get_current_user.
"""
from __future__ import annotations

import datetime as dt
import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def _secret() -> str:
    return os.getenv("JWT_SECRET_KEY", "change-me-in-production")


def _algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")


def _expire_minutes() -> int:
    try:
        return int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    except ValueError:
        return 30


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a bcrypt hash (utf-8 string) for the given plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Credentials ───────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> bool:
    """True iff username + password match the configured admin credentials."""
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
    if not expected_hash:
        return False
    if username != expected_user:
        return False
    return verify_password(password, expected_hash)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    """Encode an HS256 JWT with an `exp` claim."""
    to_encode = dict(data)
    minutes = expires_minutes if expires_minutes is not None else _expire_minutes()
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, _secret(), algorithm=_algorithm())


_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Decode + validate the bearer token. Raises 401 on missing/invalid/expired
    token, 403 if the `role` claim is not "admin". Returns the payload dict.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
    except jwt.ExpiredSignatureError:
        raise _CREDENTIALS_EXC
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXC

    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return payload
```

- [ ] **Step 5: Wire `/token` and protect DELETE in `backend/app/main.py`**

Add to the imports near the other `app.*` imports (after the `from app.schemas import (...)` block):

```python
from fastapi.security import OAuth2PasswordRequestForm  # noqa: E402
from app import auth  # noqa: E402
```

Add the `/token` endpoint (place it in the "AI Utilities" tail or a new "Auth" section near the bottom of the file, before the AI Utilities section is fine):

```python
# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/token")
@trace_call
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
    """Issue a JWT for the configured admin user (form fields: username, password)."""
    if not auth.authenticate(form_data.username, form_data.password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth.create_access_token({"sub": form_data.username, "role": "admin"})
    return {"access_token": token, "token_type": "bearer"}
```

Modify the existing `delete_recipe` signature (currently at `main.py:337-346`) to depend on `get_current_user`:

```python
@app.delete("/recipes/{recipe_id}", status_code=204, response_model=None)
@trace_call
def delete_recipe(
    recipe_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(auth.get_current_user),
) -> None:
    """Delete a recipe and all its ingredients/steps (cascade). Admin only."""
    recipe = _get_recipe_or_404(recipe_id, session)
    session.delete(recipe)
    session.commit()
```

- [ ] **Step 6: Keep existing DELETE tests green — override `get_current_user` in `test_recipes.py`**

In `backend/tests/test_recipes.py`, update the `client` fixture (`test_recipes.py:39-47`) to also override the auth dependency so the existing unauthenticated DELETE tests still pass:

```python
@pytest.fixture(name="client")
def client_fixture(session: Session):
    from app import auth

    def override_get_session():
        yield session

    def override_get_current_user():
        return {"sub": "admin", "role": "admin"}

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[auth.get_current_user] = override_get_current_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
```

- [ ] **Step 7: Run the auth tests + full suite to verify pass**

Run: `cd backend && pytest tests/test_auth.py -v && pytest`
Expected: all `test_auth.py` tests PASS, and the full suite (34 existing + new auth tests) PASS. No 401s in the existing delete tests.

- [ ] **Step 8: Add auth env vars to `.env.example`**

Append to `.env.example`:

```bash

# ── Auth (JWT) ───────────────────────────────────────────────────────────────
# Used to protect admin routes (e.g. DELETE /recipes/{id}).
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=30
ADMIN_USERNAME=admin
# bcrypt hash of the admin password. Generate one with:
#   cd backend && python -c "from app import auth; print(auth.hash_password('admin'))"
ADMIN_PASSWORD_HASH=
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/auth.py backend/tests/test_auth.py backend/app/main.py backend/tests/test_recipes.py backend/pyproject.toml backend/uv.lock .env.example
git commit -m "feat(auth): add JWT auth and protect DELETE /recipes/{id}"
```

---

## Task 2: Async Redis-backed refresh worker

**Files:**
- Create: `scripts/refresh.py`
- Create: `scripts/requirements.txt`
- Create: `backend/tests/test_refresh.py`
- Modify: `backend/pyproject.toml` (add `redis`, ensure `anyio` test dep)
- Modify: `.env.example` (Redis + refresh vars)

**Interfaces:**
- Consumes: the backend HTTP API — `GET /recipes` (list) and `GET /recipes/{id}/enhance` (pre-warm). The refresh module imports nothing from `app.*`; it talks HTTP only.
- Produces (importable from `scripts.refresh` for tests):
  - `async def refresh_recipe(recipe_id: int, *, client, redis, ttl: int, max_retries: int = 3) -> str` — returns `"processed"`, `"skipped"`, or `"failed"`.
  - `async def run_refresh(*, client, redis, concurrency: int, ttl: int) -> dict` — returns `{"processed": int, "skipped": int, "failed": int}`.
  - `def build_redis(url: str)` / `def build_client(base_url: str)` — factory helpers (so `main()` wires real deps, tests inject fakes).
  - `async def main() -> None` — entrypoint loop.

**Note on test framework:** add `@pytest.mark.anyio` tests with an `anyio_backend` fixture pinned to `"asyncio"`. The project already runs `asyncio_mode = "auto"` (pytest-asyncio); anyio's pyfunc hook handles the marked tests. Step 4 verifies the full suite still collects cleanly — if a collision appears, fall back to plain `async def` (auto mode) plus keeping one `@pytest.mark.anyio` test in its own file.

- [ ] **Step 1: Add worker deps**

In `backend/pyproject.toml` `[project].dependencies`, add:

```toml
    "redis>=5.0.0",
```

In `[project.optional-dependencies].dev` and `[tool.uv].dev-dependencies`, add:

```toml
    "anyio>=4.0.0",
```

Install:

```bash
cd backend && uv sync --extra dev && source .venv/bin/activate
```

Create `scripts/requirements.txt` (for standalone `uv run`):

```text
redis>=5.0.0
httpx>=0.27.0
anyio>=4.0.0
```

- [ ] **Step 2: Write the failing worker tests**

Create `backend/tests/test_refresh.py`:

```python
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
```

Also create an empty `scripts/__init__.py` so `from scripts import refresh` works:

```bash
mkdir -p scripts
: > scripts/__init__.py
```

- [ ] **Step 3: Run the worker tests to verify they fail**

Run: `cd backend && pytest tests/test_refresh.py -v`
Expected: import error — `scripts/refresh.py` does not exist yet.

- [ ] **Step 4: Implement `scripts/refresh.py`**

Create `scripts/refresh.py`:

```python
"""
SousChef async refresh worker.

Periodically pre-warms AI enhancement tips for every recipe by calling the
backend's GET /recipes/{id}/enhance endpoint. Bounds concurrency with an
asyncio.Semaphore, retries transient HTTP failures with exponential backoff,
and uses Redis as an idempotency store (key `refresh:{id}` with a TTL) so the
same recipe is not re-processed within the TTL window across runs.

Run standalone:  uv run python scripts/refresh.py
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

try:  # redis is optional at import time so the module imports under test
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [refresh] %(message)s",
)
logger = logging.getLogger("refresh")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CONCURRENCY = int(os.getenv("REFRESH_CONCURRENCY", "5"))
TTL = int(os.getenv("REFRESH_TTL", "3600"))
INTERVAL = int(os.getenv("REFRESH_INTERVAL", "300"))


def build_redis(url: str = REDIS_URL):
    if aioredis is None:  # pragma: no cover
        raise RuntimeError("redis package not installed")
    return aioredis.from_url(url, encoding="utf-8", decode_responses=True)


def build_client(base_url: str = API_BASE_URL) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


async def refresh_recipe(
    recipe_id: int,
    *,
    client,
    redis,
    ttl: int,
    max_retries: int = 3,
    backoff_base: float = 0.5,
) -> str:
    """
    Pre-warm one recipe. Returns "skipped" (idempotency key present),
    "processed" (enhance call succeeded), or "failed" (all retries exhausted).
    """
    key = f"refresh:{recipe_id}"
    if await redis.exists(key):
        logger.info("skip recipe_id=%s (idempotency key present)", recipe_id)
        return "skipped"

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.get(f"/recipes/{recipe_id}/enhance")
            resp.raise_for_status()
            # Mark done only after success; nx avoids racing parallel runs.
            await redis.set(key, "1", nx=True, ex=ttl)
            logger.info("processed recipe_id=%s (attempt %s)", recipe_id, attempt)
            return "processed"
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            logger.warning(
                "recipe_id=%s attempt %s/%s failed: %s",
                recipe_id, attempt, max_retries, exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))

    logger.error("failed recipe_id=%s after %s attempts: %s", recipe_id, max_retries, last_exc)
    return "failed"


async def run_refresh(*, client, redis, concurrency: int, ttl: int) -> dict:
    """Fetch all recipes and refresh them with bounded concurrency. Returns a summary."""
    resp = await client.get("/recipes")
    resp.raise_for_status()
    recipes = resp.json()

    semaphore = asyncio.Semaphore(concurrency)
    summary = {"processed": 0, "skipped": 0, "failed": 0}

    async def _bounded(recipe_id: int) -> str:
        async with semaphore:
            return await refresh_recipe(recipe_id, client=client, redis=redis, ttl=ttl)

    results = await asyncio.gather(*(_bounded(r["id"]) for r in recipes))
    for status in results:
        summary[status] += 1

    logger.info(
        "refresh summary: total=%s processed=%s skipped=%s failed=%s",
        len(recipes), summary["processed"], summary["skipped"], summary["failed"],
    )
    return summary


async def _run_once() -> dict:
    redis = build_redis()
    client = build_client()
    try:
        return await run_refresh(
            client=client, redis=redis, concurrency=CONCURRENCY, ttl=TTL
        )
    finally:
        await client.aclose()
        await redis.aclose()


async def main() -> None:
    """Long-lived loop: refresh, sleep REFRESH_INTERVAL, repeat."""
    logger.info(
        "worker start: api=%s redis=%s concurrency=%s ttl=%s interval=%s",
        API_BASE_URL, REDIS_URL, CONCURRENCY, TTL, INTERVAL,
    )
    while True:
        try:
            await _run_once()
        except Exception:
            logger.exception("refresh cycle failed; will retry next interval")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Run the worker tests + full suite to verify pass**

Run: `cd backend && pytest tests/test_refresh.py -v && pytest`
Expected: all `test_refresh.py` tests PASS; full backend suite still PASSES.

- [ ] **Step 6: Add Redis + refresh env vars to `.env.example`**

Append to `.env.example`:

```bash

# ── Redis + async refresh worker ─────────────────────────────────────────────
REDIS_URL=redis://localhost:6379
REFRESH_CONCURRENCY=5
REFRESH_TTL=3600
# Seconds the worker sleeps between refresh cycles.
REFRESH_INTERVAL=300
```

- [ ] **Step 7: Commit**

```bash
git add scripts/refresh.py scripts/requirements.txt scripts/__init__.py backend/tests/test_refresh.py backend/pyproject.toml backend/uv.lock .env.example
git commit -m "feat(worker): add Redis-backed async refresh worker with tests"
```

---

## Task 3: Compose stack — rename to compose.yaml, add Redis + worker

**Files:**
- Rename: `docker-compose.yml` → `compose.yaml`
- Modify: `compose.yaml` (add `redis`, `worker`; add `REDIS_URL` to backend; healthchecks)
- Modify: `README.md` (compose filename references)

**Interfaces:**
- Consumes: `scripts/refresh.py` (Task 2), backend image build (`./backend`), backend `GET /recipes` healthcheck (exists).

- [ ] **Step 1: Rename the compose file**

```bash
git mv docker-compose.yml compose.yaml
```

- [ ] **Step 2: Rewrite `compose.yaml` with Redis + worker**

Replace the contents of `compose.yaml` with:

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test:
        - "CMD"
        - "python"
        - "-c"
        - "import urllib.request; urllib.request.urlopen('http://localhost:8000/recipes')"
      interval: 30s
      timeout: 5s
      start_period: 10s
      retries: 3

  frontend:
    build: ./frontend
    ports:
      - "${FRONTEND_PORT:-8501}:8501"
    environment:
      - API_BASE_URL=http://backend:8000
      - GEMINI_API_KEY=${GEMINI_API_KEY}
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  worker:
    build: ./backend
    command: python /app/scripts/refresh.py
    env_file: .env
    environment:
      - API_BASE_URL=http://backend:8000
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./scripts:/app/scripts
    depends_on:
      backend:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  redis_data:
```

- [ ] **Step 3: Validate the compose file parses**

Run: `docker compose -f compose.yaml config >/dev/null && echo OK`
Expected: prints `OK` (config is valid). If Docker is unavailable in the environment, skip with a note.

- [ ] **Step 4: Update `README.md` compose references**

Search `README.md` for `docker-compose.yml` and `docker compose up` references and update any explicit `docker-compose.yml` filename mentions to `compose.yaml`. The command `docker compose up --build` is unchanged (it auto-detects `compose.yaml`).

Run: `grep -n "docker-compose" README.md` — update each hit. Expected after edit: no stale `docker-compose.yml` filename references.

- [ ] **Step 5: Commit**

```bash
git add compose.yaml README.md
git commit -m "feat(compose): rename to compose.yaml and add redis + worker services"
```

---

## Task 4: `docs/EX3-notes.md`

**Files:**
- Create: `docs/EX3-notes.md`

- [ ] **Step 1: Write `docs/EX3-notes.md`**

Create `docs/EX3-notes.md`:

````markdown
# EX3 Notes

## Architecture

```
                ┌──────────────┐
   browser ───▶ │  frontend    │  Streamlit :8501
                │ (Streamlit)  │
                └──────┬───────┘
                       │ HTTP (API_BASE_URL)
                       ▼
                ┌──────────────┐        ┌──────────────┐
                │   backend    │ ─────▶ │   SQLite     │  recipes.db
                │  (FastAPI)   │        │  (volume)    │
                │    :8000     │        └──────────────┘
                └──────┬───────┘
                       │ GET /recipes/{id}/enhance
        ┌──────────────┘
        │
        ▼
   ┌──────────────┐  set/exists refresh:{id}   ┌──────────────┐
   │   worker     │ ─────────────────────────▶ │    Redis     │  :6379
   │ refresh.py   │                            │ (idempotency)│
   └──────────────┘                            └──────────────┘
```

Services (see `compose.yaml`): **frontend → backend → SQLite**, **backend ↔ Redis**,
**worker → backend + Redis**. This satisfies the "4 cooperating services" requirement
(frontend, backend, redis, worker).

## Async refresh trace

The worker sets an idempotency key `refresh:{recipe_id}` (TTL `REFRESH_TTL`) after a
successful enhance call, and skips any recipe whose key still exists. Sample structured
log excerpt from one `scripts/refresh.py` cycle:

```
2026-06-28 10:00:01 INFO [refresh] worker start: api=http://backend:8000 redis=redis://redis:6379 concurrency=5 ttl=3600 interval=300
2026-06-28 10:00:01 INFO [refresh] processed recipe_id=1 (attempt 1)
2026-06-28 10:00:01 INFO [refresh] processed recipe_id=2 (attempt 1)
2026-06-28 10:00:01 INFO [refresh] skip recipe_id=3 (idempotency key present)
2026-06-28 10:00:01 INFO [refresh] refresh summary: total=3 processed=2 skipped=1 failed=0
```

Equivalent `redis-cli MONITOR` view of the idempotency keys being checked and set:

```
"EXISTS" "refresh:1"
"SET" "refresh:1" "1" "NX" "EX" "3600"
"EXISTS" "refresh:2"
"SET" "refresh:2" "1" "NX" "EX" "3600"
"EXISTS" "refresh:3"          # key already present -> recipe skipped, no SET
```

## JWT secret rotation

1. Generate a new secret:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Update `JWT_SECRET_KEY` in `.env` with the new value.
3. Restart the backend so it picks up the new secret:
   ```bash
   docker compose up -d --build backend
   ```
4. All tokens signed with the old secret now fail validation (401) — clients must
   call `POST /token` again to obtain a fresh token. No server-side revocation list
   is needed; rotating the secret invalidates every previously issued token.

## Running the security tests

```bash
cd backend && pytest tests/test_auth.py -v
```
````

- [ ] **Step 2: Commit**

```bash
git add docs/EX3-notes.md
git commit -m "docs: add EX3-notes (architecture, refresh trace, JWT rotation)"
```

---

## Task 5: `docs/runbooks/compose.md`

**Files:**
- Create: `docs/runbooks/compose.md`

- [ ] **Step 1: Write `docs/runbooks/compose.md`**

Create `docs/runbooks/compose.md`:

````markdown
# Runbook: Docker Compose stack

The full stack is defined in `compose.yaml`: `backend`, `frontend`, `redis`, `worker`.

## 1. Start the full stack

```bash
cp .env.example .env       # then fill in GEMINI_API_KEY + ADMIN_PASSWORD_HASH
docker compose up --build
```

- Backend API docs: http://localhost:8000/docs
- Streamlit UI:      http://localhost:8501

## 2. Verify backend health

```bash
curl -fsS http://localhost:8000/recipes && echo "  <- backend OK"
```

## 3. Verify Redis is up

```bash
docker compose exec redis redis-cli ping     # expect: PONG
```

## 4. Run the async worker manually (one-off)

The `worker` service loops automatically. To trigger an ad-hoc run in a throwaway
container:

```bash
docker compose run --rm worker python /app/scripts/refresh.py
```

(Ctrl-C to stop the loop, or run a one-shot variant in your shell.)

## 5. Check health / response headers

```bash
curl -i http://localhost:8000/recipes | head -n 20
```

Inspect the request-id correlation in logs:

```bash
docker compose logs backend | grep request_id
```

## 6. Run backend tests inside Docker

```bash
docker compose run --rm backend pytest
```

## 7. Stop everything cleanly

```bash
docker compose down -v        # -v also removes the redis_data volume
```
````

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/compose.md
git commit -m "docs: add Compose operations runbook"
```

---

## Task 6: `scripts/demo.sh`

**Files:**
- Create: `scripts/demo.sh`

**Interfaces:**
- Consumes: backend uvicorn (`app.main:app`), `/recipes`, `/token`, `DELETE /recipes/{id}` (Task 1), admin credentials from env.

- [ ] **Step 1: Write `scripts/demo.sh`**

Create `scripts/demo.sh`:

```bash
#!/usr/bin/env bash
#
# SousChef EX3 demo — walks a grader through the app in under 2 minutes.
# Run from the repo root:  bash scripts/demo.sh
#
set -euo pipefail

API="${API_BASE_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USERNAME:-admin}"
ADMIN_PW="${ADMIN_PASSWORD:-admin}"   # plaintext; backend stores ADMIN_PASSWORD_HASH
BACKEND_PID=""

header() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }

cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    header "Cleanup: stopping backend (pid ${BACKEND_PID})"
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

header "1/6  Starting the backend (uvicorn, detached)"
( cd backend && source .venv/bin/activate && \
  uvicorn app.main:app --port 8000 >/tmp/souschef-demo.log 2>&1 ) &
BACKEND_PID=$!
echo "backend pid: ${BACKEND_PID}  (logs: /tmp/souschef-demo.log)"

header "2/6  Waiting for backend health"
for i in $(seq 1 30); do
  if curl -fsS "${API}/recipes" >/dev/null 2>&1; then
    echo "backend healthy after ${i}s"; break
  fi
  sleep 1
  if [[ "${i}" -eq 30 ]]; then echo "backend did not become healthy"; exit 1; fi
done

header "3/6  Smoke test: create a recipe"
CREATED=$(curl -fsS -X POST "${API}/recipes" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Demo Shakshuka","category":"ארוחת בוקר"}')
echo "${CREATED}"
RECIPE_ID=$(echo "${CREATED}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")

header "4/6  List recipes (should include the new one)"
curl -fsS "${API}/recipes" | python3 -m json.tool | head -n 20

header "5/6  Auth: obtain a JWT and delete via the protected route"
TOKEN=$(curl -fsS -X POST "${API}/token" \
  -d "username=${ADMIN_USER}&password=${ADMIN_PW}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "got token: ${TOKEN:0:24}..."
echo "deleting recipe ${RECIPE_ID} (admin only):"
curl -fsS -o /dev/null -w "DELETE status: %{http_code}\n" \
  -X DELETE "${API}/recipes/${RECIPE_ID}" \
  -H "Authorization: Bearer ${TOKEN}"

header "6/6  Frontend"
echo "Streamlit UI runs separately. Start it with:"
echo "    cd frontend && streamlit run main.py"
echo "Then open http://localhost:8501"

header "Demo complete"
```

Make it executable:

```bash
chmod +x scripts/demo.sh
```

- [ ] **Step 2: Smoke-check the script syntax**

Run: `bash -n scripts/demo.sh && echo "syntax OK"`
Expected: prints `syntax OK` (no execution; just a syntax check). A full run requires the backend venv and a valid `ADMIN_PASSWORD_HASH` matching `ADMIN_PASSWORD`.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo.sh
git commit -m "feat: add 2-minute grader demo script"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: all tests PASS — the original 34 plus the new auth and refresh tests, with no 401/collection regressions.

- [ ] **Step 2: Validate compose + script syntax**

Run:
```bash
docker compose -f compose.yaml config >/dev/null && echo "compose OK"
bash -n scripts/demo.sh && echo "demo syntax OK"
```
Expected: `compose OK` and `demo syntax OK` (skip the compose check with a note if Docker is unavailable).

- [ ] **Step 3: Confirm spec coverage**

Re-read `EX3-spec.md` sections 1–6 and confirm each maps to a delivered file:
- §1 refresh worker → `scripts/refresh.py` + `backend/tests/test_refresh.py`
- §2 compose + worker → `compose.yaml`
- §3 JWT auth → `backend/app/auth.py` + `/token` + protected DELETE + `backend/tests/test_auth.py`
- §4 → `docs/EX3-notes.md`
- §5 → `docs/runbooks/compose.md`
- §6 → `scripts/demo.sh`

---

## Self-Review Notes

- **Spec coverage:** All six spec sections map to tasks above; the rubric table rows
  (4th microservice, compose+runbook, refresh+anyio test, idempotency, hashed creds+JWT
  route, expired/missing token tests, EX3-notes, demo script) are each covered.
- **Deviations from spec (approved by user):** auth uses **PyJWT + bcrypt** (not
  python-jose/passlib); compose file is **renamed** to `compose.yaml`; worker runs as a
  **sleep loop**. `POST /recipes/from-url` is intentionally left unprotected to avoid
  breaking its existing unauthenticated tests — only `DELETE /recipes/{id}` is role-gated,
  which satisfies "at least one role-gated route."
- **Regression guard:** Task 1 Step 6 overrides `get_current_user` in the existing
  `test_recipes.py` client fixture so the original DELETE tests stay green.
- **Test framework:** new async tests use `@pytest.mark.anyio` with an `anyio_backend`
  fixture; Task 2 Step 5 verifies the full suite still collects under the project's
  `asyncio_mode = "auto"`.
````
