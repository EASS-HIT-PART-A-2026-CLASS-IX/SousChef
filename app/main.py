"""
SousChef – FastAPI application entry point.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session, select

from app.ai import extract_recipe_from_text, extract_recipe_from_url
from app.database import create_db_and_tables, get_session
from app.models import Ingredient, Recipe, Step
from app.schemas import (
    ImportFromURLRequest,
    IngredientCreate,
    IngredientRead,
    RecipeCreate,
    RecipeRead,
    RecipeUpdate,
    StepCreate,
    StepRead,
)

# Load .env at startup
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate critical env var before accepting traffic
    if not os.getenv("GEMINI_API_KEY"):
        import warnings
        warnings.warn(
            "GEMINI_API_KEY is not set. AI import endpoints will be unavailable.",
            stacklevel=1,
        )
    create_db_and_tables()
    yield


app = FastAPI(
    title="SousChef API",
    description="SousChef – REST API for managing recipes with AI-powered import",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_recipe_or_404(recipe_id: int, session: Session) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")
    return recipe


def _build_recipe_read(recipe: Recipe) -> RecipeRead:
    return RecipeRead(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        category=recipe.category,
        prep_time=recipe.prep_time,
        cook_time=recipe.cook_time,
        servings=recipe.servings,
        ingredients=[IngredientRead.model_validate(i) for i in recipe.ingredients],
        steps=[StepRead.model_validate(s) for s in recipe.steps],
    )


def _create_recipe_from_dict(data: dict, session: Session) -> Recipe:
    """
    Create a Recipe (plus its Ingredients and Steps) from a plain dict,
    as returned by the Gemini parser.
    """
    ingredients_data = data.pop("ingredients", [])
    steps_data = data.pop("steps", [])

    recipe = Recipe(**data)
    session.add(recipe)
    session.flush()  # populate recipe.id

    for ing in ingredients_data:
        session.add(Ingredient(recipe_id=recipe.id, **ing))
    for step in steps_data:
        session.add(Step(recipe_id=recipe.id, **step))

    session.commit()
    session.refresh(recipe)
    return recipe


# ── Recipes ───────────────────────────────────────────────────────────────────

@app.post("/recipes", response_model=RecipeRead, status_code=201)
def create_recipe(
    payload: RecipeCreate,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """Create a new recipe (optionally with nested ingredients and steps)."""
    recipe = Recipe(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        prep_time=payload.prep_time,
        cook_time=payload.cook_time,
        servings=payload.servings,
    )
    session.add(recipe)
    session.flush()

    for ing in payload.ingredients:
        session.add(Ingredient(recipe_id=recipe.id, **ing.model_dump()))
    for step in payload.steps:
        session.add(Step(recipe_id=recipe.id, **step.model_dump()))

    session.commit()
    session.refresh(recipe)
    return _build_recipe_read(recipe)


@app.get("/recipes", response_model=List[RecipeRead])
def list_recipes(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    session: Session = Depends(get_session),
) -> List[RecipeRead]:
    """List all recipes, optionally filtered by category."""
    stmt = select(Recipe)
    if category:
        stmt = stmt.where(Recipe.category == category)
    recipes = session.exec(stmt).all()
    return [_build_recipe_read(r) for r in recipes]


@app.get("/recipes/{recipe_id}", response_model=RecipeRead)
def get_recipe(
    recipe_id: int,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """Get a single recipe by ID, including all ingredients and steps."""
    recipe = _get_recipe_or_404(recipe_id, session)
    return _build_recipe_read(recipe)


@app.put("/recipes/{recipe_id}", response_model=RecipeRead)
def update_recipe(
    recipe_id: int,
    payload: RecipeUpdate,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """Update the scalar fields of a recipe."""
    recipe = _get_recipe_or_404(recipe_id, session)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(recipe, key, value)
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return _build_recipe_read(recipe)


@app.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(
    recipe_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Delete a recipe and all its ingredients/steps (cascade)."""
    recipe = _get_recipe_or_404(recipe_id, session)
    session.delete(recipe)
    session.commit()


# ── Ingredients ───────────────────────────────────────────────────────────────

@app.post("/recipes/{recipe_id}/ingredients", response_model=IngredientRead, status_code=201)
def add_ingredient(
    recipe_id: int,
    payload: IngredientCreate,
    session: Session = Depends(get_session),
) -> IngredientRead:
    """Add an ingredient to an existing recipe."""
    _get_recipe_or_404(recipe_id, session)
    ingredient = Ingredient(recipe_id=recipe_id, **payload.model_dump())
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return IngredientRead.model_validate(ingredient)


@app.delete("/ingredients/{ingredient_id}", status_code=204)
def delete_ingredient(
    ingredient_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Remove an ingredient by ID."""
    ingredient = session.get(Ingredient, ingredient_id)
    if not ingredient:
        raise HTTPException(status_code=404, detail=f"Ingredient {ingredient_id} not found")
    session.delete(ingredient)
    session.commit()


# ── Steps ─────────────────────────────────────────────────────────────────────

@app.post("/recipes/{recipe_id}/steps", response_model=StepRead, status_code=201)
def add_step(
    recipe_id: int,
    payload: StepCreate,
    session: Session = Depends(get_session),
) -> StepRead:
    """Add a step to an existing recipe."""
    _get_recipe_or_404(recipe_id, session)
    step = Step(recipe_id=recipe_id, **payload.model_dump())
    session.add(step)
    session.commit()
    session.refresh(step)
    return StepRead.model_validate(step)


@app.delete("/steps/{step_id}", status_code=204)
def delete_step(
    step_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Remove a step by ID."""
    step = session.get(Step, step_id)
    if not step:
        raise HTTPException(status_code=404, detail=f"Step {step_id} not found")
    session.delete(step)
    session.commit()


# ── AI Import ─────────────────────────────────────────────────────────────────

@app.post("/recipes/from-url", response_model=RecipeRead, status_code=201)
async def import_from_url(
    payload: ImportFromURLRequest,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """
    Fetch a URL, extract visible text (+ og:image), and use Gemini to parse
    a recipe from the content.
    """
    recipe_data = await extract_recipe_from_url(payload.url)
    recipe = _create_recipe_from_dict(recipe_data, session)
    return _build_recipe_read(recipe)


@app.post("/recipes/from-text", response_model=RecipeRead, status_code=201)
async def import_from_text(
    text: str = Form(..., description="Recipe text to extract from"),
    image: Optional[UploadFile] = File(default=None, description="Optional image file"),
    session: Session = Depends(get_session),
) -> RecipeRead:
    """
    Send pasted text (and an optional image file) to Gemini to extract a recipe.
    Accepts multipart/form-data with a required 'text' field and an optional 'image' file.
    """
    image_bytes: Optional[bytes] = await image.read() if image else None
    recipe_data = extract_recipe_from_text(text, image_bytes)
    recipe = _create_recipe_from_dict(recipe_data, session)
    return _build_recipe_read(recipe)
