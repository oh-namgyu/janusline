"""brief.json v1: the document shape, its validation and its errors.

Kept apart from storage.py so the contract can be read (and tested) without
any filesystem concerns.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List

SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MAX_QUERY = 200
VALID_PERIOD_DAYS = (30, 90, 365)
VALID_LANG = ("ko", "en")
DEFAULT_PERIOD_DAYS = 90
VALID_STATUS = ("empty", "collected", "analyzed")
SENTIMENTS = ("positive", "negative", "neutral")
# transient load-time markers; they describe the read, not the stored brief
VOLATILE_FIELDS = ("recovered", "data_loss", "read_only")
SUMMARY_FIELDS = (
    "schema",
    "slug",
    "query",
    "period_days",
    "lang",
    "status",
    "created",
    "updated",
)


class StorageError(Exception):
    """Base error for storage operations."""


class BriefNotFound(StorageError):
    """Requested brief does not exist."""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:64].strip("-")
    return slug or "brief"


def validate_slug(slug: Any) -> str:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("invalid slug")
    return slug


def require_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} is too long (max {limit})")
    return value


def normalise_period_days(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_PERIOD_DAYS
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or value not in VALID_PERIOD_DAYS:
        raise ValueError("period_days must be 30, 90 or 365")
    return int(value)


def normalise_lang(lang: Any) -> List[str]:
    """Accept a list or a comma string; keep the canonical ko, en order."""
    if lang is None or lang == "":
        return list(VALID_LANG)
    if isinstance(lang, str):
        lang = [part.strip() for part in lang.split(",")]
    if not isinstance(lang, list) or not lang:
        raise ValueError("lang must be a non-empty list")
    chosen = [code for code in VALID_LANG if code in lang]
    unknown = [code for code in lang if code not in VALID_LANG]
    if unknown or not chosen:
        raise ValueError("lang must be any of: ko, en")
    return chosen


def new_brief(
    slug: str, query: str, period_days: int, lang: List[str]
) -> Dict[str, Any]:
    """A brief.json v1 document in its initial, never-collected state."""
    now = utcnow()
    return {
        "schema": SCHEMA_VERSION,
        "slug": slug,
        "query": query,
        "period_days": period_days,
        "lang": list(lang),
        "status": "empty",
        "created": now,
        "updated": now,
        "articles": [],
        "synthesis": None,
    }


def summarise(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Card-sized view: no articles, but the counts a ratio bar needs."""
    summary = {key: brief.get(key) for key in SUMMARY_FIELDS}
    articles = brief.get("articles") or []
    summary["article_count"] = len(articles)
    counts = {name: 0 for name in SENTIMENTS}
    for article in articles:
        sentiment = article.get("sentiment") if isinstance(article, dict) else None
        if sentiment in counts:
            counts[sentiment] += 1
    summary["sentiment_counts"] = counts
    for field in VOLATILE_FIELDS:
        if brief.get(field):
            summary[field] = True
    return summary


def check_schema(brief: Any) -> Dict[str, Any]:
    """Version hook: a brief written by a newer release is read-only, not junk."""
    if not isinstance(brief, dict):
        raise StorageError("brief is not an object")
    version = brief.get("schema")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        brief["read_only"] = True
    return brief
