"""
pytest test suite for the SousChef API.

All tests use an in-memory SQLite database and mock every external call
(Gemini API, httpx) so no network access is required.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Ingredient, Recipe, Step


# ── In-memory DB fixture ──────────────────────────────────────────────────────

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_RECIPE_PAYLOAD = {
    "name": "Pancakes",
    "description": "Fluffy breakfast pancakes",
    "category": "breakfast",
    "prep_time": 10,
    "cook_time": 15,
    "servings": 4,
    "ingredients": [
        {"name": "flour", "amount": 2.0, "unit": "cups"},
        {"name": "milk", "amount": 1.5, "unit": "cups"},
    ],
    "steps": [
        {"order": 1, "instruction": "Mix dry ingredients."},
        {"order": 2, "instruction": "Add wet ingredients and stir."},
        {"order": 3, "instruction": "Cook on griddle until golden."},
    ],
}

GEMINI_RECIPE_DICT = {
    "name": "Chocolate Chip Cookies",
    "description": "Classic cookies",
    "category": "dessert",
    "prep_time": 15,
    "cook_time": 12,
    "servings": 24,
    "ingredients": [
        {"name": "flour", "amount": 2.25, "unit": "cups"},
        {"name": "chocolate chips", "amount": 2.0, "unit": "cups"},
    ],
    "steps": [
        {"order": 1, "instruction": "Cream butter and sugar."},
        {"order": 2, "instruction": "Add eggs and vanilla."},
        {"order": 3, "instruction": "Fold in flour and chips."},
        {"order": 4, "instruction": "Bake at 375°F for 11-13 minutes."},
    ],
}


# ── Recipe CRUD tests ─────────────────────────────────────────────────────────

class TestCreateRecipe:
    def test_create_recipe_returns_201(self, client: TestClient):
        resp = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD)
        assert resp.status_code == 201

    def test_create_recipe_fields_match(self, client: TestClient):
        resp = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD)
        data = resp.json()
        assert data["name"] == "Pancakes"
        assert data["category"] == "breakfast"
        assert data["prep_time"] == 10
        assert data["cook_time"] == 15
        assert data["servings"] == 4
        assert "id" in data

    def test_create_recipe_with_ingredients_and_steps(self, client: TestClient):
        resp = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD)
        data = resp.json()
        assert len(data["ingredients"]) == 2
        assert len(data["steps"]) == 3
        # Check ingredient content
        ing_names = {i["name"] for i in data["ingredients"]}
        assert "flour" in ing_names
        assert "milk" in ing_names
        # Check step order
        orders = [s["order"] for s in data["steps"]]
        assert orders == [1, 2, 3]

    def test_create_recipe_minimal(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "Simple Salad"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Simple Salad"
        assert data["ingredients"] == []
        assert data["steps"] == []


class TestListRecipes:
    def test_list_all_recipes(self, client: TestClient):
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "name": "Recipe A"})
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "name": "Recipe B"})
        resp = client.get("/recipes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_recipes_filter_by_category(self, client: TestClient):
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "category": "breakfast"})
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "name": "Pasta", "category": "dinner"})
        resp = client.get("/recipes?category=breakfast")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["category"] == "breakfast"

    def test_list_recipes_filter_no_match(self, client: TestClient):
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "category": "breakfast"})
        resp = client.get("/recipes?category=dessert")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_recipes_empty(self, client: TestClient):
        resp = client.get("/recipes")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetRecipe:
    def test_get_recipe_by_id(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.get(f"/recipes/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["name"] == "Pancakes"

    def test_get_recipe_includes_ingredients_and_steps(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.get(f"/recipes/{created['id']}")
        data = resp.json()
        assert len(data["ingredients"]) == 2
        assert len(data["steps"]) == 3

    def test_get_recipe_not_found(self, client: TestClient):
        resp = client.get("/recipes/9999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestUpdateRecipe:
    def test_update_recipe_name(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.put(f"/recipes/{created['id']}", json={"name": "Waffles"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Waffles"

    def test_update_recipe_partial(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.put(f"/recipes/{created['id']}", json={"cook_time": 99})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cook_time"] == 99
        # Unchanged fields remain
        assert data["name"] == "Pancakes"

    def test_update_recipe_not_found(self, client: TestClient):
        resp = client.put("/recipes/9999", json={"name": "Ghost"})
        assert resp.status_code == 404


class TestDeleteRecipe:
    def test_delete_recipe_returns_204(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.delete(f"/recipes/{created['id']}")
        assert resp.status_code == 204

    def test_delete_recipe_no_longer_exists(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        client.delete(f"/recipes/{created['id']}")
        resp = client.get(f"/recipes/{created['id']}")
        assert resp.status_code == 404

    def test_delete_recipe_not_found(self, client: TestClient):
        resp = client.delete("/recipes/9999")
        assert resp.status_code == 404

    def test_delete_recipe_cascades_ingredients(self, client: TestClient, session: Session):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        recipe_id = created["id"]
        client.delete(f"/recipes/{recipe_id}")
        remaining = session.exec(
            __import__("sqlmodel", fromlist=["select"]).select(Ingredient).where(
                Ingredient.recipe_id == recipe_id
            )
        ).all()
        assert remaining == []

    def test_delete_recipe_cascades_steps(self, client: TestClient, session: Session):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        recipe_id = created["id"]
        client.delete(f"/recipes/{recipe_id}")
        remaining = session.exec(
            __import__("sqlmodel", fromlist=["select"]).select(Step).where(
                Step.recipe_id == recipe_id
            )
        ).all()
        assert remaining == []


# ── Ingredient / Step endpoint tests ─────────────────────────────────────────

class TestIngredients:
    def test_add_ingredient_to_recipe(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/ingredients",
            json={"name": "sugar", "amount": 0.5, "unit": "cups"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "sugar"
        assert data["recipe_id"] == recipe["id"]

    def test_add_ingredient_recipe_not_found(self, client: TestClient):
        resp = client.post(
            "/recipes/9999/ingredients",
            json={"name": "sugar", "amount": 0.5, "unit": "cups"},
        )
        assert resp.status_code == 404

    def test_delete_ingredient(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        ing_id = created["ingredients"][0]["id"]
        resp = client.delete(f"/ingredients/{ing_id}")
        assert resp.status_code == 204

    def test_delete_ingredient_not_found(self, client: TestClient):
        resp = client.delete("/ingredients/9999")
        assert resp.status_code == 404


class TestSteps:
    def test_add_step_to_recipe(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/steps",
            json={"order": 1, "instruction": "Do something."},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["order"] == 1
        assert data["recipe_id"] == recipe["id"]

    def test_delete_step(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        step_id = created["steps"][0]["id"]
        resp = client.delete(f"/steps/{step_id}")
        assert resp.status_code == 204

    def test_delete_step_not_found(self, client: TestClient):
        resp = client.delete("/steps/9999")
        assert resp.status_code == 404


# ── AI Import tests ───────────────────────────────────────────────────────────

class TestFromText:
    def test_from_text_happy_path(self, client: TestClient):
        """Mock Gemini; verify recipe is created and returned."""
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-text",
                data={"text": "Chocolate chip cookies recipe..."},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Chocolate Chip Cookies"
        assert data["category"] == "dessert"
        assert len(data["ingredients"]) == 2
        assert len(data["steps"]) == 4

    def test_from_text_with_image(self, client: TestClient):
        """Optional image file is read and forwarded to the extractor as bytes."""
        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-text",
                data={"text": "Some cookie text"},
                files={"image": ("cookie.jpg", fake_image, "image/jpeg")},
            )
            mock_extract.assert_called_once_with("Some cookie text", fake_image)
        assert resp.status_code == 201

    def test_from_text_without_image(self, client: TestClient):
        """Image field is optional — omitting it passes None to the extractor."""
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-text",
                data={"text": "Some cookie text"},
            )
            mock_extract.assert_called_once_with("Some cookie text", None)
        assert resp.status_code == 201

    def test_from_text_invalid_json_from_gemini(self, client: TestClient):
        """If Gemini returns something unparseable, expect 422."""
        from fastapi import HTTPException as FHE

        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.side_effect = FHE(
                status_code=422,
                detail="AI could not extract a recipe from this content. Please try with clearer content.",
            )
            resp = client.post(
                "/recipes/from-text",
                data={"text": "This is not a recipe at all"},
            )
        assert resp.status_code == 422
        assert "AI could not extract" in resp.json()["detail"]

    def test_from_text_all_null_fields_from_gemini(self, client: TestClient):
        """If Gemini returns valid JSON but with null name, expect 422 not 500."""
        from fastapi import HTTPException as FHE

        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.side_effect = FHE(
                status_code=422,
                detail="AI could not extract a recipe from this content. Please try with clearer content.",
            )
            resp = client.post(
                "/recipes/from-text",
                data={"text": "Some ambiguous content"},
            )
        assert resp.status_code == 422
        assert "AI could not extract" in resp.json()["detail"]


class TestFromURL:
    def test_from_url_happy_path(self, client: TestClient):
        """Mock httpx fetch + Gemini; verify recipe created."""
        with patch("app.main.extract_recipe_from_url", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-url",
                json={"url": "https://example.com/recipe"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Chocolate Chip Cookies"
        assert len(data["ingredients"]) == 2

    def test_from_url_fetch_failure_returns_422(self, client: TestClient):
        """Simulate a blocked / unreachable URL and verify the 422 fallback."""
        from fastapi import HTTPException as FHE

        with patch("app.main.extract_recipe_from_url", new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = FHE(
                status_code=422,
                detail="Could not fetch URL. Please use /recipes/from-text instead.",
            )
            resp = client.post(
                "/recipes/from-url",
                json={"url": "https://www.instagram.com/p/blocked/"},
            )
        assert resp.status_code == 422
        assert "Could not fetch URL" in resp.json()["detail"]

    def test_from_url_recipe_saved_to_db(self, client: TestClient, session: Session):
        """After a successful import, the recipe must be persisted."""
        with patch("app.main.extract_recipe_from_url", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-url",
                json={"url": "https://example.com/cookies"},
            )
        recipe_id = resp.json()["id"]
        db_recipe = session.get(Recipe, recipe_id)
        assert db_recipe is not None
        assert db_recipe.name == "Chocolate Chip Cookies"
