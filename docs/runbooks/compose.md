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
curl -fsS http://localhost:8000/health
# {"status":"ok","version":"1.0.0"}
```

(`/health` is exempt from rate limiting, so probes never consume request budget.)

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

## 5. Check health / rate-limit headers

Every non-`/health` response carries the rate-limit trio (limit is
`RATE_LIMIT_PER_MINUTE`, default 120 per client IP per 60s window):

```bash
curl -si http://localhost:8000/recipes | grep -i x-ratelimit
# X-RateLimit-Limit: 120
# X-RateLimit-Remaining: 119
# X-RateLimit-Reset: 42
```

Exceeding the limit returns `429` with a `Retry-After` header:

```bash
for i in $(seq 1 130); do curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/recipes; done | sort | uniq -c
```

Inspect the request-id correlation in logs:

```bash
docker compose logs backend | grep request_id
```

## 6. Run backend tests inside Docker

```bash
docker compose run --rm backend pytest
```

## 6b. Schemathesis / pytest in CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull
request: it installs the backend with `uv sync --extra dev` and runs
`uv run pytest`, which includes `tests/test_api_contract.py` — Schemathesis
fuzzing of the CRUD endpoints against the app's own OpenAPI schema
(no 5xx allowed, responses must match the declared schema).

Run the same thing locally:

```bash
cd backend && uv run pytest tests/test_api_contract.py -v
```

## 6c. Seed sample data

```bash
uv run python scripts/seed.py     # idempotent; API must be up
```

## 7. Stop everything cleanly

```bash
docker compose down -v        # -v also removes the redis_data volume
```
