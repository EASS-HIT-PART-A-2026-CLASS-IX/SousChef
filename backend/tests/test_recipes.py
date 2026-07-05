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
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import ai
from app.ai import RECIPE_JSON_SCHEMA
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


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_RECIPE_PAYLOAD = {
    "name": "Pancakes",
    "description": "Fluffy breakfast pancakes",
    "category": "ארוחת בוקר",
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
    "category": "קינוח",
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
        assert data["category"] == "ארוחת בוקר"
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
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "category": "ארוחת בוקר"})
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "name": "Pasta", "category": "ארוחת ערב"})
        resp = client.get("/recipes?category=ארוחת בוקר")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["category"] == "ארוחת בוקר"

    def test_list_recipes_filter_no_match(self, client: TestClient):
        client.post("/recipes", json={**SAMPLE_RECIPE_PAYLOAD, "category": "ארוחת בוקר"})
        resp = client.get("/recipes?category=קינוח")
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
    def test_from_text_runs_extractor_in_threadpool(self, client: TestClient):
        with patch("app.main.extract_recipe_from_text") as mock_extract, patch(
            "app.main.run_in_threadpool",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-text",
                data={"text": "Chocolate chip cookies recipe..."},
            )

        assert resp.status_code == 201
        mock_run.assert_awaited_once_with(mock_extract, "Chocolate chip cookies recipe...", None)

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
        assert data["category"] == "קינוח"
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
    def test_from_url_preview_returns_draft_without_saving(self, client: TestClient, session: Session):
        with patch("app.main.extract_recipe_from_url", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = dict(GEMINI_RECIPE_DICT)
            resp = client.post(
                "/recipes/from-url/preview",
                json={"url": "https://example.com/recipe"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Chocolate Chip Cookies"
        assert "id" not in data
        assert session.exec(select(Recipe)).all() == []

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

    def test_from_url_invalid_url_returns_422(self, client: TestClient):
        """A non-HTTP URL (or plain garbage) must be rejected before any fetch."""
        resp = client.post(
            "/recipes/from-url",
            json={"url": "not-a-url-at-all"},
        )
        assert resp.status_code == 422

    def test_from_url_non_http_scheme_returns_422(self, client: TestClient):
        """ftp:// or file:// URLs must be rejected."""
        resp = client.post(
            "/recipes/from-url",
            json={"url": "ftp://example.com/recipe.txt"},
        )
        assert resp.status_code == 422


class TestUrlExtractionThreading:
    @pytest.mark.asyncio
    async def test_extract_recipe_from_url_offloads_jsonld_extraction(self):
        html_doc = """
        <html>
            <head>
                <script type="application/ld+json">
                    {"@type":"Recipe","name":"עוגיות"}
                </script>
            </head>
            <body>ignored</body>
        </html>
        """

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.text = html_doc

        client = AsyncMock()
        client.get.return_value = response

        client_cm = AsyncMock()
        client_cm.__aenter__.return_value = client
        client_cm.__aexit__.return_value = False

        with patch("app.ai.httpx.AsyncClient", return_value=client_cm), patch(
            "asyncio.to_thread",
            new_callable=AsyncMock,
        ) as mock_to_thread:
            mock_to_thread.return_value = dict(GEMINI_RECIPE_DICT)
            result = await ai.extract_recipe_from_url("https://example.com/recipe")

        assert result["name"] == GEMINI_RECIPE_DICT["name"]
        mock_to_thread.assert_awaited_once()
        args = mock_to_thread.await_args.args
        assert args[0] is ai.extract_recipe_from_text
        assert '"@type": "Recipe"' in args[1]


class TestAIJsonParsing:
    def test_parse_recipe_json_accepts_python_style_object(self):
        raw = """
        ```json
        {
            'name': 'עוגיות טחינה',
            'description': 'מתכון פריך',
            'ingredients': [{'name': 'טחינה', 'amount': 1, 'unit': 'כוס'},],
            'steps': [{'order': 1, 'instruction': 'לערבב'}],
        }
        ```
        """

        data = ai._parse_recipe_json(raw)

        assert data["name"] == "עוגיות טחינה"
        assert data["ingredients"][0]["name"] == "טחינה"

    def test_parse_recipe_json_salvages_truncated_recipe_object(self):
        raw = """
        {
          "name": "מאפינס אוכמניות",
          "description": "מאפינס רכים ואווריריים",
          "category": "קינוח",
          "prep_time": null,
          "cook_time": 20,
          "servings": null,
          "ingredients": [
            {"name": "קמח שקדים", "amount": 2, "unit": "כוסות"},
            {"name": "אוכמניות", "amount": 1, "unit": "כוס"},
            {"name": "דבש (לק
        """

        data = ai._parse_recipe_json(raw)

        assert data["name"] == "מאפינס אוכמניות"
        assert data["category"] == "קינוח"
        assert data["cook_time"] == 20
        assert data["ingredients"] == [
            {"name": "קמח שקדים", "amount": 2.0, "unit": "כוסות"},
            {"name": "אוכמניות", "amount": 1.0, "unit": "כוס"},
        ]


# ── Validation edge-case tests ────────────────────────────────────────────────

class TestValidation:
    # ── Recipe name ───────────────────────────────────────────────────────────
    def test_create_empty_name_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": ""})
        assert resp.status_code == 422

    def test_create_whitespace_name_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "   "})
        assert resp.status_code == 422

    def test_update_empty_name_rejected(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.put(f"/recipes/{created['id']}", json={"name": ""})
        assert resp.status_code == 422

    def test_update_whitespace_name_rejected(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.put(f"/recipes/{created['id']}", json={"name": "   "})
        assert resp.status_code == 422

    # ── Category ──────────────────────────────────────────────────────────────
    def test_create_invalid_category_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "Test", "category": "brunch"})
        assert resp.status_code == 422

    def test_create_valid_categories_accepted(self, client: TestClient):
        for cat in ("ארוחת בוקר", "ארוחת צהריים", "ארוחת ערב", "קינוח", "חטיף", "אחר"):
            resp = client.post("/recipes", json={"name": f"מתכון {cat}", "category": cat})
            assert resp.status_code == 201, f"Category '{cat}' was unexpectedly rejected"

    def test_update_invalid_category_rejected(self, client: TestClient):
        created = client.post("/recipes", json=SAMPLE_RECIPE_PAYLOAD).json()
        resp = client.put(f"/recipes/{created['id']}", json={"category": "brunch"})
        assert resp.status_code == 422

    # ── Numeric fields ────────────────────────────────────────────────────────
    def test_create_negative_prep_time_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "Test", "prep_time": -1})
        assert resp.status_code == 422

    def test_create_negative_cook_time_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "Test", "cook_time": -5})
        assert resp.status_code == 422

    def test_create_negative_servings_rejected(self, client: TestClient):
        resp = client.post("/recipes", json={"name": "Test", "servings": -2})
        assert resp.status_code == 422

    def test_create_zero_times_accepted(self, client: TestClient):
        """Zero is a valid value for prep/cook times."""
        resp = client.post("/recipes", json={"name": "Instant", "prep_time": 0, "cook_time": 0})
        assert resp.status_code == 201

    # ── Ingredients ───────────────────────────────────────────────────────────
    def test_ingredient_zero_amount_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/ingredients",
            json={"name": "salt", "amount": 0, "unit": "tsp"},
        )
        assert resp.status_code == 422

    def test_ingredient_negative_amount_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/ingredients",
            json={"name": "salt", "amount": -1, "unit": "tsp"},
        )
        assert resp.status_code == 422

    def test_ingredient_blank_name_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/ingredients",
            json={"name": "  ", "amount": 1.0, "unit": "cup"},
        )
        assert resp.status_code == 422

    def test_ingredient_blank_unit_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/ingredients",
            json={"name": "flour", "amount": 1.0, "unit": ""},
        )
        assert resp.status_code == 422

    # ── Steps ─────────────────────────────────────────────────────────────────
    def test_step_zero_order_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/steps",
            json={"order": 0, "instruction": "Do something."},
        )
        assert resp.status_code == 422

    def test_step_negative_order_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/steps",
            json={"order": -1, "instruction": "Do something."},
        )
        assert resp.status_code == 422

    def test_step_blank_instruction_rejected(self, client: TestClient):
        recipe = client.post("/recipes", json={"name": "Test"}).json()
        resp = client.post(
            f"/recipes/{recipe['id']}/steps",
            json={"order": 1, "instruction": "   "},
        )
        assert resp.status_code == 422


# ── AI dict parsing edge cases ────────────────────────────────────────────────

class TestCreateRecipeFromDict:
    def test_extra_jsonld_keys_are_ignored(self, client: TestClient):
        """Gemini JSON-LD responses may include @type, image, author, etc.
        These must be silently stripped — not crash with TypeError."""
        gemini_response = {
            **GEMINI_RECIPE_DICT,
            "@type": "Recipe",
            "@context": "https://schema.org",
            "image": "https://example.com/cookie.jpg",
            "author": {"@type": "Person", "name": "Jane"},
            "datePublished": "2024-01-01",
        }
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = gemini_response
            resp = client.post(
                "/recipes/from-text",
                data={"text": "cookie recipe from structured data"},
            )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Chocolate Chip Cookies"

    def test_ingredients_with_extra_keys_are_saved(self, client: TestClient):
        """Extra keys in ingredient dicts must be stripped, not cause a crash."""
        response = {
            **GEMINI_RECIPE_DICT,
            "ingredients": [
                {"name": "flour", "amount": 2.0, "unit": "cups", "notes": "sifted"},
            ],
        }
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = response
            resp = client.post(
                "/recipes/from-text",
                data={"text": "cookie recipe"},
            )
        assert resp.status_code == 201
        assert len(resp.json()["ingredients"]) == 1

    def test_ingredients_missing_amount_and_unit_are_saved(self, client: TestClient):
        """Ingredients with only a name (no amount/unit) are valid — amount and unit are optional."""
        response = {
            **GEMINI_RECIPE_DICT,
            "ingredients": [
                {"name": "flour", "amount": 2.0, "unit": "cups"},
                {"name": "מלח לפי הטעם"},   # no amount or unit — valid
            ],
        }
        with patch("app.main.extract_recipe_from_text") as mock_extract:
            mock_extract.return_value = response
            resp = client.post(
                "/recipes/from-text",
                data={"text": "cookie recipe"},
            )
        assert resp.status_code == 201
        assert len(resp.json()["ingredients"]) == 2


class TestOllamaJsonGuards:
    def test_recipe_schema_bounds_free_text_fields(self):
        ingredient_schema = RECIPE_JSON_SCHEMA["properties"]["ingredients"]["items"]["properties"]
        step_schema = RECIPE_JSON_SCHEMA["properties"]["steps"]["items"]["properties"]

        assert ingredient_schema["name"]["maxLength"] == 80
        assert ingredient_schema["unit"]["anyOf"][0]["maxLength"] == 24
        assert step_schema["instruction"]["maxLength"] == 280

    def test_ollama_generate_retries_without_schema_when_response_is_empty(self):
        first = MagicMock()
        first.raise_for_status.return_value = None
        first.json.return_value = {"response": ""}

        second = MagicMock()
        second.raise_for_status.return_value = None
        second.json.return_value = {"response": '{"name":"שקשוקה"}'}

        with patch("app.ai.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.side_effect = [first, second]
            result = ai._ollama_generate(
                "Return recipe JSON",
                schema={"type": "object", "properties": {"name": {"type": "string"}}},
            )

        assert result == '{"name":"שקשוקה"}'
        assert mock_post.call_count == 2
        assert mock_post.call_args_list[0].kwargs["json"]["format"]["type"] == "object"
        assert "format" not in mock_post.call_args_list[1].kwargs["json"]


class TestStagedSuggestRecipe:
    def test_suggest_recipe_builds_context_across_stages(self):
        responses = iter([
            {"name": "שקשוקה"},
            {"description": "מנה ישראלית קלאסית עם עגבניות וביצים."},
            {"category": "ארוחת ערב", "prep_time": 10, "cook_time": 20, "servings": 3},
            {"ingredients": [{"name": "עגבניות", "amount": 4, "unit": "יח'"}]},
            {"steps": [{"order": 1, "instruction": "מבשלים את הרוטב."}]},
        ])
        prompts: list[str] = []

        def fake_generate(prompt: str, schema: dict):
            prompts.append(prompt)
            return next(responses)

        with patch("app.ai._generate_json_with_schema", side_effect=fake_generate):
            recipe = ai.suggest_recipe()

        assert recipe["name"] == "שקשוקה"
        assert recipe["description"] == "מנה ישראלית קלאסית עם עגבניות וביצים."
        assert recipe["category"] == "ארוחת ערב"
        assert recipe["ingredients"][0]["name"] == "עגבניות"
        assert recipe["steps"][0]["instruction"] == "מבשלים את הרוטב."
        assert len(prompts) == 5
        assert '"name": "שקשוקה"' in prompts[1]
        assert '"description": "מנה ישראלית קלאסית עם עגבניות וביצים."' in prompts[2]
        assert '"ingredients": [' in prompts[4]

    def test_suggest_recipe_stage_retries_invalid_output_then_succeeds(self):
        responses = iter([
            {"name": "   "},
            {"name": "שקשוקה"},
        ])

        with patch("app.ai._generate_json_with_schema", side_effect=lambda prompt, schema: next(responses)):
            result = ai.suggest_recipe_stage("name", {})

        assert result["stage"] == "name"
        assert result["patch"] == {"name": "שקשוקה"}
        assert result["recipe"]["name"] == "שקשוקה"

    def test_suggest_recipe_stage_returns_structured_422_after_final_retry(self):
        from fastapi import HTTPException as FHE

        with patch("app.ai._generate_json_with_schema", return_value={"name": "   "}):
            with pytest.raises(FHE) as exc_info:
                ai.suggest_recipe_stage("name", {})

        exc = exc_info.value
        assert exc.status_code == 422
        assert exc.detail["stage"] == "name"
        assert exc.detail["attempts"] == 3
        assert "name" in exc.detail["message"].lower()

    def test_ingredient_normalization_drops_invalid_amount_and_unit(self):
        raw = {
            "ingredients": [
                {"name": "מלח", "amount": 0, "unit": "כפית"},
                {"name": "פלפל", "amount": None, "unit": " "},
                {"name": "שמן זית", "amount": 2, "unit": "כפות"},
            ]
        }

        result = ai._normalize_ingredients_patch(raw)

        assert result["ingredients"][0] == {"name": "מלח", "amount": None, "unit": None}
        assert result["ingredients"][1] == {"name": "פלפל", "amount": None, "unit": None}
        assert result["ingredients"][2] == {"name": "שמן זית", "amount": 2.0, "unit": "כפות"}

    def test_step_normalization_renumbers_sequentially(self):
        raw = {
            "steps": [
                {"order": 8, "instruction": "  מערבבים  "},
                {"order": 2, "instruction": "מגישים"},
            ]
        }

        result = ai._normalize_steps_patch(raw)

        assert result["steps"] == [
            {"order": 1, "instruction": "מערבבים"},
            {"order": 2, "instruction": "מגישים"},
        ]


class TestSuggestStageEndpoint:
    def test_stage_endpoint_returns_patch_and_merged_recipe(self, client: TestClient):
        with patch("app.main.suggest_recipe_stage") as mock_stage:
            mock_stage.return_value = {
                "stage": "description",
                "patch": {"description": "טעים מאוד"},
                "recipe": {"name": "שקשוקה", "description": "טעים מאוד"},
                "done": False,
            }
            resp = client.post(
                "/recipes/suggest/stage",
                json={"stage": "description", "recipe": {"name": "שקשוקה"}},
            )

        assert resp.status_code == 200
        assert resp.json()["patch"] == {"description": "טעים מאוד"}
        assert resp.json()["recipe"]["name"] == "שקשוקה"
        assert resp.json()["done"] is False

    def test_stage_endpoint_returns_structured_failure_detail(self, client: TestClient):
        from fastapi import HTTPException as FHE

        with patch("app.main.suggest_recipe_stage") as mock_stage:
            mock_stage.side_effect = FHE(
                status_code=422,
                detail={"stage": "ingredients", "message": "bad ingredients", "attempts": 3},
            )
            resp = client.post(
                "/recipes/suggest/stage",
                json={"stage": "ingredients", "recipe": {"name": "שקשוקה"}},
            )

        assert resp.status_code == 422
        assert resp.json()["detail"] == {
            "stage": "ingredients",
            "message": "bad ingredients",
            "attempts": 3,
        }
