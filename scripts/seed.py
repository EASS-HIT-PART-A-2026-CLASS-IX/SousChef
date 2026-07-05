"""
SousChef seed script.

Populates the backend with a few sample recipes via the REST API so a fresh
checkout has data to demo with. Idempotent: recipes whose name already exists
are skipped.

Run (with the API up):  uv run python scripts/seed.py
"""
from __future__ import annotations

import os

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

SAMPLE_RECIPES: list[dict] = [
    {
        "name": "שקשוקה קלאסית",
        "description": "שקשוקה עם רוטב עגבניות עשיר וביצים רכות",
        "category": "ארוחת בוקר",
        "prep_time": 10,
        "cook_time": 20,
        "servings": 2,
        "ingredients": [
            {"name": "עגבניות מרוסקות", "amount": 400, "unit": "גרם"},
            {"name": "ביצים", "amount": 4, "unit": "יחידה"},
            {"name": "בצל", "amount": 1, "unit": "יחידה"},
            {"name": "פפריקה מתוקה", "amount": 1, "unit": "כפית"},
        ],
        "steps": [
            {"order": 1, "instruction": "לטגן את הבצל עד להזהבה"},
            {"order": 2, "instruction": "להוסיף עגבניות ותבלינים ולבשל 10 דקות"},
            {"order": 3, "instruction": "ליצור גומות, לשבור ביצים ולכסות עד שהחלבון מתייצב"},
        ],
    },
    {
        "name": "סלט קינואה עם ירקות",
        "description": "סלט קינואה קליל עם ירקות טריים ולימון",
        "category": "ארוחת צהריים",
        "prep_time": 15,
        "cook_time": 15,
        "servings": 4,
        "ingredients": [
            {"name": "קינואה", "amount": 1, "unit": "כוס"},
            {"name": "מלפפון", "amount": 2, "unit": "יחידה"},
            {"name": "עגבניות שרי", "amount": 200, "unit": "גרם"},
            {"name": "לימון", "amount": 1, "unit": "יחידה"},
        ],
        "steps": [
            {"order": 1, "instruction": "לבשל את הקינואה לפי הוראות האריזה ולצנן"},
            {"order": 2, "instruction": "לקצוץ את הירקות לקוביות קטנות"},
            {"order": 3, "instruction": "לערבב הכל עם מיץ לימון, שמן זית ומלח"},
        ],
    },
    {
        "name": "עוגת שוקולד פשוטה",
        "description": "עוגת שוקולד רכה בקערה אחת",
        "category": "קינוח",
        "prep_time": 15,
        "cook_time": 35,
        "servings": 8,
        "ingredients": [
            {"name": "קמח", "amount": 1.5, "unit": "כוס"},
            {"name": "קקאו", "amount": 0.5, "unit": "כוס"},
            {"name": "סוכר", "amount": 1, "unit": "כוס"},
            {"name": "ביצים", "amount": 3, "unit": "יחידה"},
        ],
        "steps": [
            {"order": 1, "instruction": "לחמם תנור ל-170 מעלות"},
            {"order": 2, "instruction": "לערבב את כל המרכיבים לבלילה אחידה"},
            {"order": 3, "instruction": "לאפות 35 דקות ולצנן לפני ההגשה"},
        ],
    },
]


def seed(client) -> int:
    """
    Create any SAMPLE_RECIPES missing from the API (matched by name).
    Accepts any httpx-compatible client. Returns the number created.
    """
    resp = client.get("/recipes")
    resp.raise_for_status()
    existing_names = {r["name"] for r in resp.json()}

    created = 0
    for recipe in SAMPLE_RECIPES:
        if recipe["name"] in existing_names:
            continue
        client.post("/recipes", json=recipe).raise_for_status()
        created += 1
    return created


def main() -> None:
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        created = seed(client)
    print(f"Seed complete: {created} recipe(s) created, "
          f"{len(SAMPLE_RECIPES) - created} already existed.")


if __name__ == "__main__":
    main()
