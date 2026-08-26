"""Shared collection helpers: saved feeds, fixed clock, stub collectors."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from core.collect import MAX_PER_EDITION, CollectError, GoogleNewsCollector, parse_edition

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


def body(res) -> dict:
    return json.loads(res.data)


def make_brief(client, query: str = "samsung electronics", **extra) -> str:
    res = client.post("/api/briefs", json={"query": query, **extra})
    assert res.status_code == 201
    return body(res)["data"]["slug"]
