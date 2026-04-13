from typing import Optional, List
from pydantic import BaseModel


# ── Ingredient ──────────────────────────────────────────────────────────────

class IngredientCreate(BaseModel):
    name: str
    amount: float
    unit: str


class IngredientRead(BaseModel):
    id: int
    recipe_id: int
    name: str
    amount: float
    unit: str

    model_config = {"from_attributes": True}


# ── Step ─────────────────────────────────────────────────────────────────────

class StepCreate(BaseModel):
    order: int
    instruction: str


class StepRead(BaseModel):
    id: int
    recipe_id: int
    order: int
    instruction: str

    model_config = {"from_attributes": True}


# ── Recipe ───────────────────────────────────────────────────────────────────

class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None
    ingredients: List[IngredientCreate] = []
    steps: List[StepCreate] = []


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None


class RecipeRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None
    ingredients: List[IngredientRead] = []
    steps: List[StepRead] = []

    model_config = {"from_attributes": True}


# ── AI Import ─────────────────────────────────────────────────────────────────

class ImportFromURLRequest(BaseModel):
    url: str


# ImportFromTextRequest is intentionally omitted — the /recipes/from-text
# endpoint uses multipart/form-data (Form + UploadFile), not a JSON body.
