# SousChef — End-to-End Tests

Playwright-driven browser tests that boot the real backend + Streamlit frontend
and exercise the app top-to-bottom, including CRUD flows, AI-assisted flows,
imports, drawer interactions, and visual validation artifacts.

## Install

```bash
# 1. Backend deps (if not already installed)
cd backend && uv sync --extra dev && cd ..

# 2. e2e deps
pip install -r tests/e2e/requirements.txt
playwright install chromium
```

## Run

The tests are driven by two environment variables:

| Var            | Values                | Default                        | What it does                                             |
|----------------|-----------------------|--------------------------------|----------------------------------------------------------|
| `E2E_AI_MODE`  | `mock` \| `ollama`    | `mock`                         | `mock` boots a fake Ollama server; `ollama` uses a real one |
| `OLLAMA_BASE_URL` | URL                | `http://localhost:11434`       | Only used when `E2E_AI_MODE=ollama`                      |
| `OLLAMA_MODEL`    | model id           | `gemma4:26b`                   | Only used when `E2E_AI_MODE=ollama`                      |
| `E2E_HEADED`   | `1` to show browser   | unset (headless)               | Watch the tests run in a real Chromium window            |

```bash
# Default — fast, deterministic, no model needed
pytest tests/e2e

# Hit a real local Ollama
E2E_AI_MODE=ollama OLLAMA_MODEL=llama3.1:8b pytest tests/e2e

# Watch the browser
E2E_HEADED=1 pytest tests/e2e -k test_nav_switches_pages
```

## What's covered

- Header brand + recipe-count pill rendering
- Navigation between all four pages (recipes / create / URL import / text import)
- Empty-state message when DB has no recipes
- Manual recipe creation, validation, and drawer verification
- Category-pill filter narrowing the grid
- Search box filtering by name
- Recipe drawer open / close / edit / delete flows
- AI search, AI suggest, and AI improve flows
- Text import, image import, and URL import flows
- AI retry behavior for staged suggestion generation

## Visual report

Each run generates a self-contained HTML report plus screenshots at:

```bash
tests/e2e/artifacts/latest/index.html
```

Related artifacts written beside it:

- `tests/e2e/artifacts/latest/report.json` — machine-readable run summary
- `tests/e2e/artifacts/latest/screenshots/` — per-test visual checkpoints and final-state captures

Open the HTML file in a browser after the run to review pass/fail status and
the captured screenshots for each test.

## How it works

`conftest.py` spins up three subprocesses per test session:

1. **Mock Ollama** (only when `E2E_AI_MODE=mock`) — a tiny FastAPI app on a free port
   that emulates `POST /api/generate` and returns canned recipes / Hebrew text based
   on prompt content.
2. **Backend** — `uvicorn app.main:app` on a free port, with a temp SQLite DB and
   `AI_PROVIDER=ollama` pointed at either the mock or the real Ollama.
3. **Frontend** — `streamlit run frontend/main.py` on a free port, with
   `API_BASE_URL` pointed at the backend.

All three are torn down after the session.
