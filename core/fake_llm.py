"""Deterministic offline analyst for demos and browser tests (JANUSLINE_FAKE=1).

It reads the real prompts, so it exercises the real reconciliation path: two of
its answers are wrong on purpose — one evidence quote is a paraphrase rather than
a substring, and the synthesis cites one id that was never sent — so the grounding
demotion and the citation drop are visible in every demo run.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from .prompts import SYSTEM_CLASSIFY

CLASSIFY_RE = re.compile(
    r'<article id="([^"]+)">\s*<title>(.*?)</title>\s*<snippet>(.*?)</snippet>',
    re.DOTALL,
)
SYNTHESIS_RE = re.compile(r'<article id="([^"]+)" sentiment="([a-z]+)"')
SUBJECT_RE = re.compile(r"^SUBJECT: (.*)$", re.MULTILINE)
POSITIVE_HINTS = ("surge", "record", "win", "rise", "raise", "증가", "급등", "투자")
NEGATIVE_HINTS = ("lawsuit", "drop", "fire", "halt", "probe", "antitrust", "소송")
# the one article whose evidence is deliberately not a substring
UNGROUNDED_HINT = "fire"
UNGROUNDED_EVIDENCE = "the report describes a production stoppage"
UNKNOWN_CITATION = "0" * 40
MAX_CITATIONS = 3


def subject_of(user: str) -> str:
    match = SUBJECT_RE.search(user)
    return match.group(1).strip() if match else "the subject"


def sentiment_of(title: str) -> str:
    lowered = title.lower()
    if any(hint in lowered for hint in POSITIVE_HINTS):
        return "positive"
    if any(hint in lowered for hint in NEGATIVE_HINTS):
        return "negative"
    return "neutral"


def _classification(article_id: str, title: str) -> Dict[str, Any]:
    sentiment = sentiment_of(title)
    grounded = UNGROUNDED_HINT not in title.lower()
    return {
        "id": article_id,
        "sentiment": sentiment,
        "summary": f"{title.strip()} ({sentiment} for the subject).",
        "evidence": title.strip() if grounded else UNGROUNDED_EVIDENCE,
    }


def classify(user: str) -> List[Dict[str, Any]]:
    return [
        _classification(article_id, title)
        for article_id, title, _snippet in CLASSIFY_RE.findall(user)
    ]


def _side(subject: str, label: str, ids: List[str], extra: Tuple[str, ...] = ()) -> Dict:
    return {
        "narrative": (
            f"Read at its most {label}, the coverage of {subject} points one way: "
            f"{len(ids)} of the collected articles line up behind that reading."
        ),
        "if_scenario": (
            f"IF the {label} reading holds, the following months for {subject} would "
            "extend the same trend rather than break it."
        ),
        "citations": ids[:MAX_CITATIONS] + list(extra),
    }


def synthesise(user: str) -> Dict[str, Any]:
    subject = subject_of(user)
    found = SYNTHESIS_RE.findall(user)
    positive = [article_id for article_id, sentiment in found if sentiment == "positive"]
    negative = [article_id for article_id, sentiment in found if sentiment == "negative"]
    return {
        "positive": _side(subject, "favourable", positive, (UNKNOWN_CITATION,)),
        "negative": _side(subject, "unfavourable", negative),
        "caveat": "a caveat the server is expected to overwrite",
    }


class FakeText:
    """Same interface as core.llm.AnthropicText, without the provider."""

    def generate(self, system: str, user: str) -> str:
        payload: Any = classify(user) if system == SYSTEM_CLASSIFY else synthesise(user)
        return json.dumps(payload, ensure_ascii=False)
