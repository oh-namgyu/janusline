"""Google News RSS collection: fetch, parse, dedupe, period filter.

The only host this module ever contacts is news.google.com — the user query is
URL encoded into the query string and never decides a host, so there is no SSRF
surface. Article links are stored for display; they are never fetched.

Collection is a transaction: everything happens in memory and the caller does a
single atomic write, so a failure at any step leaves brief.json untouched.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from html import unescape
from typing import Any, Dict, List, Optional, Sequence
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import feedparser

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
EDITIONS: Dict[str, Dict[str, str]] = {
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}
MAX_PER_EDITION = 20
MAX_TOTAL = 40
TIMEOUT = 20
USER_AGENT = "janusline/1.0"
ALLOWED_SCHEMES = ("http", "https")
TAG_RE = re.compile(r"<[^>]*>")
PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
WS_RE = re.compile(r"\s+")


class CollectError(Exception):
    """Collection failed. `retryable` marks transient network-side failures."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def feed_url(query: str, lang: str) -> str:
    edition = EDITIONS.get(lang)
    if edition is None:
        raise ValueError(f"unsupported edition: {lang}")
    return f"{GOOGLE_NEWS_RSS}?{urlencode({'q': query, **edition})}"


def clean_text(text: Any) -> str:
    """Whitespace only. Titles keep whatever characters the feed sent — the UI
    renders them with textContent and the export escapes them, so markup in a
    title stays visible as text instead of being silently rewritten."""
    if not isinstance(text, str):
        return ""
    return WS_RE.sub(" ", text).strip()


def strip_html(text: Any) -> str:
    """RSS descriptions carry markup; the UI renders text, so store text."""
    if not isinstance(text, str):
        return ""
    return WS_RE.sub(" ", unescape(TAG_RE.sub(" ", text))).strip()


def normalise_link(link: str) -> str:
    """Same article, different tracking parameters — compare scheme+host+path."""
    parts = urlparse(link)
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def normalise_title(title: str) -> str:
    """Collapse case, punctuation and whitespace so re-syndications collide."""
    return WS_RE.sub(" ", PUNCT_RE.sub(" ", (title or "").lower())).strip()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def entry_published(entry: Any, collected_at: str) -> tuple[str, bool]:
    """RFC822 date, or the collection time flagged as approximate."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return collected_at, True
    try:
        return _iso(datetime(*parsed[:6], tzinfo=timezone.utc)), False
    except (TypeError, ValueError):
        return collected_at, True


def entry_source(entry: Any, link: str) -> str:
    source = entry.get("source")
    title = source.get("title") if isinstance(source, dict) else None
    if isinstance(title, str) and title.strip():
        return title.strip()
    return urlparse(link).netloc or "unknown"


def build_article(entry: Any, collected_at: str) -> Optional[Dict[str, Any]]:
    """One RSS entry as a schema article, or None when it must be dropped."""
    link = entry.get("link")
    if not isinstance(link, str) or not link.strip():
        return None
    link = link.strip()
    if urlparse(link).scheme.lower() not in ALLOWED_SCHEMES:
        return None
    published, approximate = entry_published(entry, collected_at)
    article: Dict[str, Any] = {
        "id": sha1(link.encode("utf-8")).hexdigest(),
        "title": clean_text(entry.get("title")) or link,
        "source": entry_source(entry, link),
        "link": link,
        "published": published,
        "snippet": strip_html(entry.get("summary")),
        "sentiment": None,
        "summary": None,
        "evidence": None,
    }
    if approximate:
        article["date_approx"] = True
    return article


def parse_edition(
    raw: bytes | str, collected_at: str, cutoff: str, limit: int = MAX_PER_EDITION
) -> List[Dict[str, Any]]:
    """Parse one edition feed into at most `limit` in-period articles."""
    feed = feedparser.parse(raw)
    entries = getattr(feed, "entries", []) or []
    # an empty feed is a legitimate "no results"; a response that is not a feed
    # at all (error page, captcha) has neither entries nor a recognised version
    if not entries and (getattr(feed, "bozo", False) or not getattr(feed, "version", "")):
        raise CollectError("unparseable feed response", retryable=True)
    articles: List[Dict[str, Any]] = []
    for entry in entries:
        article = build_article(entry, collected_at)
        if article is None or article["published"] < cutoff:
            continue
        articles.append(article)
        if len(articles) >= limit:
            break
    return articles


def dedupe(articles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Link first, normalised title second — editions re-syndicate each other."""
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for article in articles:
        link_key = normalise_link(article["link"])
        title_key = normalise_title(article["title"])
        if link_key in seen_links or (title_key and title_key in seen_titles):
            continue
        seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(article)
    return unique


class GoogleNewsCollector:
    """Reads the public Google News RSS search feed, one call per edition."""

    def __init__(self, timeout: int = TIMEOUT) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
        except (URLError, OSError) as err:
            raise CollectError(
                f"news feed unreachable ({type(err).__name__})", retryable=True
            ) from err
        if status != 200:
            raise CollectError(f"news feed returned HTTP {status}", retryable=True)
        return raw

    def collect(
        self,
        query: str,
        period_days: int,
        langs: Sequence[str],
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        moment = now or datetime.now(timezone.utc)
        collected_at = _iso(moment)
        cutoff = _iso(moment - timedelta(days=period_days))
        merged: List[Dict[str, Any]] = []
        for lang in langs:
            raw = self.fetch(feed_url(query, lang))
            merged.extend(parse_edition(raw, collected_at, cutoff))
        articles = dedupe(merged)
        articles.sort(key=lambda item: item["published"], reverse=True)
        return articles[:MAX_TOTAL]
