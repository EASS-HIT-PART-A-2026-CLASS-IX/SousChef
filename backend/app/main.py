"""
SousChef – FastAPI application entry point.
"""
from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, List, Optional

from dotenv import load_dotenv

# Must run before app.ai is imported so its module-level env-var reads pick up .env values
load_dotenv()

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path, Query, Request, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from sqlmodel import Session, select  # noqa: E402
from app.observability import clear_request_id, configure_logging, get_logger, set_request_id, trace_call  # noqa: E402

configure_logging()
logger = get_logger(__name__)

from app.ai import (  # noqa: E402
    enhance_recipe,
    extract_recipe_from_text,
    extract_recipe_from_url,
    recommend_recipes,
    suggest_recipe,
    suggest_recipe_stage,
)
from app.database import create_db_and_tables, get_session  # noqa: E402
from app.models import Ingredient, Recipe, Step  # noqa: E402
from app.schemas import (  # noqa: E402
    ImportFromURLRequest,
    IngredientCreate,
    IngredientRead,
    RecipeCreate,
    RecipeRead,
    SuggestStageRequest,
    SuggestStageResponse,
    RecipeUpdate,
    RecommendRequest,
    StepCreate,
    StepRead,
    VALID_CATEGORIES,
)
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.security import OAuth2PasswordRequestForm  # noqa: E402
from app import auth, ratelimit  # noqa: E402


@trace_call
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate AI provider configuration before accepting traffic
    import warnings

    provider = os.getenv("AI_PROVIDER", "gemini").lower()
    if provider == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            warnings.warn(
                "GEMINI_API_KEY is not set. AI import endpoints will be unavailable. "
                "Set AI_PROVIDER=ollama to use a local model instead.",
                stacklevel=1,
            )
    elif provider == "ollama":
        from app.ai import OLLAMA_BASE_URL, OLLAMA_MODEL
        warnings.warn(
            f"Using Ollama at {OLLAMA_BASE_URL} with model '{OLLAMA_MODEL}'. "
            "Make sure the daemon is running and the model has been pulled.",
            stacklevel=1,
        )
    else:
        warnings.warn(
            f"Unknown AI_PROVIDER='{provider}'. Expected 'gemini' or 'ollama'. "
            "AI import endpoints will fail until this is corrected.",
            stacklevel=1,
        )
    create_db_and_tables()
    yield


# SQLite rejects integers wider than a signed 64-bit; bound id path params so
# out-of-range values get a 422 instead of an OverflowError-driven 500.
RecordId = Annotated[int, Path(ge=1, le=2**63 - 1)]

app = FastAPI(
    title="SousChef API",
    description="SousChef – REST API for managing recipes with AI-powered import",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:8]
    set_request_id(request_id)
    start = time.perf_counter()
    logger.info(
        "HTTP request started method=%s path=%s query=%s client=%s",
        request.method,
        request.url.path,
        request.url.query,
        request.client.host if request.client else "unknown",
    )
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception("HTTP request failed after %.1fms", duration_ms)
        clear_request_id()
        raise

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "HTTP request completed status=%s duration_ms=%.1f",
        response.status_code,
        duration_ms,
    )
    clear_request_id()
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in ratelimit.EXEMPT_PATHS:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    allowed, headers = ratelimit.hit(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded, try again soon"},
            headers=headers,
        )
    response = await call_next(request)
    response.headers.update(headers)
    return response


@app.get("/health")
def health():
    """Liveness probe. Exempt from rate limiting."""
    return {"status": "ok", "version": app.version}


# ── Helper ────────────────────────────────────────────────────────────────────

@trace_call
def _get_recipe_or_404(recipe_id: int, session: Session) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")
    return recipe


@trace_call
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


_RECIPE_FIELDS = {"name", "description", "category", "prep_time", "cook_time", "servings"}
_INGREDIENT_FIELDS = {"name", "amount", "unit"}
_STEP_FIELDS = {"order", "instruction"}


@trace_call
def _create_recipe_from_dict(data: dict, session: Session) -> Recipe:
    """
    Create a Recipe (plus its Ingredients and Steps) from a plain dict,
    as returned by the Gemini parser.

    Only known model fields are extracted from the dict — extra keys that
    Gemini or JSON-LD may include (e.g. @type, image, author) are silently
    ignored to prevent TypeError crashes.
    """
    ingredients_data = data.get("ingredients") or []
    steps_data = data.get("steps") or []

    recipe_kwargs = {k: v for k, v in data.items() if k in _RECIPE_FIELDS}
    recipe = Recipe(**recipe_kwargs)
    session.add(recipe)
    session.flush()  # populate recipe.id

    for ing in ingredients_data:
        if not isinstance(ing, dict):
            continue
        ing_kwargs = {k: v for k, v in ing.items() if k in _INGREDIENT_FIELDS}
        # Only name is required; amount and unit are optional
        if not ing_kwargs.get("name"):
            continue
        session.add(Ingredient(recipe_id=recipe.id, **ing_kwargs))

    for step in steps_data:
        if not isinstance(step, dict):
            continue
        step_kwargs = {k: v for k, v in step.items() if k in _STEP_FIELDS}
        # Skip steps missing required fields
        if not all(k in step_kwargs for k in _STEP_FIELDS):
            continue
        session.add(Step(recipe_id=recipe.id, **step_kwargs))

    session.commit()
    session.refresh(recipe)
    return recipe


@trace_call
def _build_recipe_draft(data: dict) -> RecipeCreate:
    """
    Normalize extracted AI output into a draft payload suitable for the Create page.
    Invalid optional fields are dropped so the user can review and save manually.
    """
    raw_name = data.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        raise HTTPException(
            status_code=422,
            detail="AI could not extract a recipe from this content. Please try with clearer content.",
        )

    raw_description = data.get("description")
    description = raw_description.strip() if isinstance(raw_description, str) else None
    description = description or None

    raw_category = data.get("category")
    category = raw_category.strip() if isinstance(raw_category, str) else None
    if category not in VALID_CATEGORIES:
        category = None

    def _clean_int(value, *, minimum: int) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < minimum:
            return None
        return value

    ingredients: list[dict] = []
    for item in data.get("ingredients") or []:
        if not isinstance(item, dict):
            continue
        raw_ing_name = item.get("name")
        ing_name = raw_ing_name.strip() if isinstance(raw_ing_name, str) else ""
        if not ing_name:
            continue

        entry = {"name": ing_name}
        amount = item.get("amount")
        if not isinstance(amount, bool) and isinstance(amount, (int, float)) and amount > 0:
            entry["amount"] = float(amount)
            raw_unit = item.get("unit")
            unit = raw_unit.strip() if isinstance(raw_unit, str) else ""
            if unit:
                entry["unit"] = unit
        ingredients.append(entry)

    steps: list[dict] = []
    for index, item in enumerate(data.get("steps") or [], start=1):
        if not isinstance(item, dict):
            continue
        raw_instruction = item.get("instruction")
        instruction = raw_instruction.strip() if isinstance(raw_instruction, str) else ""
        if not instruction:
            continue
        steps.append({"order": index, "instruction": instruction})

    return RecipeCreate.model_validate(
        {
            "name": name,
            "description": description,
            "category": category,
            "prep_time": _clean_int(data.get("prep_time"), minimum=0),
            "cook_time": _clean_int(data.get("cook_time"), minimum=0),
            "servings": _clean_int(data.get("servings"), minimum=1),
            "ingredients": ingredients,
            "steps": steps,
        }
    )


# ── Recipes ───────────────────────────────────────────────────────────────────

@app.post("/recipes", response_model=RecipeRead, status_code=201)
@trace_call
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
@trace_call
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
@trace_call
def get_recipe(
    recipe_id: RecordId,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """Get a single recipe by ID, including all ingredients and steps."""
    recipe = _get_recipe_or_404(recipe_id, session)
    return _build_recipe_read(recipe)


@app.put("/recipes/{recipe_id}", response_model=RecipeRead)
@trace_call
def update_recipe(
    recipe_id: RecordId,
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


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/token")
@trace_call
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
    """Issue a JWT for the configured admin user (form fields: username, password)."""
    if not auth.authenticate(form_data.username, form_data.password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth.create_access_token({"sub": form_data.username, "role": "admin"})
    return {"access_token": token, "token_type": "bearer"}


@app.delete("/recipes/{recipe_id}", status_code=204, response_model=None)
@trace_call
def delete_recipe(
    recipe_id: RecordId,
    session: Session = Depends(get_session),
    current_user: dict = Depends(auth.get_current_user),
) -> None:
    """Delete a recipe and all its ingredients/steps (cascade). Admin only."""
    recipe = _get_recipe_or_404(recipe_id, session)
    session.delete(recipe)
    session.commit()


# ── Ingredients ───────────────────────────────────────────────────────────────

@app.post("/recipes/{recipe_id}/ingredients", response_model=IngredientRead, status_code=201)
@trace_call
def add_ingredient(
    recipe_id: RecordId,
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


@app.delete("/ingredients/{ingredient_id}", status_code=204, response_model=None)
@trace_call
def delete_ingredient(
    ingredient_id: RecordId,
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
@trace_call
def add_step(
    recipe_id: RecordId,
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


@app.delete("/steps/{step_id}", status_code=204, response_model=None)
@trace_call
def delete_step(
    step_id: RecordId,
    session: Session = Depends(get_session),
) -> None:
    """Remove a step by ID."""
    step = session.get(Step, step_id)
    if not step:
        raise HTTPException(status_code=404, detail=f"Step {step_id} not found")
    session.delete(step)
    session.commit()


# ── AI Import ─────────────────────────────────────────────────────────────────

@app.post("/recipes/from-url/preview", response_model=RecipeCreate)
@trace_call
async def preview_from_url(
    payload: ImportFromURLRequest,
) -> RecipeCreate:
    """
    Fetch a URL and extract a recipe draft without saving it.
    Used by the frontend to open the Create page prefilled with imported data.
    """
    recipe_data = await extract_recipe_from_url(str(payload.url))
    return _build_recipe_draft(recipe_data)


@app.post("/recipes/from-url", response_model=RecipeRead, status_code=201)
@trace_call
async def import_from_url(
    payload: ImportFromURLRequest,
    session: Session = Depends(get_session),
) -> RecipeRead:
    """
    Fetch a URL, extract visible text (+ og:image), and use Gemini to parse
    a recipe from the content.
    """
    recipe_data = await extract_recipe_from_url(str(payload.url))
    recipe = _create_recipe_from_dict(recipe_data, session)
    return _build_recipe_read(recipe)


@app.post("/recipes/from-text", response_model=RecipeRead, status_code=201)
@trace_call
async def import_from_text(
    text: str = Form("", description="Recipe text to extract from"),
    image: Optional[UploadFile] = File(default=None, description="Optional image file"),
    session: Session = Depends(get_session),
) -> RecipeRead:
    """
    Send pasted text (and an optional image file) to Gemini to extract a recipe.
    Accepts multipart/form-data with a required 'text' field and an optional 'image' file.
    """
    image_bytes: Optional[bytes] = await image.read() if image else None
    recipe_data = await run_in_threadpool(extract_recipe_from_text, text, image_bytes)
    recipe = _create_recipe_from_dict(recipe_data, session)
    return _build_recipe_read(recipe)


# ── AI Utilities ──────────────────────────────────────────────────────────────

@app.get("/recipes/{recipe_id}/enhance")
@trace_call
def enhance_recipe_tips(
    recipe_id: RecordId,
    session: Session = Depends(get_session),
) -> dict:
    """Return 3 AI-generated improvement tips for the recipe in Hebrew."""
    recipe = _get_recipe_or_404(recipe_id, session)
    tips = enhance_recipe(recipe.name, [i.name for i in recipe.ingredients])
    return {"tips": tips}


@app.post("/recipes/suggest")
@trace_call
def suggest_recipe_endpoint() -> dict:
    """Generate a random Israeli recipe and return it as a dict (not saved to DB)."""
    return suggest_recipe()


@app.post("/recipes/suggest/stage", response_model=SuggestStageResponse)
@trace_call
def suggest_recipe_stage_endpoint(payload: SuggestStageRequest) -> SuggestStageResponse:
    """Generate one validated stage of the AI recipe suggestion flow."""
    result = suggest_recipe_stage(payload.stage, payload.recipe, payload.prompt)
    return SuggestStageResponse(**result)


@app.post("/recipes/recommend")
@trace_call
def recommend_recipes_endpoint(payload: RecommendRequest) -> dict:
    """Return a short Hebrew recommendation given a search query and list of recipe names."""
    recommendation = recommend_recipes(payload.query, payload.recipe_names)
    return {"recommendation": recommendation}
