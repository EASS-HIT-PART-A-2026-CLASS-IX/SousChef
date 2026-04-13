"""
Gemini-powered recipe extraction helpers.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from fastapi import HTTPException

logger = logging.getLogger(__name__)

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

Return ONLY the JSON object, no explanation, no markdown fences.

Content:
{content}
"""


def _get_client() -> genai.Client:
    """Return a configured Gemini Client, raising on missing key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please create a .env file with your Gemini API key."
        )
    return genai.Client(api_key=api_key)


def _parse_gemini_response(raw: str) -> dict:
    """
    Strip optional markdown code fences and parse the JSON returned by Gemini.
    Raises HTTPException 422 if the response is not valid JSON or has no name.
    """
    logger.info("Raw Gemini response: %s", raw)

    text = raw.strip()
    # Remove optional ```json ... ``` fences that some models add
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Gemini response could not be parsed as JSON: %s", text[:500])
        raise HTTPException(
            status_code=422,
            detail="AI could not extract a recipe from this content. Please try with clearer content.",
        )

    # Some models wrap the result under a "recipe" key — unwrap it
    if isinstance(data, dict) and "recipe" in data and isinstance(data["recipe"], dict):
        data = data["recipe"]

    # Validate that we got a usable recipe (name is the only required field)
    if not isinstance(data, dict) or not data.get("name"):
        logger.warning("Gemini returned a dict with no name field: %s", data)
        raise HTTPException(
            status_code=422,
            detail="AI could not extract a recipe from this content. Please try with clearer content.",
        )

    return data


_MIME_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),   # RIFF....WEBP
]


def _detect_mime_type(data: bytes) -> Optional[str]:
    """Return the MIME type of *data* based on its magic bytes, or None."""
    for signature, mime in _MIME_SIGNATURES:
        if data[:len(signature)] == signature:
            return mime
    # WebP has 4 bytes of size between RIFF and WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def extract_recipe_from_text(text: str, image_bytes: Optional[bytes] = None) -> dict:
    """
    Call Gemini with the supplied text (and optional raw image bytes).
    Returns the parsed recipe dict.
    """
    client = _get_client()
    prompt = EXTRACTION_PROMPT.format(content=text)

    parts: list = [prompt]

    if image_bytes:
        mime_type = _detect_mime_type(image_bytes)
        if mime_type is None:
            logger.warning("Uploaded file does not appear to be a supported image — skipping")
        else:
            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                )
            )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=parts,
        )
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
    return _parse_gemini_response(response.text)


def _extract_jsonld_recipe(soup) -> Optional[str]:
    """
    Look for a schema.org/Recipe object embedded as JSON-LD in the page.
    Returns it serialised as a JSON string, or None if not found.
    Most major recipe sites (AllRecipes, BBC Good Food, NYT Cooking, etc.)
    embed this, making it far more reliable than scraping visible text.
    """
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        # The blob may be a single object or a list
        items = data if isinstance(data, list) else [data]

        for item in items:
            # Handle @graph arrays (used by some sites)
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


async def extract_recipe_from_url(url: str) -> dict:
    """
    Fetch the page at *url*, extract recipe content, then call Gemini.
    Extraction priority:
      1. Social media post description (Instagram / Facebook / YouTube)
      2. schema.org/Recipe JSON-LD (embedded structured data — most reliable)
      3. Visible text from the main content area
    Raises HTTPException 422 if the page cannot be fetched.
    """
    import asyncio

    import httpx
    from bs4 import BeautifulSoup

    from app.social import detect_platform, fetch_social_description

    # ── Strategy 1: social media platforms ───────────────────────────────────
    if detect_platform(url):
        try:
            loop = asyncio.get_event_loop()
            description = await loop.run_in_executor(None, fetch_social_description, url)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Could not fetch social media post: {exc}",
            )
        if not description.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    "The post description is empty. "
                    "Please paste the recipe text using /recipes/from-text instead."
                ),
            )
        return extract_recipe_from_text(description)

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

    # ── Strategy 2: schema.org/Recipe JSON-LD ────────────────────────────────
    jsonld_text = _extract_jsonld_recipe(soup)
    if jsonld_text:
        return extract_recipe_from_text(jsonld_text)

    # ── Strategy 3: visible text fallback ────────────────────────────────────
    logger.info("No JSON-LD recipe found, falling back to visible text extraction")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    visible_text = soup.get_text(separator="\n", strip=True)

    # Try to grab an og:image for multimodal context
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

    return extract_recipe_from_text(visible_text[:8000], og_image_bytes)
