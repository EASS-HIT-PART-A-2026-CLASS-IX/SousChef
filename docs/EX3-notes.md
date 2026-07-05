# EX3 Notes

## Demo video

[`docs/demo.mp4`](demo.mp4) (≈1:55) walks through every feature end-to-end:
grid + search + category filters, AI search, recipe drawer, AI improvement
tips, inline edit, AI-suggested recipe creation, import from free text,
import from a live URL (auto-translated to Hebrew), and JWT-protected delete.

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
