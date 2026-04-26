from typing import Any, Literal, Optional, List
from pydantic import BaseModel, AnyHttpUrl, Field, field_validator


VALID_CATEGORIES = {"ארוחת בוקר", "ארוחת צהריים", "ארוחת ערב", "קינוח", "חטיף", "אחר"}


# ── Ingredient ────────────────────────────────────────────────────────────────

class IngredientCreate(BaseModel):
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("unit")
    @classmethod
    def unit_not_blank_when_provided(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("must not be blank when provided")
        return v

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class IngredientRead(BaseModel):
    id: int
    recipe_id: int
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Step ──────────────────────────────────────────────────────────────────────

class StepCreate(BaseModel):
    order: int
    instruction: str

    @field_validator("order")
    @classmethod
    def positive_order(cls, v: int) -> int:
        if v < 1:
            raise ValueError("order must be 1 or greater")
        return v

    @field_validator("instruction")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class StepRead(BaseModel):
    id: int
    recipe_id: int
    order: int
    instruction: str

    model_config = {"from_attributes": True}


# ── Recipe ────────────────────────────────────────────────────────────────────

class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None
    ingredients: List[IngredientCreate] = []
    steps: List[StepCreate] = []

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if v not in VALID_CATEGORIES:
                raise ValueError(
                    f"must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
                )
        return v

    @field_validator("prep_time", "cook_time", "servings")
    @classmethod
    def non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("must be 0 or greater")
        return v


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("must not be blank")
        return v.strip() if v else v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if v not in VALID_CATEGORIES:
                raise ValueError(
                    f"must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
                )
        return v

    @field_validator("prep_time", "cook_time", "servings")
    @classmethod
    def non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("must be 0 or greater")
        return v


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
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def http_only(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https")
        return v

# ImportFromTextRequest is intentionally omitted — the /recipes/from-text
# endpoint uses multipart/form-data (Form + UploadFile), not a JSON body.


class RecommendRequest(BaseModel):
    query: str
    recipe_names: List[str] = []


SuggestStage = Literal["name", "description", "meta", "ingredients", "steps"]


class SuggestStageRequest(BaseModel):
    stage: SuggestStage
    recipe: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None


class SuggestStageResponse(BaseModel):
    stage: SuggestStage
    patch: dict[str, Any]
    recipe: dict[str, Any]
    done: bool
