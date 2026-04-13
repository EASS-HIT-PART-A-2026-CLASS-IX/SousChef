from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship


class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    prep_time: Optional[int] = None   # minutes
    cook_time: Optional[int] = None   # minutes
    servings: Optional[int] = None

    ingredients: List["Ingredient"] = Relationship(
        back_populates="recipe",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    steps: List["Step"] = Relationship(
        back_populates="recipe",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Ingredient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id")
    name: str
    amount: float
    unit: str

    recipe: Optional[Recipe] = Relationship(back_populates="ingredients")


class Step(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id")
    order: int
    instruction: str

    recipe: Optional[Recipe] = Relationship(back_populates="steps")
