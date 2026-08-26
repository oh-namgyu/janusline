"""Analysis: batch classification, dual synthesis, schema checks, one retry.

Two prompt shapes, both answering in strict JSON. Classification runs in chunks
of BATCH_SIZE articles, synthesis is a single closing call, so one analysis costs
ceil(n / BATCH_SIZE) + 1 provider calls when nothing has to be corrected.

Nothing here touches storage: the caller collects the whole result in memory and
writes once, so a failure at any point leaves brief.json untouched.
"""

from __future__ import annotations

import json
from functools import partial
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

from .prompts import (
    CLASSIFY_BLOCK,
    CLASSIFY_TEMPLATE,
    CORRECTION,
    SYNTHESIS_BLOCK,
    SYNTHESIS_TEMPLATE,
    SYSTEM_CLASSIFY,
    SYSTEM_SYNTHESIS,
)
from .schema import SENTIMENTS

BATCH_SIZE = 25
MAX_SUMMARY = 400
MAX_NARRATIVE = 2000
SIDES = ("positive", "negative")
ATTEMPTS = 2
NO_SUMMARY = "(no summary)"
# the model never writes this: the disclosure is the server's statement, not the
# model's, so it cannot be softened, dropped or rewritten by a reply
CAVEAT = (
    "Machine-generated analysis of headlines and feed summaries only — the full "
    "article texts were never fetched. Sentiments, summaries and scenarios are "
    "automated readings rather than fact checks; open the sources before relying "
    "on them."
)


class AnalysisParseError(Exception):
    """The model never returned a usable document. `raw` holds the last reply."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


# -- prompt building -----------------------------------------------------
def shield(text: Any) -> str:
    """Neutralise the block delimiter so article text cannot close its own block."""
    if not isinstance(text, str):
        return ""
    return text.replace("<", "‹").replace(">", "›")


def article_text(article: Dict[str, Any]) -> str:
    """The exact text shown to the model — and therefore what evidence must quote."""
    return f"{shield(article.get('title'))}\n{shield(article.get('snippet'))}"


def build_classification_prompt(
    subject: str, articles: Sequence[Dict[str, Any]]
) -> Tuple[str, str]:
    blocks = "\n".join(
        CLASSIFY_BLOCK.format(
            id=article["id"],
            title=shield(article.get("title")),
            snippet=shield(article.get("snippet")),
        )
        for article in articles
    )
    return SYSTEM_CLASSIFY, CLASSIFY_TEMPLATE.format(subject=subject, blocks=blocks)


def tally_of(verdicts: Iterable[Dict[str, Any]]) -> str:
    counts = {name: 0 for name in SENTIMENTS}
    for verdict in verdicts:
        sentiment = verdict.get("sentiment")
        if sentiment in counts:
            counts[sentiment] += 1
    return ", ".join(f"{name} {counts[name]}" for name in SENTIMENTS)


def build_synthesis_prompt(
    subject: str,
    articles: Sequence[Dict[str, Any]],
    verdicts: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    blocks = "\n".join(
        SYNTHESIS_BLOCK.format(
            id=article["id"],
            sentiment=verdicts.get(article["id"], {}).get("sentiment", "neutral"),
            title=shield(article.get("title")),
            summary=shield(verdicts.get(article["id"], {}).get("summary")) or NO_SUMMARY,
        )
        for article in articles
    )
    user = SYNTHESIS_TEMPLATE.format(
        subject=subject, tally=tally_of(verdicts.values()), blocks=blocks
    )
    return SYSTEM_SYNTHESIS, user


# -- reply parsing -------------------------------------------------------
def extract_json(text: str) -> str:
    """Drop a markdown fence around the payload when the model adds one."""
    body = (text or "").strip()
    if not body.startswith("```"):
        return body
    body = body[3:]
    head, _, rest = body.partition("\n")
    if head.strip() and head.strip()[:1] not in ("{", "["):
        body = rest
    closing = body.rfind("```")
    if closing != -1:
        body = body[:closing]
    return body.strip()


def decode(raw: str) -> Any:
    try:
        return json.loads(extract_json(raw))
    except json.JSONDecodeError as err:
        raise ValueError(f"response is not valid JSON ({err})") from err


def neutral_verdict() -> Dict[str, Any]:
    """What an article gets when the model skipped it or answered unusably."""
    return {"sentiment": "neutral", "summary": None, "evidence": None}


def _text(value: Any, limit: int) -> Any:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def grounded(evidence: Any, haystack: str) -> Any:
    """Evidence has to be a passage the article really contains, or it is dropped."""
    quote = _text(evidence, MAX_SUMMARY)
    return quote if quote and quote in haystack else None


def _matched_id(entry: Any, haystacks: Dict[str, str]) -> Any:
    """The id this reply element answers for, or None when it answers for none."""
    if not isinstance(entry, dict):
        return None
    article_id = entry.get("id")
    if isinstance(article_id, str) and article_id in haystacks:
        return article_id
    return None


def _verdict(entry: Dict[str, Any], haystack: str) -> Dict[str, Any]:
    """One reply element as a verdict. An unlisted sentiment is not a judgement."""
    if entry.get("sentiment") not in SENTIMENTS:
        return neutral_verdict()
    return {
        "sentiment": entry["sentiment"],
        "summary": _text(entry.get("summary"), MAX_SUMMARY),
        "evidence": grounded(entry.get("evidence"), haystack),
    }


def parse_classification(
    raw: str, articles: Sequence[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Reconcile one reply against the ids that were sent.

    Unknown ids are dropped, ids the model skipped fall back to neutral, and an
    evidence quote that is not in its own article is demoted to null while the
    classification itself is kept. A reply that answers for none of the ids is a
    failed reply, and the caller retries it.
    """
    data = decode(raw)
    if not isinstance(data, list):
        raise ValueError("response must be a JSON array")
    haystacks = {article["id"]: article_text(article) for article in articles}
    found: Dict[str, Dict[str, Any]] = {}
    for entry in data:
        article_id = _matched_id(entry, haystacks)
        if article_id is not None and article_id not in found:
            found[article_id] = _verdict(entry, haystacks[article_id])
    if haystacks and not found:
        raise ValueError("no element matched the article ids that were sent")
    return {key: found.get(key, neutral_verdict()) for key in haystacks}


def _citations(value: Any, known: Sequence[str]) -> List[str]:
    if not isinstance(value, list):
        return []
    cited: List[str] = []
    for item in value:
        if isinstance(item, str) and item in known and item not in cited:
            cited.append(item)
    return cited


def _side(block: Any, name: str, known: Sequence[str], errors: List[str]) -> Any:
    if not isinstance(block, dict):
        errors.append(f"{name} must be an object")
        return None
    entry: Dict[str, Any] = {}
    for field in ("narrative", "if_scenario"):
        text = _text(block.get(field), MAX_NARRATIVE)
        if text is None:
            errors.append(f"{name}.{field} must be a non-empty string")
        entry[field] = text or ""
    entry["citations"] = _citations(block.get("citations"), known)
    if not entry["citations"]:
        # kept, but flagged: the UI shows this side as unsupported
        entry["ungrounded"] = True
    return entry


def parse_synthesis(raw: str, known: Sequence[str]) -> Dict[str, Any]:
    """Validate both readings and attach the server-owned caveat."""
    data = decode(raw)
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    errors: List[str] = []
    synthesis: Dict[str, Any] = {}
    for name in SIDES:
        side = _side(data.get(name), name, known, errors)
        if side is not None:
            synthesis[name] = side
    if errors:
        raise ValueError("; ".join(errors))
    synthesis["caveat"] = CAVEAT
    return synthesis


# -- orchestration -------------------------------------------------------
def ask(llm: Any, system: str, user: str, parse: Callable[[str], Any]) -> Any:
    """One call, then one corrective retry quoting the validation error."""
    prompt = user
    raw = ""
    problem = "no response"
    for _ in range(ATTEMPTS):
        raw = llm.generate(system, prompt)
        try:
            return parse(raw)
        except ValueError as err:
            problem = str(err)
            prompt = f"{user}\n\n{CORRECTION.format(error=problem)}"
    raise AnalysisParseError(problem, raw=raw)


def classify_articles(
    subject: str, articles: Sequence[Dict[str, Any]], llm: Any
) -> Dict[str, Dict[str, Any]]:
    verdicts: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(articles), BATCH_SIZE):
        batch = articles[start : start + BATCH_SIZE]
        system, user = build_classification_prompt(subject, batch)
        parse = partial(parse_classification, articles=batch)
        verdicts.update(ask(llm, system, user, parse))
    return verdicts


def analyse(
    subject: str, articles: Sequence[Dict[str, Any]], llm: Any
) -> Dict[str, Any]:
    """Classify every article, then write both readings. Memory only."""
    verdicts = classify_articles(subject, articles, llm)
    system, user = build_synthesis_prompt(subject, articles, verdicts)
    known = [article["id"] for article in articles]
    synthesis = ask(llm, system, user, partial(parse_synthesis, known=known))
    return {"verdicts": verdicts, "synthesis": synthesis}


def apply_analysis(brief: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Fold a finished analysis into a freshly loaded brief, under the caller's lock."""
    verdicts = result["verdicts"]
    for article in brief.get("articles") or []:
        article.update(verdicts.get(article.get("id")) or neutral_verdict())
    brief["synthesis"] = result["synthesis"]
    brief["status"] = "analyzed"
