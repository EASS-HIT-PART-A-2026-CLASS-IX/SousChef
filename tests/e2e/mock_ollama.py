"""
Mock Ollama daemon used by the e2e suite when E2E_AI_MODE=mock.

Exposes POST /api/generate and returns canned content based on prompt heuristics:
  * "Extract the recipe"            → recipe JSON (extraction prompt)
  * "שלב 1: החזר רק את שם המתכון"   → staged recipe name JSON
  * "שלב 2:"                        → staged description JSON
  * "שלב 3:"                        → staged meta JSON
  * "שלב 4:"                        → staged ingredients JSON
  * "שלב 5:"                        → staged steps JSON
  * "צור מתכון ישראלי"              → recipe JSON (legacy suggest)
  * "המלץ בעברית"                   → short Hebrew recommendation
  * "תן 3 טיפים"                     → 3 short Hebrew tips
  * anything else                    → echo

Also exposes GET /__hits to inspect prompts seen so far (for assertions).

Run directly:  python -m tests.e2e.mock_ollama --port 11500
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()
HITS: list[dict[str, Any]] = []
FAILED_STAGES: set[str] = set()
CONFIG: dict[str, set[str]] = {
    "fail_stage_once": set(),
    "fail_stage_always": set(),
}


SAMPLE_RECIPE = {
    "name": "מתכון ניסוי E2E",
    "description": "מתכון שנוצר על ידי שרת ה-mock לבדיקות e2e",
    "category": "ארוחת ערב",
    "prep_time": 10,
    "cook_time": 20,
    "servings": 3,
    "ingredients": [
        {"name": "עגבנייה", "amount": 2, "unit": "יח'"},
        {"name": "שמן זית", "amount": 30, "unit": "מ\"ל"},
    ],
    "steps": [
        {"order": 1, "instruction": "לחתוך עגבניות"},
        {"order": 2, "instruction": "לערבב עם שמן זית"},
    ],
}


def _canned_response(prompt: str) -> str:
    p = prompt or ""
    fail_once = {
        stage.strip()
        for stage in os.getenv("MOCK_OLLAMA_FAIL_STAGE_ONCE", "").split(",")
        if stage.strip()
    } | CONFIG["fail_stage_once"]
    fail_always = CONFIG["fail_stage_always"]

    def maybe_fail(stage: str) -> str | None:
        if stage in fail_always:
            return "not-json"
        if stage in fail_once and stage not in FAILED_STAGES:
            FAILED_STAGES.add(stage)
            return "not-json"
        return None

    if "Extract the recipe" in p or "recipe extraction assistant" in p:
        return json.dumps(SAMPLE_RECIPE, ensure_ascii=False)
    if "שלב 1: החזר רק את שם המתכון" in p:
        if (bad := maybe_fail("name")) is not None:
            return bad
        return json.dumps({"name": SAMPLE_RECIPE["name"]}, ensure_ascii=False)
    if "שלב 2:" in p:
        if (bad := maybe_fail("description")) is not None:
            return bad
        return json.dumps({"description": SAMPLE_RECIPE["description"]}, ensure_ascii=False)
    if "שלב 3:" in p:
        if (bad := maybe_fail("meta")) is not None:
            return bad
        return json.dumps(
            {
                "category": SAMPLE_RECIPE["category"],
                "prep_time": SAMPLE_RECIPE["prep_time"],
                "cook_time": SAMPLE_RECIPE["cook_time"],
                "servings": SAMPLE_RECIPE["servings"],
            },
            ensure_ascii=False,
        )
    if "שלב 4:" in p:
        if (bad := maybe_fail("ingredients")) is not None:
            return bad
        return json.dumps({"ingredients": SAMPLE_RECIPE["ingredients"]}, ensure_ascii=False)
    if "שלב 5:" in p:
        if (bad := maybe_fail("steps")) is not None:
            return bad
        return json.dumps({"steps": SAMPLE_RECIPE["steps"]}, ensure_ascii=False)
    if "צור מתכון ישראלי" in p:
        return json.dumps(SAMPLE_RECIPE, ensure_ascii=False)
    if "המלץ בעברית" in p:
        return "אני ממליץ על המתכון 'מתכון ניסוי E2E' — מהיר, טעים ומתאים לכל אירוע."
    if "תן 3 טיפים" in p:
        return "1. הוסיפו מלח ים. 2. הקפידו על שמן זית איכותי. 3. הגישו מיד."
    return "תשובה כללית מ-mock"


@app.post("/api/generate")
async def generate(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    HITS.append({
        "model": body.get("model"),
        "prompt": prompt,
        "format": body.get("format"),
        "has_images": bool(body.get("images")),
    })
    return {
        "model": body.get("model", "mock"),
        "response": _canned_response(prompt),
        "done": True,
    }


@app.get("/__hits")
def hits():
    return {"count": len(HITS), "hits": HITS}


@app.post("/__reset")
def reset():
    HITS.clear()
    FAILED_STAGES.clear()
    CONFIG["fail_stage_once"].clear()
    CONFIG["fail_stage_always"].clear()
    return {"ok": True}


@app.post("/__configure")
async def configure(request: Request):
    body = await request.json()
    CONFIG["fail_stage_once"] = set(body.get("fail_stage_once") or [])
    CONFIG["fail_stage_always"] = set(body.get("fail_stage_always") or [])
    return {"ok": True}


@app.get("/")
def root():
    # Ollama's real root returns "Ollama is running" — keep parity for friendliness.
    return {"status": "Ollama mock is running"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11500)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
