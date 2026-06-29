"""
AI-powered recipe extraction helpers.

Supports three backends, selected via the AI_PROVIDER environment variable:

    AI_PROVIDER=gemini    (default) — Google Gemini (cloud, requires GEMINI_API_KEY)
    AI_PROVIDER=ollama              — Local Ollama daemon (/api/generate)
    AI_PROVIDER=llamacpp            — llama.cpp server (llama-server, /v1/chat/completions)

Ollama configuration:
    OLLAMA_BASE_URL   default "http://localhost:11434"
    OLLAMA_MODEL      default "gemma4:26b"  (must be vision-capable for image inputs)

llama.cpp configuration:
    LLAMACPP_BASE_URL   default "http://localhost:8080"
    LLAMACPP_MAX_TOKENS default 900
    LLAMACPP_TIMEOUT    default 180

Public functions (extract_recipe_from_text, extract_recipe_from_url, enhance_recipe,
suggest_recipe, recommend_recipes) keep the same signatures regardless of provider,
so callers and tests do not need to change.
"""
from __future__ import annotations

import ast
import base64
import json
import os
import re
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.observability import get_logger, trace_call
from app.schemas import VALID_CATEGORIES, SuggestStage

logger = get_logger(__name__)

# ── Provider configuration ────────────────────────────────────────────────────

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "900"))

LLAMACPP_BASE_URL = os.getenv("LLAMACPP_BASE_URL", "http://localhost:8080").rstrip("/")
LLAMACPP_TIMEOUT = float(os.getenv("LLAMACPP_TIMEOUT", "180"))
LLAMACPP_MAX_TOKENS = int(os.getenv("LLAMACPP_MAX_TOKENS", "900"))
# Prepend /no_think to the user message to disable Qwen3's chain-of-thought reasoning.
# This is safe on all models (non-Qwen3 models simply ignore the prefix).
# Set LLAMACPP_NO_THINK=false only if you intentionally want thinking tokens.
LLAMACPP_NO_THINK = os.getenv("LLAMACPP_NO_THINK", "true").lower() != "false"

_JSON_STRING_LIMIT = 240
_INGREDIENT_NAME_LIMIT = 80
_UNIT_LIMIT = 24
_STEP_LIMIT = 280
_MAX_INGREDIENTS = 20
_MAX_STEPS = 20

SUGGEST_STAGES: tuple[SuggestStage, ...] = ("name", "description", "meta", "ingredients", "steps")
SUGGEST_STAGE_ATTEMPTS = 3


@trace_call
def _nullable(schema: dict) -> dict:
    """Allow either the given schema or null."""
    return {"anyOf": [schema, {"type": "null"}]}


@trace_call
def _bounded_string(max_length: int) -> dict:
    """A trimmed string field with a practical maximum length."""
    return {"type": "string", "minLength": 1, "maxLength": max_length}


# ── Recipe JSON schema (used for Ollama structured-output / constrained decoding) ──

RECIPE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name":        _bounded_string(120),
        "description": _nullable(_bounded_string(_JSON_STRING_LIMIT)),
        "category":    {"type": "string", "enum": ["ארוחת בוקר", "ארוחת צהריים", "ארוחת ערב", "קינוח", "חטיף", "אחר"]},
        "prep_time":   _nullable({"type": "integer", "minimum": 0, "maximum": 1_440}),
        "cook_time":   _nullable({"type": "integer", "minimum": 0, "maximum": 1_440}),
        "servings":    _nullable({"type": "integer", "minimum": 1, "maximum": 100}),
        "ingredients": {
            "type": "array",
            "minItems": 1,
            "maxItems": _MAX_INGREDIENTS,
            "items": {
                "type": "object",
                "properties": {
                    "name":   _bounded_string(_INGREDIENT_NAME_LIMIT),
                    "amount": _nullable({"type": "number", "exclusiveMinimum": 0, "maximum": 10_000}),
                    "unit":   _nullable(_bounded_string(_UNIT_LIMIT)),
                },
                "required": ["name", "amount", "unit"],
                "additionalProperties": False,
            },
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": _MAX_STEPS,
            "items": {
                "type": "object",
                "properties": {
                    "order":       {"type": "integer", "minimum": 1, "maximum": _MAX_STEPS},
                    "instruction": _bounded_string(_STEP_LIMIT),
                },
                "required": ["order", "instruction"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "description", "category", "prep_time", "cook_time", "servings", "ingredients", "steps"],
    "additionalProperties": False,
}

RECIPE_NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": _bounded_string(120),
    },
    "required": ["name"],
    "additionalProperties": False,
}

RECIPE_DESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "description": _nullable(_bounded_string(_JSON_STRING_LIMIT)),
    },
    "required": ["description"],
    "additionalProperties": False,
}

RECIPE_META_SCHEMA = {
    "type": "object",
    "properties": {
        "category": RECIPE_JSON_SCHEMA["properties"]["category"],
        "prep_time": RECIPE_JSON_SCHEMA["properties"]["prep_time"],
        "cook_time": RECIPE_JSON_SCHEMA["properties"]["cook_time"],
        "servings": RECIPE_JSON_SCHEMA["properties"]["servings"],
    },
    "required": ["category", "prep_time", "cook_time", "servings"],
    "additionalProperties": False,
}

RECIPE_INGREDIENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "ingredients": RECIPE_JSON_SCHEMA["properties"]["ingredients"],
    },
    "required": ["ingredients"],
    "additionalProperties": False,
}

RECIPE_STEPS_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": RECIPE_JSON_SCHEMA["properties"]["steps"],
    },
    "required": ["steps"],
    "additionalProperties": False,
}


# ── Prompt template ───────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a recipe extraction assistant. Extract the recipe from the following content \
and return it as a JSON object with this exact structure. \
All text fields (name, description, category, ingredient names, and step instructions) must be written in Hebrew.

{{
  "name": "...",
  "description": "...",
  "category": "ארוחת בוקר|ארוחת צהריים|ארוחת ערב|קינוח|חטיף|אחר",
  "prep_time": <int minutes or null>,
  "cook_time": <int minutes or null>,
  "servings": <int or null>,
  "ingredients": [
    {{"name": "...", "amount": <float>, "unit": "..."}},
    ...
  ],
  "steps": [
    {{"order": 1, "instruction": "..."}},
    ...
  ]
}}

For description, prep_time, cook_time, and servings: if the content does not state them \
explicitly, infer reasonable values yourself rather than returning null. Write a short \
one-sentence Hebrew description summarizing the dish, and estimate prep_time and cook_time \
in minutes and servings based on the ingredients and the steps. Use null only if you \
genuinely cannot make a sensible estimate.

Return ONLY the JSON object, no explanation, no markdown fences.
Prefer compact, minified JSON on a single line.
Keep ingredients and steps concise and include only the essential recipe data.

Content:
{content}
"""


# ── Image MIME detection (used by both providers) ─────────────────────────────

_MIME_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
]


@trace_call
def _detect_mime_type(data: bytes) -> Optional[str]:
    """Return the MIME type of *data* based on its magic bytes, or None."""
    for signature, mime in _MIME_SIGNATURES:
        if data[: len(signature)] == signature:
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# ── Shared JSON-response parser ───────────────────────────────────────────────

@trace_call
def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1]).strip()
    return text


@trace_call
def _extract_json_candidate(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


@trace_call
def _repair_json_candidate(text: str) -> str:
    repaired = text.strip()
    repaired = repaired.replace("\u201c", '"').replace("\u201d", '"')
    repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', repaired)
    return repaired


@trace_call
def _decode_json_string_fragment(fragment: str) -> str:
    try:
        return json.loads(f'"{fragment}"')
    except json.JSONDecodeError:
        return fragment


@trace_call
def _extract_partial_string_field(text: str, field_name: str) -> Optional[str]:
    match = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        text,
    )
    if not match:
        return None
    value = _decode_json_string_fragment(match.group(1)).strip()
    return value or None


@trace_call
def _extract_partial_int_field(text: str, field_name: str, *, minimum: int) -> Optional[int]:
    match = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*(null|-?\d+)',
        text,
    )
    if not match:
        return None
    token = match.group(1)
    if token == "null":
        return None
    value = int(token)
    if value < minimum:
        return None
    return value


@trace_call
def _extract_partial_ingredients(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'\{\s*"name"\s*:\s*"((?:\\.|[^"\\])*)"'
        r'(?:\s*,\s*"amount"\s*:\s*(null|-?\d+(?:\.\d+)?))?'
        r'(?:\s*,\s*"unit"\s*:\s*"((?:\\.|[^"\\])*)")?'
        r'\s*\}'
    )

    ingredients: list[dict[str, Any]] = []
    for name_raw, amount_raw, unit_raw in pattern.findall(text):
        name = _decode_json_string_fragment(name_raw).strip()
        if not name:
            continue
        entry: dict[str, Any] = {"name": name}
        if amount_raw and amount_raw != "null":
            entry["amount"] = float(amount_raw)
            unit = _decode_json_string_fragment(unit_raw).strip() if unit_raw else ""
            if unit:
                entry["unit"] = unit
        ingredients.append(entry)
    return ingredients


@trace_call
def _extract_partial_steps(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'\{\s*"order"\s*:\s*\d+\s*,\s*"instruction"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}'
    )

    steps: list[dict[str, Any]] = []
    for index, (instruction_raw,) in enumerate(pattern.findall(text), start=1):
        instruction = _decode_json_string_fragment(instruction_raw).strip()
        if instruction:
            steps.append({"order": index, "instruction": instruction})
    return steps


@trace_call
def _salvage_partial_recipe_json(raw: str) -> Optional[dict[str, Any]]:
    text = _strip_code_fences(raw)
    name = _extract_partial_string_field(text, "name")
    if not name:
        return None

    result: dict[str, Any] = {
        "name": name,
        "ingredients": _extract_partial_ingredients(text),
        "steps": _extract_partial_steps(text),
    }

    description = _extract_partial_string_field(text, "description")
    if description is not None:
        result["description"] = description

    category = _extract_partial_string_field(text, "category")
    if category in VALID_CATEGORIES:
        result["category"] = category

    result["prep_time"] = _extract_partial_int_field(text, "prep_time", minimum=0)
    result["cook_time"] = _extract_partial_int_field(text, "cook_time", minimum=0)
    result["servings"] = _extract_partial_int_field(text, "servings", minimum=1)

    logger.warning(
        "Recovered partial recipe JSON with fields name=%s ingredients=%s steps=%s",
        result.get("name"),
        len(result["ingredients"]),
        len(result["steps"]),
    )
    return result


@trace_call
def _load_json_lenient(raw: str) -> Any:
    text = _strip_code_fences(raw)
    candidates = [text]
    extracted = _extract_json_candidate(text)
    if extracted != text:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        repaired = _repair_json_candidate(candidate)
        if repaired != candidate:
            try:
                data = json.loads(repaired)
                logger.warning("Recovered malformed model JSON with a lightweight repair pass")
                return data
            except json.JSONDecodeError:
                pass

        try:
            data = ast.literal_eval(repaired)
            logger.warning("Recovered malformed model JSON with Python-literal fallback")
            return data
        except (SyntaxError, ValueError):
            continue

    raise json.JSONDecodeError("Invalid JSON object", text, 0)


@trace_call
def _parse_recipe_json(raw: str) -> dict:
    """
    Strip optional markdown code fences and parse a recipe JSON blob.
    Raises HTTPException 422 if the response is not valid JSON or has no name.
    """
    logger.info("Raw model response: %s", raw)

    try:
        data = _load_json_lenient(raw)
    except json.JSONDecodeError:
        partial = _salvage_partial_recipe_json(raw)
        if partial is not None:
            return partial
        logger.warning("Model response could not be parsed as JSON: %s", raw.strip()[:500])
        raise HTTPException(
            status_code=422,
            detail="AI could not extract a recipe from this content. Please try with clearer content.",
        )

    # Some models wrap the result under a "recipe" key — unwrap it
    if isinstance(data, dict) and "recipe" in data and isinstance(data["recipe"], dict):
        data = data["recipe"]

    if not isinstance(data, dict) or not data.get("name"):
        logger.warning("Model returned a dict with no name field: %s", data)
        raise HTTPException(
            status_code=422,
            detail="AI could not extract a recipe from this content. Please try with clearer content.",
        )

    return data


@trace_call
def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a JSON object response from the model."""
    try:
        data = _load_json_lenient(raw)
    except json.JSONDecodeError:
        logger.warning("Model response could not be parsed as JSON object: %s", raw.strip()[:500])
        raise HTTPException(
            status_code=422,
            detail="The AI returned malformed JSON. Please try again.",
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=422,
            detail="The AI returned an unexpected response shape. Please try again.",
        )
    return data


# Back-compat alias — older code/tests may import the Gemini-named helper
_parse_gemini_response = _parse_recipe_json


# ── Gemini backend ────────────────────────────────────────────────────────────

@trace_call
def _get_gemini_client():
    """Return a configured Gemini Client, raising on missing key. Imports lazily."""
    from google import genai  # noqa: WPS433  (lazy import keeps Ollama-only setups light)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Either set it, or set AI_PROVIDER=ollama / AI_PROVIDER=llamacpp to use a local model."
        )
    return genai.Client(api_key=api_key)


@trace_call
def _gemini_generate(prompt: str, image_bytes: Optional[bytes] = None) -> str:
    """Call Gemini once and return the raw response text."""
    from google.genai import errors as genai_errors  # lazy
    from google.genai import types

    client = _get_gemini_client()

    parts: list = [prompt]
    if image_bytes:
        mime_type = _detect_mime_type(image_bytes)
        if mime_type is None:
            logger.warning("Uploaded file does not appear to be a supported image — skipping")
        else:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=parts)
    except genai_errors.ServerError as e:
        logger.warning("Gemini server error: %s", e)
        raise HTTPException(
            status_code=503,
            detail="The AI service is temporarily unavailable due to high demand. Please try again in a moment.",
        )
    except genai_errors.ClientError as e:
        logger.warning("Gemini client error: %s", e)
        raise HTTPException(
            status_code=502,
            detail="The AI service returned an error. Please check your API key and try again.",
        )
    except Exception as e:
        logger.error("Unexpected error calling Gemini: %s", e)
        raise HTTPException(
            status_code=502,
            detail="An unexpected error occurred while contacting the AI service. Please try again.",
        )
    return response.text


# ── Ollama backend ────────────────────────────────────────────────────────────

@trace_call
def _ollama_generate(
    prompt: str,
    image_bytes: Optional[bytes] = None,
    schema: Optional[dict] = None,
    allow_schema_fallback: bool = True,
) -> str:
    """
    Call the local Ollama daemon's /api/generate endpoint and return the response text.
    When ``schema`` is provided it is passed as the ``format`` field, enabling Ollama's
    constrained decoding (structured output) so the response is guaranteed to match the schema.
    When ``image_bytes`` is provided, the configured OLLAMA_MODEL must be vision-capable.
    """
    payload: dict = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "repeat_penalty": 1.3,
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }
    if schema is not None:
        payload["format"] = schema
    if image_bytes:
        # Ollama expects images as a list of base64-encoded strings (no data: prefix)
        payload["images"] = [base64.b64encode(image_bytes).decode("ascii")]

    url = f"{OLLAMA_BASE_URL}/api/generate"
    try:
        # Ollama always runs on localhost; bypass any system HTTP(S)/SOCKS proxy
        # so sandboxed/dev environments with global proxies don't break the call.
        with httpx.Client(trust_env=False, timeout=OLLAMA_TIMEOUT) as client:
            resp = client.post(url, json=payload)
        resp.raise_for_status()
    except httpx.ConnectError as e:
        logger.warning("Could not connect to Ollama at %s: %s", url, e)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not reach Ollama at {OLLAMA_BASE_URL}. "
                "Make sure the Ollama daemon is running (`ollama serve`)."
            ),
        )
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        logger.warning("Ollama returned %s: %s", e.response.status_code, body)
        # 404 typically means the requested model has not been pulled yet
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Ollama does not have model '{OLLAMA_MODEL}'. "
                    f"Run `ollama pull {OLLAMA_MODEL}` and try again."
                ),
            )
        raise HTTPException(
            status_code=502,
            detail=f"Ollama error {e.response.status_code}: {body}",
        )
    except httpx.HTTPError as e:
        logger.error("Unexpected error calling Ollama: %s", e)
        raise HTTPException(
            status_code=502,
            detail="An unexpected error occurred while contacting Ollama.",
        )

    try:
        data = resp.json()
    except ValueError:
        logger.error("Ollama returned non-JSON envelope: %s", resp.text[:300])
        raise HTTPException(status_code=502, detail="Ollama returned a malformed response.")

    response_text = (data.get("response") or "").strip()
    if schema is not None and not response_text and allow_schema_fallback:
        logger.warning(
            "Ollama model '%s' returned an empty response for schema-constrained decoding; retrying without format.",
            OLLAMA_MODEL,
        )
        fallback_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Return ONLY valid JSON that matches this JSON schema. "
            "Do not include explanations, markdown, or any extra text.\n"
            f"JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        return _ollama_generate(
            fallback_prompt,
            image_bytes=image_bytes,
            schema=None,
            allow_schema_fallback=False,
        )

    return response_text


# ── llama.cpp backend ────────────────────────────────────────────────────────

@trace_call
def _llamacpp_generate(
    prompt: str,
    image_bytes: Optional[bytes] = None,
    schema: Optional[dict] = None,
    allow_schema_fallback: bool = True,
) -> str:
    """
    Call a llama.cpp server via its OpenAI-compatible /v1/chat/completions endpoint.
    When ``schema`` is provided it is sent as response_format.json_schema for
    constrained decoding (requires llama-server built with grammar support).
    When ``image_bytes`` is provided the model must be vision-capable (e.g. llava, gemma3).
    """
    content: Any
    if image_bytes:
        mime_type = _detect_mime_type(image_bytes) or "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ]
    else:
        content = prompt

    payload: dict = {
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": LLAMACPP_MAX_TOKENS,
    }
    if LLAMACPP_NO_THINK:
        # Disables Qwen3's chain-of-thought mode via the chat template.
        # Prevents reasoning_content from consuming all available tokens.
        # Non-Qwen3 models silently ignore unknown chat_template_kwargs.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "recipe", "strict": True, "schema": schema},
        }

    url = f"{LLAMACPP_BASE_URL}/v1/chat/completions"
    try:
        with httpx.Client(trust_env=False, timeout=LLAMACPP_TIMEOUT) as client:
            resp = client.post(url, json=payload)
        resp.raise_for_status()
    except httpx.ConnectError as e:
        logger.warning("Could not connect to llama.cpp at %s: %s", url, e)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not reach llama.cpp server at {LLAMACPP_BASE_URL}. "
                "Make sure llama-server is running."
            ),
        )
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        logger.warning("llama.cpp returned %s: %s", e.response.status_code, body)
        raise HTTPException(
            status_code=502,
            detail=f"llama.cpp error {e.response.status_code}: {body}",
        )
    except httpx.HTTPError as e:
        logger.error("Unexpected error calling llama.cpp: %s", e)
        raise HTTPException(
            status_code=502,
            detail="An unexpected error occurred while contacting llama.cpp.",
        )

    try:
        data = resp.json()
        response_text = data["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError):
        logger.error("llama.cpp returned unexpected response shape: %s", resp.text[:300])
        raise HTTPException(status_code=502, detail="llama.cpp returned a malformed response.")

    if schema is not None and not response_text and allow_schema_fallback:
        logger.warning(
            "llama.cpp returned an empty response for schema-constrained decoding; retrying without response_format.",
        )
        fallback_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Return ONLY valid JSON that matches this JSON schema. "
            "Do not include explanations, markdown, or any extra text.\n"
            f"JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        return _llamacpp_generate(
            fallback_prompt,
            image_bytes=image_bytes,
            schema=None,
            allow_schema_fallback=False,
        )

    return response_text


# ── Provider dispatch ─────────────────────────────────────────────────────────

@trace_call
def _generate_text(prompt: str) -> str:
    """Plain text completion — used by enhance/recommend/suggest."""
    if AI_PROVIDER == "ollama":
        return _ollama_generate(prompt)
    if AI_PROVIDER == "llamacpp":
        return _llamacpp_generate(prompt)
    return _gemini_generate(prompt)


@trace_call
def _generate_recipe_json(prompt: str, image_bytes: Optional[bytes] = None) -> str:
    """JSON-mode completion — used by recipe extraction."""
    if AI_PROVIDER == "ollama":
        return _ollama_generate(prompt, image_bytes=image_bytes, schema=RECIPE_JSON_SCHEMA)
    if AI_PROVIDER == "llamacpp":
        return _llamacpp_generate(prompt, image_bytes=image_bytes, schema=RECIPE_JSON_SCHEMA)
    return _gemini_generate(prompt, image_bytes=image_bytes)


@trace_call
def _generate_json_with_schema(prompt: str, schema: dict) -> dict[str, Any]:
    """Generate a small JSON object with the provided schema."""
    if AI_PROVIDER == "ollama":
        raw = _ollama_generate(prompt, schema=schema)
    elif AI_PROVIDER == "llamacpp":
        raw = _llamacpp_generate(prompt, schema=schema)
    else:
        raw = _gemini_generate(prompt)
    return _parse_json_object(raw)


# ── Public API (signatures unchanged, so existing tests keep working) ────────

@trace_call
def extract_recipe_from_text(text: str, image_bytes: Optional[bytes] = None) -> dict:
    """Run the recipe-extraction prompt over text (and optional image bytes)."""
    prompt = EXTRACTION_PROMPT.format(content=text)
    raw = _generate_recipe_json(prompt, image_bytes=image_bytes)
    return _parse_recipe_json(raw)


@trace_call
def enhance_recipe(recipe_name: str, ingredient_names: list[str]) -> str:
    """Return 3 improvement tips for a recipe in Hebrew."""
    prompt = (
        f'אתה שף מקצועי. קיבלת את המתכון: "{recipe_name}". '
        f'מרכיבים: {", ".join(ingredient_names)}. '
        f'תן 3 טיפים קצרים לשיפור בעברית.'
    )
    return _generate_text(prompt)


def _theme(user_prompt: Optional[str]) -> str:
    if user_prompt and user_prompt.strip():
        return (
            f"צור מתכון על פי: {user_prompt.strip()}. "
            "כל הטקסטים חייבים להיות בעברית."
        )
    return (
        "צור מתכון ישראלי מסורתי אחד, הגיוני ומבושל באמת. "
        "כל הטקסטים חייבים להיות בעברית."
    )


@trace_call
def _recipe_context(recipe: dict[str, Any]) -> str:
    """Serialize the recipe-so-far for the next stage prompt."""
    return json.dumps(recipe, ensure_ascii=False, indent=2)


@trace_call
def _build_stage_prompt(
    stage_instruction: str,
    response_shape: str,
    recipe: dict[str, Any],
    user_prompt: Optional[str] = None,
) -> str:
    return (
        f"{_theme(user_prompt)}\n"
        f"{stage_instruction}\n"
        "החזר רק אובייקט JSON תקין, ללא markdown וללא הסברים.\n"
        f"מבנה התשובה:\n{response_shape}\n\n"
        "הקשר מהשלבים הקודמים:\n"
        f"{_recipe_context(recipe)}"
    )


@trace_call
def _suggest_recipe_name(user_prompt: Optional[str] = None) -> dict[str, Any]:
    prompt = (
        f"{_theme(user_prompt)}\n"
        "שלב 1: החזר רק את שם המתכון.\n"
        "החזר רק אובייקט JSON תקין, ללא markdown וללא הסברים.\n"
        'מבנה התשובה:\n{"name": "..."}'
    )
    return _generate_json_with_schema(prompt, RECIPE_NAME_SCHEMA)


@trace_call
def _suggest_recipe_description(recipe: dict[str, Any], user_prompt: Optional[str] = None) -> dict[str, Any]:
    prompt = _build_stage_prompt(
        "שלב 2: על סמך שם המתכון בלבד, כתוב תיאור קצר, טבעי ומעורר תיאבון.",
        '{"description": "..."}',
        recipe,
        user_prompt,
    )
    return _generate_json_with_schema(prompt, RECIPE_DESCRIPTION_SCHEMA)


@trace_call
def _suggest_recipe_meta(recipe: dict[str, Any], user_prompt: Optional[str] = None) -> dict[str, Any]:
    prompt = _build_stage_prompt(
        "שלב 3: החזר רק קטגוריה, זמן הכנה, זמן בישול ומספר מנות שמתאימים למתכון.",
        (
            '{"category": "ארוחת בוקר|ארוחת צהריים|ארוחת ערב|קינוח|חטיף|אחר", '
            '"prep_time": 0, "cook_time": 0, "servings": 1}'
        ),
        recipe,
        user_prompt,
    )
    return _generate_json_with_schema(prompt, RECIPE_META_SCHEMA)


@trace_call
def _suggest_recipe_ingredients(recipe: dict[str, Any], user_prompt: Optional[str] = None) -> dict[str, Any]:
    prompt = _build_stage_prompt(
        "שלב 4: החזר רק רשימת מרכיבים רלוונטית, עם כמויות ויחידות הגיוניות.",
        '{"ingredients": [{"name": "...", "amount": 1, "unit": "..."}]}',
        recipe,
        user_prompt,
    )
    return _generate_json_with_schema(prompt, RECIPE_INGREDIENTS_SCHEMA)


@trace_call
def _suggest_recipe_steps(recipe: dict[str, Any], user_prompt: Optional[str] = None) -> dict[str, Any]:
    prompt = _build_stage_prompt(
        "שלב 5: החזר רק שלבי הכנה קצרים, ברורים ומסודרים לפי הסדר.",
        '{"steps": [{"order": 1, "instruction": "..."}]}',
        recipe,
        user_prompt,
    )
    return _generate_json_with_schema(prompt, RECIPE_STEPS_SCHEMA)


@trace_call
def _stage_message(detail: Any) -> str:
    """Extract a user-facing message from an HTTPException detail payload."""
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "The AI returned invalid data.")
    return str(detail)


@trace_call
def _stage_validation_error(message: str) -> HTTPException:
    """Create a stage validation error that is eligible for retry."""
    return HTTPException(status_code=422, detail=message)


@trace_call
def _normalize_name_patch(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _stage_validation_error("The recipe name must be a non-blank string.")
    return {"name": name.strip()}


@trace_call
def _normalize_description_patch(raw: dict[str, Any]) -> dict[str, Any]:
    description = raw.get("description")
    if description is None:
        return {"description": None}
    if not isinstance(description, str):
        raise _stage_validation_error("The recipe description must be a string or null.")
    trimmed = description.strip()
    return {"description": trimmed or None}


@trace_call
def _coerce_int(value: Any, *, field_name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _stage_validation_error(f"{field_name} must be an integer.")
    if value < minimum:
        raise _stage_validation_error(f"{field_name} must be {minimum} or greater.")
    return value


@trace_call
def _normalize_meta_patch(raw: dict[str, Any]) -> dict[str, Any]:
    category = raw.get("category")
    if not isinstance(category, str) or category.strip() not in VALID_CATEGORIES:
        raise _stage_validation_error("The recipe category must be one of the allowed Hebrew categories.")
    return {
        "category": category.strip(),
        "prep_time": _coerce_int(raw.get("prep_time"), field_name="prep_time", minimum=0),
        "cook_time": _coerce_int(raw.get("cook_time"), field_name="cook_time", minimum=0),
        "servings": _coerce_int(raw.get("servings"), field_name="servings", minimum=1),
    }


@trace_call
def _normalize_ingredients_patch(raw: dict[str, Any]) -> dict[str, Any]:
    ingredients = raw.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise _stage_validation_error("The ingredient list must contain at least one ingredient.")

    normalized: list[dict[str, Any]] = []
    for item in ingredients:
        if not isinstance(item, dict):
            raise _stage_validation_error("Each ingredient must be an object.")

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _stage_validation_error("Each ingredient must have a non-blank name.")

        amount = item.get("amount")
        unit = item.get("unit")
        clean_unit = unit.strip() if isinstance(unit, str) and unit.strip() else None

        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            clean_amount = None
            clean_unit = None
        else:
            clean_amount = float(amount)

        normalized.append(
            {
                "name": name.strip(),
                "amount": clean_amount,
                "unit": clean_unit,
            }
        )

    if not normalized:
        raise _stage_validation_error("The ingredient list must contain at least one ingredient.")

    return {"ingredients": normalized}


@trace_call
def _normalize_steps_patch(raw: dict[str, Any]) -> dict[str, Any]:
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise _stage_validation_error("The step list must contain at least one step.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(steps, start=1):
        if not isinstance(item, dict):
            raise _stage_validation_error("Each step must be an object.")
        instruction = item.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise _stage_validation_error("Each step must have a non-blank instruction.")
        normalized.append({"order": index, "instruction": instruction.strip()})

    return {"steps": normalized}


@trace_call
def _normalize_stage_patch(stage: SuggestStage, raw: dict[str, Any]) -> dict[str, Any]:
    if stage == "name":
        return _normalize_name_patch(raw)
    if stage == "description":
        return _normalize_description_patch(raw)
    if stage == "meta":
        return _normalize_meta_patch(raw)
    if stage == "ingredients":
        return _normalize_ingredients_patch(raw)
    return _normalize_steps_patch(raw)


@trace_call
def _generate_stage_patch(
    stage: SuggestStage,
    recipe: dict[str, Any],
    user_prompt: Optional[str] = None,
) -> dict[str, Any]:
    if stage == "name":
        return _suggest_recipe_name(user_prompt)
    if stage == "description":
        return _suggest_recipe_description(recipe, user_prompt)
    if stage == "meta":
        return _suggest_recipe_meta(recipe, user_prompt)
    if stage == "ingredients":
        return _suggest_recipe_ingredients(recipe, user_prompt)
    return _suggest_recipe_steps(recipe, user_prompt)


@trace_call
def _merge_recipe_patch(recipe: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(recipe)
    merged.update(patch)
    return merged


@trace_call
def suggest_recipe_stage(
    stage: SuggestStage,
    recipe: Optional[dict[str, Any]] = None,
    user_prompt: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generate and validate a single stage of the AI recipe flow.
    Retries malformed or invalid stage outputs up to SUGGEST_STAGE_ATTEMPTS times.
    """
    current_recipe = dict(recipe or {})
    last_message = "The AI returned invalid data."

    for attempt in range(1, SUGGEST_STAGE_ATTEMPTS + 1):
        try:
            raw_patch = _generate_stage_patch(stage, current_recipe, user_prompt)
            patch = _normalize_stage_patch(stage, raw_patch)
            merged = _merge_recipe_patch(current_recipe, patch)
            return {
                "stage": stage,
                "patch": patch,
                "recipe": merged,
                "done": stage == SUGGEST_STAGES[-1],
            }
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            last_message = _stage_message(exc.detail)
            logger.warning("AI stage '%s' failed validation on attempt %s/%s: %s",
                           stage, attempt, SUGGEST_STAGE_ATTEMPTS, last_message)

    raise HTTPException(
        status_code=422,
        detail={
            "stage": stage,
            "message": last_message,
            "attempts": SUGGEST_STAGE_ATTEMPTS,
        },
    )


@trace_call
def suggest_recipe() -> dict:
    """Generate one Israeli recipe in staged calls, carrying prior answers as context."""
    recipe: dict[str, Any] = {}
    for stage in SUGGEST_STAGES:
        result = suggest_recipe_stage(stage, recipe)
        recipe = result["recipe"]
    return _parse_recipe_json(json.dumps(recipe, ensure_ascii=False))


@trace_call
def recommend_recipes(query: str, recipe_names: list[str]) -> str:
    """Return a short Hebrew recommendation based on query and available recipe names."""
    names = ", ".join(recipe_names) if recipe_names else "אין מתכונים זמינים"
    prompt = f'יש לי מתכונים: {names}. המשתמש מחפש: "{query}". המלץ בעברית קצר.'
    return _generate_text(prompt)


# ── HTML / JSON-LD helpers (unchanged) ────────────────────────────────────────

@trace_call
def _extract_jsonld_recipe(soup) -> Optional[str]:
    """
    Look for a schema.org/Recipe object embedded as JSON-LD in the page.
    Returns it serialised as a JSON string, or None if not found.
    """
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]

        for item in items:
            if isinstance(item, dict) and "@graph" in item:
                items.extend(item["@graph"])
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type", "")
            types_list = item_type if isinstance(item_type, list) else [item_type]
            if any("Recipe" in t for t in types_list):
                logger.info("Found schema.org/Recipe JSON-LD on page")
                return json.dumps(item, ensure_ascii=False)

    return None


@trace_call
async def extract_recipe_from_url(url: str) -> dict:
    """
    Fetch the page at *url*, extract recipe content, then call the configured AI backend.
    Extraction priority:
      1. Social media post description (Instagram / Facebook / YouTube)
      2. schema.org/Recipe JSON-LD (embedded structured data — most reliable)
      3. Visible text from the main content area
    Raises HTTPException 422 if the page cannot be fetched.
    """
    import asyncio

    from bs4 import BeautifulSoup

    from app.social import detect_platform, fetch_social_description

    platform = detect_platform(url)
    if platform:
        # Many social posts (notably Instagram) require a logged-in session, so
        # an anonymous yt-dlp fetch fails or returns nothing. Surface a short,
        # actionable Hebrew message and keep the raw error in the logs.
        social_fallback_detail = (
            f"לא ניתן לייבא אוטומטית מ-{platform}. ייתכן שהפוסט דורש התחברות "
            "או אינו זמין לצפייה ללא חשבון. העתיקו את טקסט המתכון מהפוסט "
            "והדביקו אותו בייבוא מטקסט."
        )
        try:
            description = await asyncio.to_thread(fetch_social_description, url)
        except Exception as exc:
            logger.warning("Social fetch failed for platform=%s: %s", platform, exc)
            raise HTTPException(status_code=422, detail=social_fallback_detail)
        if not description.strip():
            logger.info("Social post description empty for platform=%s", platform)
            raise HTTPException(status_code=422, detail=social_fallback_detail)
        return await asyncio.to_thread(extract_recipe_from_text, description)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="Could not fetch URL. Please use /recipes/from-text instead.",
        )

    soup = BeautifulSoup(html, "html.parser")

    jsonld_text = _extract_jsonld_recipe(soup)
    if jsonld_text:
        return await asyncio.to_thread(extract_recipe_from_text, jsonld_text)

    logger.info("No JSON-LD recipe found, falling back to visible text extraction")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    visible_text = soup.get_text(separator="\n", strip=True)

    og_image_bytes: Optional[bytes] = None
    og_image_tag = soup.find("meta", property="og:image")
    if og_image_tag and og_image_tag.get("content"):
        image_url = og_image_tag["content"]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                img_resp = await client.get(image_url, headers=headers)
                img_resp.raise_for_status()
                og_image_bytes = img_resp.content
        except Exception:
            og_image_bytes = None

    return await asyncio.to_thread(extract_recipe_from_text, visible_text[:8000], og_image_bytes)
