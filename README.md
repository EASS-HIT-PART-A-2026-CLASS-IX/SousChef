# 🍳 SousChef

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-FF4B4B?logo=streamlit)](https://streamlit.io/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5--flash-orange?logo=google)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A recipe manager with a **Streamlit UI** and a **FastAPI** backend. Import recipes from any URL (including Instagram, YouTube, Facebook), paste raw text, or create them manually. All AI-extracted content is returned in Hebrew.

---

## ✨ Features

- **Full CRUD** for recipes, ingredients, and steps via a polished Hebrew RTL UI
- **AI import from URL** — paste any recipe link; detects Instagram/Facebook/YouTube automatically
- **AI import from text/image** — paste text or upload a photo; Gemini extracts the recipe
- **AI recipe suggestion** — generate a complete recipe draft with one click
- **AI enhance tips** — get improvement suggestions for any saved recipe
- **AI search** — ask in natural language what to cook and get a recommendation from your saved recipes
- **Category filtering** and **full-text search** on the recipe grid
- **JWT authentication** — bcrypt-hashed admin credential, a `/token` endpoint, and a role-gated `DELETE /recipes/{id}`
- **Async refresh worker** — a Redis-backed background service that pre-warms AI enhancement tips with bounded concurrency, retries, and idempotency
- **Docker Compose** — full stack (backend, frontend, Redis, worker) with a single command

---

## 🗂️ Project Structure

```
souschef/
├── backend/                    # FastAPI REST API
│   ├── app/
│   │   ├── main.py             # All routes
│   │   ├── models.py           # SQLModel table models
│   │   ├── schemas.py          # Pydantic request/response schemas
│   │   ├── database.py         # SQLite engine + session dependency
│   │   ├── ai.py               # Gemini integration + scraping strategies
│   │   ├── social.py           # Social media extractor (yt-dlp)
│   │   ├── auth.py             # JWT issuance/validation + bcrypt hashing
│   │   └── observability.py    # Structured logging
│   ├── tests/
│   │   ├── test_recipes.py     # CRUD + AI import tests (in-memory DB, mocked AI)
│   │   ├── test_auth.py        # JWT auth tests
│   │   └── test_refresh.py     # Async refresh worker tests (anyio)
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                   # Streamlit UI
│   ├── main.py                 # Entry point
│   ├── .streamlit/
│   │   └── config.toml         # Pinned light theme for the cream RTL UI
│   ├── app/
│   │   ├── config.py           # Constants and env vars
│   │   ├── styles.py           # CSS / theming
│   │   ├── api_client.py       # HTTP helpers wrapping the backend API
│   │   ├── state.py            # Session-state helpers and navigation
│   │   ├── components.py       # Shared UI components (header, cards, drawer)
│   │   └── pages/
│   │       ├── recipes.py      # Recipe grid + AI search
│   │       ├── create.py       # Create / AI-suggest recipe
│   │       ├── url_import.py   # Import from URL
│   │       └── text_import.py  # Import from text / image
│   ├── Dockerfile
│   └── pyproject.toml
├── tests/
│   └── e2e/                    # Playwright end-to-end tests
│       ├── test_ui.py
│       ├── conftest.py         # Spins up backend + frontend per session
│       └── mock_ollama.py      # Mock AI server for offline testing
├── scripts/
│   ├── refresh.py              # Async Redis-backed refresh worker
│   └── demo.sh                 # 2-minute end-to-end demo script
├── docs/
│   ├── EX3-notes.md            # Architecture, refresh trace, JWT rotation
│   └── runbooks/compose.md     # Compose operations runbook
├── compose.yaml
└── .env.example
```

---

## 🚀 Running Locally (two terminals)

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A free [Gemini API key](https://aistudio.google.com/app/apikey)

### 1. Configure environment

```bash
cp .env.example .env
# Open .env and set: GEMINI_API_KEY=your_actual_key_here
```

### 2. Start the backend (terminal 1)

```bash
cd backend
uv sync --extra dev
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
uvicorn app.main:app --reload
```

The API will be available at **http://localhost:8000** (Swagger UI at `/docs`).

### 3. Start the frontend (terminal 2)

```bash
cd frontend
uv sync
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
streamlit run main.py
```

The UI will open at **http://localhost:8501**.

Both services communicate over `http://localhost:8000` by default. Override with `API_BASE_URL=http://...` if your backend runs on a different port.

---

## 🐳 Docker (full stack)

```bash
cp .env.example .env           # set GEMINI_API_KEY + ADMIN_PASSWORD_HASH first
docker compose up --build
```

The stack runs four services:

| Service | Description | URL |
|---|---|---|
| `frontend` | Streamlit UI | http://localhost:8501 |
| `backend` | FastAPI (REST + Swagger) | http://localhost:8000/docs |
| `redis` | Idempotency store for the worker | `localhost:6379` |
| `worker` | Async refresh worker (`scripts/refresh.py`) | — |

The SQLite database is persisted to `./data/recipes.db` and Redis data to a named volume.

> Generate the admin password hash for `.env` with:
> ```bash
> cd backend && python -c "from app import auth; print(auth.hash_password('admin'))"
> ```

See [`docs/runbooks/compose.md`](docs/runbooks/compose.md) for operations (health checks, running the worker manually, running tests in Docker) and [`docs/EX3-notes.md`](docs/EX3-notes.md) for the architecture and JWT rotation steps. A quick end-to-end walkthrough is available via `bash scripts/demo.sh`.

---

## 🦙 Running with a local AI (no API key)

### Option A — Ollama

[Ollama](https://ollama.com/) lets you run the AI features entirely offline.

#### 1. Install Ollama and pull a model

```bash
# macOS
brew install ollama
ollama pull gemma4:26b      # vision-capable; needed for image upload
```

> Any vision-capable model works. `gemma4:26b` is the tested default.
> For a faster but less accurate option try `llava:13b`.

#### 2. Configure `.env`

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:26b
# OLLAMA_TIMEOUT=180        # increase if generation times out
```

#### 3. Start everything

**Local (two terminals):**
```bash
# terminal 1 — backend
cd backend && uvicorn app.main:app --reload

# terminal 2 — frontend
cd frontend && streamlit run main.py
```

**Docker — set `OLLAMA_BASE_URL` if Ollama runs on the host:**
```bash
# In .env, set:
# OLLAMA_BASE_URL=http://host.docker.internal:11434
docker compose up --build
```

---

### Option B — llama.cpp (llama-server)

llama.cpp's `llama-server` exposes an OpenAI-compatible API that SousChef talks to directly.

#### 1. Build or install llama-server

```bash
# macOS (Homebrew)
brew install llama.cpp

# or build from source:
# https://github.com/ggml-org/llama.cpp#build
```

#### 2. Download a GGUF model and start the server

```bash
# Example: Llama 3.2 Vision (supports image upload)
llama-server -m llama-3.2-11b-vision-instruct-q4_k_m.gguf \
             --port 8080 --ctx-size 4096
```

> For image upload support (`/recipes/from-text` with a photo) the model must be vision-capable.
> Text-only models work fine for all other features.

#### 3. Configure `.env`

```env
AI_PROVIDER=llamacpp
LLAMACPP_BASE_URL=http://localhost:8080
# LLAMACPP_MAX_TOKENS=900
# LLAMACPP_TIMEOUT=180
```

#### 4. Start the backend and frontend

```bash
# terminal 1
cd backend && uvicorn app.main:app --reload

# terminal 2
cd frontend && streamlit run main.py
```

**Docker — set `LLAMACPP_BASE_URL` if llama-server runs on the host:**
```bash
# In .env, set:
# LLAMACPP_BASE_URL=http://host.docker.internal:8080
docker compose up --build
```

---

## 🧪 Tests

### Backend unit tests (no API key or network needed)

```bash
cd backend
pytest                                              # all tests (CRUD, AI import, auth, worker)
pytest tests/test_auth.py -v                        # JWT auth suite
pytest tests/test_refresh.py -v                     # async refresh worker (anyio)
```

All external calls (Gemini, httpx, Redis) are mocked, so no network or API key is needed.

### End-to-end UI tests (Playwright)

```bash
cd tests/e2e
pip install -r requirements.txt
playwright install chromium
pytest                          # runs with mock AI by default
E2E_HEADED=1 pytest             # headed Chromium
```

The e2e suite boots the backend and frontend automatically and generates an HTML report in `tests/e2e/artifacts/latest/index.html`.

---

## 📡 API Reference

### Recipes

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes` | `201` | Create a recipe (with optional nested ingredients & steps) |
| `GET` | `/recipes` | `200` | List all recipes — filter with `?category=<value>` |
| `GET` | `/recipes/{id}` | `200` | Get a single recipe with ingredients and steps |
| `PUT` | `/recipes/{id}` | `200` | Partially update a recipe's fields |
| `DELETE` | `/recipes/{id}` | `204` | Delete a recipe (cascades). **Requires a Bearer admin token** |

### Auth

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/token` | `200` | Exchange admin `username` + `password` (form fields) for a JWT (`{"access_token", "token_type"}`) |

Protected routes expect an `Authorization: Bearer <token>` header; the token must carry `role: "admin"` (otherwise `401`/`403`).

### Ingredients & Steps

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes/{id}/ingredients` | `201` | Add an ingredient |
| `DELETE` | `/ingredients/{id}` | `204` | Remove an ingredient |
| `POST` | `/recipes/{id}/steps` | `201` | Add a step |
| `DELETE` | `/steps/{id}` | `204` | Remove a step |

### AI Endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes/from-url` | `201` | Import and save a recipe from a URL |
| `POST` | `/recipes/from-url/preview` | `200` | Extract a recipe from a URL without saving |
| `POST` | `/recipes/from-text` | `201` | Import from text / image upload |
| `GET` | `/recipes/{id}/enhance` | `200` | Get AI improvement tips for a recipe |
| `POST` | `/recipes/recommend` | `200` | Recommend a recipe from your list based on a query |
| `POST` | `/recipes/suggest/stage` | `200` | Generate one stage of a recipe draft |

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and edit as needed. The key choice is `AI_PROVIDER`.

### AI provider

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `gemini` | `gemini` (cloud), `ollama` (local), or `llamacpp` (local) |

### Gemini (cloud) — `AI_PROVIDER=gemini`

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Get one free at [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `GEMINI_MODEL` | No | Override model (default: `gemini-2.5-flash`) |

### Ollama (local) — `AI_PROVIDER=ollama`

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama daemon URL. Use `http://host.docker.internal:11434` when the backend runs in Docker and Ollama is on the host |
| `OLLAMA_MODEL` | `gemma4:26b` | Model to use. Must be vision-capable for image uploads (`/recipes/from-text`) |
| `OLLAMA_TIMEOUT` | `180` | Seconds before a request times out — local generation can be slow |

### llama.cpp (local) — `AI_PROVIDER=llamacpp`

| Variable | Default | Description |
|----------|---------|-------------|
| `LLAMACPP_BASE_URL` | `http://localhost:8080` | llama-server URL. Use `http://host.docker.internal:8080` when the backend runs in Docker |
| `LLAMACPP_MAX_TOKENS` | `900` | Maximum tokens to generate |
| `LLAMACPP_TIMEOUT` | `180` | Request timeout in seconds |

### Frontend / ports

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:8000` | Frontend → backend base URL |
| `AI_IMPORT_TIMEOUT` | `180` | Frontend-side timeout for AI import requests |
| `BACKEND_PORT` | `8000` | Backend port (Docker Compose) |
| `FRONTEND_PORT` | `8501` | Frontend port (Docker Compose) |

### Auth (JWT)

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | `change-me-in-production` | HMAC secret used to sign/verify tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `30` | Token lifetime in minutes |
| `ADMIN_USERNAME` | `admin` | Admin username for `/token` |
| `ADMIN_PASSWORD_HASH` | — | bcrypt hash of the admin password (backend validates against this) |
| `ADMIN_PASSWORD` | — | Plaintext admin password, used **only by the frontend** to obtain a token for protected calls (must match `ADMIN_PASSWORD_HASH`) |

### Redis + async refresh worker

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection (Compose sets `redis://redis:6379`) |
| `REFRESH_CONCURRENCY` | `5` | Max recipes refreshed concurrently |
| `REFRESH_TTL` | `3600` | Idempotency key TTL in seconds |
| `REFRESH_INTERVAL` | `300` | Seconds the worker sleeps between refresh cycles |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| UI | [Streamlit](https://streamlit.io/) |
| API | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| ORM | [SQLModel](https://sqlmodel.tiangolo.com/) (SQLAlchemy + Pydantic) |
| Database | SQLite |
| Cache / idempotency | [Redis](https://redis.io/) (async client) |
| Auth | [PyJWT](https://pyjwt.readthedocs.io/) + [bcrypt](https://github.com/pyca/bcrypt/) |
| AI — cloud | [Google Gemini 2.5 Flash](https://ai.google.dev/) via `google-genai` |
| AI — local | [Ollama](https://ollama.com/) · [llama.cpp](https://github.com/ggml-org/llama.cpp) (llama-server) |
| HTML parsing | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| Social media | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| HTTP client | [httpx](https://www.python-httpx.org/) (backend) · [requests](https://requests.readthedocs.io/) (frontend) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Testing | [pytest](https://pytest.org/) + [Playwright](https://playwright.dev/python/) |
| Containerisation | Docker + Docker Compose |

---

## 📄 License

MIT
