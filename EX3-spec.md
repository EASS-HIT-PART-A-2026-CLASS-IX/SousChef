# SousChef – EX3 Missing Features Spec

## Context

SousChef is a recipe manager built across EX1 and EX2 for the EASS 2026 course.
It is a Hebrew-language app using FastAPI + SQLModel + SQLite on the backend and
Streamlit on the frontend, with multi-provider AI (Gemini / Ollama / llama.cpp).

**Repo structure:**
```
backend/          FastAPI REST API (port 8000)
  app/
    main.py       All routes
    models.py     SQLModel tables: Recipe, Ingredient, Step
    schemas.py    Pydantic validation + Hebrew category enum
    database.py   SQLite engine + session dependency
    ai.py         Multi-provider AI abstraction
    social.py     yt-dlp social media extraction
    observability.py  Request-ID tracing + @trace_call decorator
  tests/
    test_recipes.py   34 unit tests (mocked, in-memory SQLite)
frontend/         Streamlit UI (port 8501)
  main.py         Entry point + router
  app/
    config.py     Constants, env vars, category colors
    api_client.py HTTP helpers wrapping backend
    state.py      Session-state helpers, URL param sync
    components.py Header, recipe cards, drawer
    styles.py     RTL CSS, Heebo font, category palette
    pages/
      recipes.py      Browse grid + AI search
      create.py       Manual create + AI-suggest flow
      url_import.py   Import from URL
      text_import.py  Import from text/image
tests/e2e/        Playwright browser tests (mock Ollama server)
docker-compose.yml  backend + frontend only (no Redis/worker yet)
.env.example
```

---

## What Already Works (do not reimplement)

- Full CRUD for recipes, ingredients, steps
- AI recipe extraction from URL (3-tier: yt-dlp → JSON-LD → visible text)
- AI recipe extraction from text + image upload
- AI enhancement tips, staged recipe suggestion, natural-language recommendation
- Hebrew RTL Streamlit UI with category filtering and AI search
- 34 backend unit tests (all mocked)
- Playwright E2E suite with mock Ollama server
- Structured logging + request-ID tracing (`observability.py`)
- Docker Compose for backend + frontend

---

## Missing Features to Implement

### 1. Redis + Async Worker (`scripts/refresh.py`)

**What:** A standalone Python script (and optional worker container) that
periodically "refreshes" recipe recommendations in the background. This
demonstrates bounded async concurrency, retries, and Redis-backed idempotency
as required by EX3 / Session 09.

**Files to create:**
- `scripts/refresh.py`
- `backend/tests/test_refresh.py`

**Requirements:**
- Use `asyncio` with a `Semaphore` to bound concurrency (max N concurrent tasks)
- For each recipe in the DB, call the `/recipes/{id}/enhance` endpoint to
  pre-warm enhancement tips
- Use Redis (`redis-py` async client) as an idempotency store: before processing
  a recipe, set a key `refresh:{recipe_id}` with a TTL; skip if key already
  exists (deduplication across runs)
- Retry failed HTTP calls up to 3 times with exponential backoff
- Log a structured summary at the end: total processed, skipped, failed
- Must be runnable as: `uv run python scripts/refresh.py`
- At least one `pytest.mark.anyio` test covering: happy path, idempotency skip,
  retry on transient failure

**Env vars to add to `.env.example`:**
```
REDIS_URL=redis://localhost:6379
REFRESH_CONCURRENCY=5
REFRESH_TTL=3600
```

---

### 2. Redis in Docker Compose + Worker Service

**What:** Extend `docker-compose.yml` (or create `compose.yaml` as the canonical
name) to include Redis and an optional async worker service.

**Requirements for `compose.yaml`:**
- `redis` service: official `redis:7-alpine` image, port 6379, named volume for
  persistence
- `worker` service: runs `python scripts/refresh.py` on a schedule or loop,
  depends on `backend` and `redis`, shares the same backend image/build
- `backend` service: add `REDIS_URL` env var pointing to the Redis service
- Health checks: backend on `GET /recipes`, redis on `redis-cli ping`
- All services should have `restart: unless-stopped`

---

### 3. JWT Authentication + Security Baseline (Session 11)

**What:** Add a minimal auth layer to protect admin-level routes. This is a
hard EX3 requirement.

**Files to modify/create:**
- `backend/app/auth.py` (new)
- `backend/app/main.py` (add protected routes + `/token` endpoint)
- `backend/tests/test_auth.py` (new)

**Requirements:**
- **Password hashing:** use `passlib[bcrypt]` to hash credentials; store one
  hardcoded admin user in env vars (`ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`)
- **JWT issuance:** `POST /token` accepts `username` + `password` form fields,
  returns `{"access_token": "...", "token_type": "bearer"}` using `python-jose`
- **JWT validation:** a `get_current_user` FastAPI dependency that decodes the
  token, checks expiry, checks role claim
- **Protected routes:** wrap `DELETE /recipes/{id}` (and optionally
  `POST /recipes/from-url`) with the `get_current_user` dependency — graders
  must see at least one role-gated route
- **Role check:** JWT payload must contain `role: "admin"`; return 403 if role
  is missing or wrong
- **Token settings (env vars):**
  ```
  JWT_SECRET_KEY=change-me-in-production
  JWT_ALGORITHM=HS256
  JWT_EXPIRE_MINUTES=30
  ADMIN_USERNAME=admin
  ADMIN_PASSWORD_HASH=<bcrypt hash>
  ```
- **Tests (in `test_auth.py`):**
  - Happy path: obtain token, call protected route → 200/204
  - Expired token: manually craft a token with `exp` in the past → 401
  - Missing token: call protected route without header → 401
  - Wrong role: token with `role: "viewer"` → 403
  - Bad password: `POST /token` with wrong password → 401

**Note:** Do NOT add auth to the frontend Streamlit UI — only the backend routes.
The rubric does not require a login screen, just protected API routes.

---

### 4. `docs/EX3-notes.md`

**What:** Required documentation file the rubric explicitly names.

**Contents:**
1. **Architecture diagram** (ASCII or Mermaid) showing all services:
   frontend → backend → SQLite, Redis; worker → Redis + backend
2. **Async refresh trace:** paste a sample Redis `MONITOR` output or structured
   log excerpt showing the idempotency keys being set/checked during a
   `scripts/refresh.py` run
3. **JWT rotation steps:** step-by-step instructions for rotating the
   `JWT_SECRET_KEY` (generate new key, update env, restart backend, invalidate
   old tokens)
4. **Running the security tests:** one-liner command

---

### 5. `docs/runbooks/compose.md`

**What:** Operations runbook required by the EX3 rubric for the Compose setup.

**Contents:**
1. How to start the full stack: `docker compose up --build`
2. How to verify backend health: `curl http://localhost:8000/recipes`
3. How to verify Redis is up: `docker compose exec redis redis-cli ping`
4. How to run the async worker manually: `docker compose run --rm worker`
5. How to check rate-limit / health headers in responses
6. How to run backend tests inside Docker:
   `docker compose run --rm backend pytest`
7. How to stop everything cleanly: `docker compose down -v`

---

### 6. Demo Script (`scripts/demo.sh`)

**What:** A shell script that walks graders through the full app in under 2
minutes. Required by EX3.

**Requirements:**
- Print a header explaining each step before running it
- Start the backend (detached uvicorn) and wait for it to be healthy
- Run a quick smoke test: create a recipe via `curl`, list it, delete it
- Print the Streamlit URL and instructions to open it
- Obtain a JWT token and call a protected route to demonstrate auth
- Clean up (kill background processes) on exit
- Must be runnable as: `bash scripts/demo.sh`

---

## New Dependencies to Add

**Backend (`backend/pyproject.toml`):**
```toml
passlib[bcrypt]>=1.7.4
python-jose[cryptography]>=3.3.0
redis[asyncio]>=5.0.0
anyio>=4.0.0
pytest-anyio>=0.0.0   # or anyio[pytest]
```

**Scripts (`scripts/requirements.txt` or inline with uv):**
```
redis[asyncio]>=5.0.0
httpx>=0.27.0
anyio>=4.0.0
```

---

## Rubric Mapping

| EX3 Requirement | Covered by |
|---|---|
| 3+ cooperating services | backend + SQLite + frontend (existing) |
| 4th microservice | async worker + Redis (new) |
| `compose.yaml` + runbook | items 2 + 5 above |
| `scripts/refresh.py` + anyio test | item 1 above |
| Redis-backed idempotency | item 1 above |
| Hashed credentials + JWT route | item 3 above |
| Tests for expired/missing token | item 3 above |
| `docs/EX3-notes.md` | item 4 above |
| Demo script | item 6 above |
| Enhancement + tests | already done (AI search, import, 34 tests) |

**Bonus (+5 pts):** Record a ≤2 min screen capture of the demo script running
and the Streamlit UI — attach as `docs/demo.mp4` or a shareable link.
