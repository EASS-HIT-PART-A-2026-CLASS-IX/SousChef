"""
Social media description extractor.

Uses yt-dlp to fetch post/reel/video descriptions from public Instagram,
Facebook, and YouTube URLs.  All three platforms share the same extractor —
adding a new platform only requires a new entry in _PLATFORM_PATTERNS.
"""
from __future__ import annotations

import re
from typing import Optional

from app.observability import get_logger, trace_call

logger = get_logger(__name__)

_PLATFORM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("instagram", re.compile(r"instagram\.com/(p|reel|tv)/")),
    ("facebook",  re.compile(r"(facebook\.com|fb\.watch)")),
    ("youtube",   re.compile(r"(youtube\.com/watch|youtu\.be/)")),
]


@trace_call
def detect_platform(url: str) -> Optional[str]:
    """Return the social platform name for *url*, or None if not recognised."""
    for platform, pattern in _PLATFORM_PATTERNS:
        if pattern.search(url):
            logger.info("Detected social platform '%s' for URL", platform)
            return platform
    logger.info("No supported social platform detected for URL")
    return None


@trace_call
def fetch_social_description(url: str) -> str:
    """
    Fetch the description/caption for a public social media post via yt-dlp.

    Returns an empty string if the description is missing or unavailable.
    Raises RuntimeError if yt-dlp is not installed or extraction fails.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        ) from exc

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    description = info.get("description") or ""
    logger.info("Fetched social description len=%s", len(description))
    return description
