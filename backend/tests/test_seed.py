"""
Tests for the seed script (scripts/seed.py).

The script's `seed(client)` function accepts any httpx-compatible client, so
we exercise it against the real app via TestClient with an in-memory DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# Make the repo-root `scripts` package importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import seed  # noqa: E402

from app.database import get_session  # noqa: E402


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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def test_seed_creates_sample_recipes(client: TestClient):
    created = seed.seed(client)
    assert created == len(seed.SAMPLE_RECIPES) >= 3

    names = {r["name"] for r in client.get("/recipes").json()}
    for sample in seed.SAMPLE_RECIPES:
        assert sample["name"] in names


def test_seed_recipes_include_ingredients_and_steps(client: TestClient):
    seed.seed(client)
    recipes = client.get("/recipes").json()
    assert all(r["ingredients"] for r in recipes)
    assert all(r["steps"] for r in recipes)


def test_seed_is_idempotent(client: TestClient):
    assert seed.seed(client) == len(seed.SAMPLE_RECIPES)
    assert seed.seed(client) == 0  # second run: everything already exists
    assert len(client.get("/recipes").json()) == len(seed.SAMPLE_RECIPES)
