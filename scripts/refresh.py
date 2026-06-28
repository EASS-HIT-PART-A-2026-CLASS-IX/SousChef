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
