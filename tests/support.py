"""Shared test helpers: saved feeds, fixed clock, stub collectors, stub analysts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from core.collect import MAX_PER_EDITION, CollectError, GoogleNewsCollector, parse_edition
from core.fake_llm import FakeText
from core.llm import LLMError, LLMNotConfigured

FIXTURES = Path(__file__).parent / "fixtures"
# the saved feeds carry fixed dates, so the clock is fixed too
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-08-20T12:00:00+00:00"


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.xml").read_bytes()


def cutoff(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def parse(name: str, days: int = 90, limit: int = MAX_PER_EDITION) -> List[dict]:
    return parse_edition(fixture(name), NOW_ISO, cutoff(days), limit)


def big_feed(prefix: str, count: int) -> bytes:
    items = "".join(
        "<item>"
        f"<title>{prefix} headline {index}</title>"
        f"<link>https://news.example.com/{prefix}/{index}</link>"
        "<pubDate>Tue, 18 Aug 2026 09:00:00 GMT</pubDate>"
        f"<description>{prefix} body {index}</description>"
        "</item>"
        for index in range(count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>big</title>{items}</channel></rss>"
    ).encode("utf-8")


class StubCollector(GoogleNewsCollector):
    """The real pipeline over the saved fixtures, one per edition."""

    def fetch(self, url: str) -> bytes:
        return fixture("google_news_ko" if "hl=ko" in url else "google_news_en")


class BrokenCollector(GoogleNewsCollector):
    def fetch(self, url: str) -> bytes:
        raise CollectError("news feed unreachable (URLError)", retryable=True)


class BigCollector(GoogleNewsCollector):
    def fetch(self, url: str) -> bytes:
        return big_feed("ko" if "hl=ko" in url else "en", 25)


# -- analysts ---------------------------------------------------------------
class ScriptedLLM:
    """Replies from a fixed queue; records every (system, user) pair it was given."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: List[tuple] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        assert self.replies, "the analyst was called more often than scripted"
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


class CountingLLM:
    """The offline fake, plus a record of every call made through it."""

    def __init__(self, inner: Any = None) -> None:
        self.inner = inner or FakeText()
        self.calls: List[tuple] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.inner.generate(system, user)


class BrokenLLM:
    def __init__(self, retryable: bool = True) -> None:
        self.retryable = retryable

    def generate(self, system: str, user: str) -> str:
        raise LLMError("RateLimitError: slow down", retryable=self.retryable)


class UnconfiguredLLM:
    def generate(self, system: str, user: str) -> str:
        raise LLMNotConfigured("ANTHROPIC_API_KEY is not set")


class GarbageLLM:
    """Never returns JSON, so both attempts fail and the parse error surfaces."""

    def __init__(self, reply: str = "sorry, I cannot do that") -> None:
        self.reply = reply
        self.calls: List[tuple] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


# -- analysis fixtures ------------------------------------------------------
def make_articles(count: int, prefix: str = "Headline") -> List[Dict[str, Any]]:
    return [
        {
            "id": f"id{index}",
            "title": f"{prefix} {index}",
            "source": "Example News",
            "link": f"https://news.example.com/{index}",
            "published": NOW_ISO,
            "snippet": f"Body text for {prefix.lower()} {index}.",
            "sentiment": None,
            "summary": None,
            "evidence": None,
        }
        for index in range(count)
    ]


def classification_reply(
    articles: Sequence[Dict[str, Any]], sentiment: str = "positive", grounded: bool = True
) -> List[Dict[str, Any]]:
    return [
        {
            "id": article["id"],
            "sentiment": sentiment,
            "summary": f"Summary of {article['title']}.",
            "evidence": article["title"] if grounded else "a passage nobody wrote",
        }
        for article in articles
    ]


def synthesis_reply(
    positive: Sequence[str] = (), negative: Sequence[str] = (), caveat: str = "model caveat"
) -> Dict[str, Any]:
    return {
        "positive": {
            "narrative": "The favourable reading.",
            "if_scenario": "IF it holds, the trend continues.",
            "citations": list(positive),
        },
        "negative": {
            "narrative": "The unfavourable reading.",
            "if_scenario": "IF it holds, the trend reverses.",
            "citations": list(negative),
        },
        "caveat": caveat,
    }


def body(res) -> dict:
    return json.loads(res.data)


def make_brief(client, query: str = "samsung electronics", **extra) -> str:
    res = client.post("/api/briefs", json={"query": query, **extra})
    assert res.status_code == 201
    return body(res)["data"]["slug"]
