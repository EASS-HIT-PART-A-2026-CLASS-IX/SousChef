# 🍳 SousChef API

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![SQLModel](https://img.shields.io/badge/SQLModel-ORM-blueviolet)](https://sqlmodel.tiangolo.com/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5--flash-orange?logo=google)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-ready REST API for managing recipes — built with **FastAPI**, **SQLModel**, and **SQLite**. Ships with an AI-powered import feature that uses **Google Gemini 2.5 Flash** to extract structured recipes from any URL or free-form text.

> *Your AI sous-chef in the terminal.*

> 📚 **EX1 – EASS 2026, Class IX @ HIT**
> This project will be extended in EX2 (Streamlit UI / Typer CLI) and EX3 (multi-service stack).

---

## ✨ Features

- **Full CRUD** for recipes, ingredients, and steps
- **Nested creation** — supply ingredients and steps inline when creating a recipe
- **Category filtering** on the list endpoint (`?category=breakfast`)
- **Cascade deletes** — removing a recipe removes all its ingredients and steps
- **AI import from URL** — fetches a page, extracts schema.org/Recipe JSON-LD or visible text, and lets Gemini structure it
- **AI import from text/image** — paste raw text or upload a photo; Gemini extracts the recipe
- **Docker + Docker Compose** — fully containerised, SQLite persisted via volume
- **34 pytest tests** — in-memory DB, all external calls mocked, zero network access required

---

## 🗂️ Project Structure

```
souschef/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, all routers, lifespan startup
│   ├── database.py      # SQLite engine + get_session dependency
│   ├── models.py        # SQLModel table models (Recipe, Ingredient, Step)
│   ├── schemas.py       # Pydantic request/response schemas
│   └── ai.py            # Gemini 2.5 Flash integration + JSON-LD scraping
├── tests/
│   └── test_recipes.py  # 34 pytest tests across 8 test classes
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml       # uv-managed dependencies
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- A free [Gemini API key](https://aistudio.google.com/app/apikey)
- [uv](https://docs.astral.sh/uv/) *(recommended)* or pip

### 1. Clone & configure

```bash
git clone <repo-url>
cd souschef
cp .env.example .env
```

Open `.env` and set your key:

```env
GEMINI_API_KEY=your_actual_key_here
```

### 2. Install dependencies

**With uv (recommended):**
```bash
# Install uv (Windows PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install uv (macOS / Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install
uv sync --extra dev
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

**With pip:**
```bash
python -m venv venv
source venv/bin/activate         # macOS / Linux
venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

| | |
|---|---|
| **API base** | http://localhost:8000 |
| **Swagger UI** | http://localhost:8000/docs |
| **ReDoc** | http://localhost:8000/redoc |

---

## 🐳 Docker

```bash
# Build and start
docker compose up --build

# Run in background
docker compose up --build -d

# Stop
docker compose down
```

The SQLite database is persisted to `./data/recipes.db` on your host machine via a volume mount, so data survives container restarts.

---

## 🧪 Tests

```bash
# Run all tests
pytest

# Verbose output with test names
pytest -v

# Run a specific test class
pytest tests/test_recipes.py::TestCreateRecipe -v

# Suppress the pytest cache (useful on some Windows setups)
pytest -v -p no:cacheprovider
```

All 34 tests use an **in-memory SQLite database** and **mock every external call** (Gemini API, httpx) — no API key or network access needed.

---

## 📡 API Reference

### Recipes

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes` | `201` | Create a recipe (with optional nested ingredients & steps) |
| `GET` | `/recipes` | `200` | List all recipes — filter with `?category=<value>` |
| `GET` | `/recipes/{id}` | `200` | Get a single recipe with all ingredients and steps |
| `PUT` | `/recipes/{id}` | `200` | Partially update a recipe's fields |
| `DELETE` | `/recipes/{id}` | `204` | Delete a recipe (cascades to ingredients and steps) |

### Ingredients

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes/{id}/ingredients` | `201` | Add an ingredient to a recipe |
| `DELETE` | `/ingredients/{id}` | `204` | Remove an ingredient |

### Steps

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes/{id}/steps` | `201` | Add a step to a recipe |
| `DELETE` | `/steps/{id}` | `204` | Remove a step |

### AI Import

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/recipes/from-url` | `201` | Fetch a URL and import the recipe via Gemini |
| `POST` | `/recipes/from-text` | `201` | Import from pasted text and/or an uploaded image |

#### How AI import works

`/recipes/from-url` uses a two-stage extraction strategy:
1. **JSON-LD first** — scans the page for a `schema.org/Recipe` object (embedded by most major recipe sites). When found, this clean structured data is sent directly to Gemini.
2. **Visible text fallback** — strips nav/scripts/footers and sends the remaining text (+ `og:image` if available) to Gemini.

`/recipes/from-text` accepts `multipart/form-data` with a `text` field and an optional `image` file.

> **Note:** Instagram, Facebook, and TikTok actively block scraping. For those, copy the recipe text and use `/recipes/from-text` instead.

---

## 🔧 Example Requests

<details>
<summary><b>Create a recipe</b></summary>

```bash
curl -s -X POST http://localhost:8000/recipes \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Classic Omelette",
    "category": "breakfast",
    "prep_time": 5,
    "cook_time": 5,
    "servings": 1,
    "ingredients": [
      {"name": "eggs",   "amount": 3,    "unit": "whole"},
      {"name": "butter", "amount": 1,    "unit": "tbsp"},
      {"name": "salt",   "amount": 0.25, "unit": "tsp"}
    ],
    "steps": [
      {"order": 1, "instruction": "Crack eggs into a bowl and whisk with salt."},
      {"order": 2, "instruction": "Melt butter in a pan over medium heat."},
      {"order": 3, "instruction": "Pour in eggs and fold gently until just set."}
    ]
  }' | python -m json.tool
```
</details>

<details>
<summary><b>List recipes / filter by category</b></summary>

```bash
# All recipes
curl -s http://localhost:8000/recipes | python -m json.tool

# Only breakfast recipes
curl -s "http://localhost:8000/recipes?category=breakfast" | python -m json.tool
```
</details>

<details>
<summary><b>Update a recipe</b></summary>

```bash
curl -s -X PUT http://localhost:8000/recipes/1 \
  -H "Content-Type: application/json" \
  -d '{"description": "A quick French-style omelette.", "servings": 2}' \
  | python -m json.tool
```
</details>

<details>
<summary><b>AI import from a URL</b></summary>

```bash
curl -s -X POST http://localhost:8000/recipes/from-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.allrecipes.com/recipe/10813/best-chocolate-chip-cookies/"}' \
  | python -m json.tool
```
</details>

<details>
<summary><b>AI import from text</b></summary>

```bash
# Text only
curl -s -X POST http://localhost:8000/recipes/from-text \
  -F "text=Banana Bread: Mash 3 ripe bananas. Mix with 1/3 cup melted butter, 3/4 cup sugar, 1 egg, 1 tsp vanilla, 1 tsp baking soda, pinch of salt, 1.5 cups flour. Bake at 175°C for 60 minutes." \
  | python -m json.tool

# Text + image file
curl -s -X POST http://localhost:8000/recipes/from-text \
  -F "text=Extract the recipe from this photo" \
  -F "image=@/path/to/recipe_photo.jpg" \
  | python -m json.tool
```
</details>

<details>
<summary><b>Delete a recipe</b></summary>

```bash
curl -s -X DELETE http://localhost:8000/recipes/1 -w "Status: %{http_code}\n"
```
</details>

---

## ⚙️ Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes (for AI import) | Google Gemini API key — get one free at [aistudio.google.com](https://aistudio.google.com/app/apikey) |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | [FastAPI](https://fastapi.tiangolo.com/) |
| ORM / validation | [SQLModel](https://sqlmodel.tiangolo.com/) (SQLAlchemy + Pydantic) |
| Database | SQLite (file-based, zero config) |
| AI extraction | [Google Gemini 2.5 Flash](https://ai.google.dev/) via `google-genai` |
| HTTP client | [httpx](https://www.python-httpx.org/) |
| HTML parsing | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Testing | [pytest](https://pytest.org/) |
| Containerisation | Docker + Docker Compose |

---

## 📄 License

MIT
