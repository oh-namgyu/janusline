#!/usr/bin/env python3
"""Check the external contracts janusline depends on, before anyone relies on them.

1. Google News RSS answers 200 and parses into entries (no key needed).
2. If ANTHROPIC_API_KEY is set, one minimal model call round trips.

Exit code 0 when every enabled check passes, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import DEFAULT_MODEL  # noqa: E402  (needs the path above)

RSS_PROBE = (
    "https://news.google.com/rss/search"
    "?q=test&hl=en-US&gl=US&ceid=US:en"
)
USER_AGENT = "janusline-preflight/1.0"
TIMEOUT = 15


def check_rss() -> Tuple[bool, str]:
    try:
        request = Request(RSS_PROBE, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=TIMEOUT) as response:
            status = getattr(response, "status", 200)
            raw = response.read()
    except (URLError, OSError) as err:
        return False, f"rss: unreachable ({type(err).__name__}: {err})"
    if status != 200:
        return False, f"rss: HTTP {status}"
    try:
        import feedparser
    except ImportError:
        return False, "rss: feedparser is not installed"
    feed = feedparser.parse(raw)
    entries = len(feed.entries)
    if feed.bozo and not entries:
        return False, f"rss: unparseable ({feed.bozo_exception})"
    return True, f"rss: HTTP 200, {entries} entries, {len(raw)} bytes"


def check_model() -> Tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return True, "model: skipped: no key"
    try:
        import anthropic
    except ImportError:
        return False, "model: the anthropic package is not installed"
    model = os.environ.get("JANUSLINE_MODEL") or DEFAULT_MODEL
    try:
        message = anthropic.Anthropic(api_key=key).messages.create(
            model=model,
            max_tokens=16,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": "reply with the single word ok"}],
        )
    except Exception as err:  # any provider failure fails the check
        return False, f"model: {type(err).__name__}: {err}"
    blocks = [b for b in (message.content or []) if getattr(b, "type", "") == "text"]
    if not blocks:
        return False, f"model: {model} returned no text"
    return True, f"model: {model} ok"


def main() -> int:
    results = [check_rss(), check_model()]
    for passed, detail in results:
        print(f"[{'ok' if passed else 'FAIL'}] {detail}")
    failed = [detail for passed, detail in results if not passed]
    print("preflight:", "pass" if not failed else f"fail ({len(failed)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
