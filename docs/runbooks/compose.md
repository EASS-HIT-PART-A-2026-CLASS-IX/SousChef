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
