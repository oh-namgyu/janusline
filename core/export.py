"""Standalone HTML export: one self-contained briefing file.

No scripts and no external references — the stylesheet is inline and the only
URLs in the document are the article links themselves, which are not fetched by
the page. So the file opens from `file://`, prints, and survives being forwarded
as an attachment.

Every dynamic string goes through html.escape, and every article link has its
scheme re-checked here rather than trusted from the stored brief.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .schema import SENTIMENTS, utcnow

ALLOWED_SCHEMES = ("http", "https")
LABELS = {
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    None: "unclassified",
}
SIDE_TITLES = (("positive", "Favourable reading"), ("negative", "Unfavourable reading"))
UNGROUNDED = "insufficient citations"
NO_QUOTE = "no direct quote"
FOOT = (
    "janusline is a research aid, not a fact checker. Sentiment, summaries and "
    "scenarios are machine generated from headlines — always open the source."
)

CSS = """:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 34px 20px; background: #ffffff; color: #16181d;
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; }
h1 { margin: 0 0 4px; font: 700 28px/1.2 Georgia, "Times New Roman", serif; }
h2 { margin: 30px 0 12px; font: 600 13px/1.2 system-ui, sans-serif;
  letter-spacing: 0.1em; text-transform: uppercase; color: #5b6472;
  border-bottom: 1px solid #e2e5ea; padding-bottom: 7px; }
h3 { margin: 0 0 9px; font: 600 16px/1.3 Georgia, serif; }
p { margin: 0 0 10px; }
.meta { display: flex; flex-wrap: wrap; gap: 7px; margin: 10px 0 4px; }
.chip { padding: 3px 10px; border: 1px solid #d9dde3; border-radius: 999px;
  font-size: 12px; color: #4b5563; }
.tally { margin: 12px 0 0; font-size: 13px; color: #4b5563; }
.tally b { font-weight: 600; }
.caveat { margin: 18px 0 0; padding: 12px 14px; border-left: 4px solid #b45309;
  background: #fdf6ec; font-size: 13px; color: #4b3a1c; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
col.side { width: 41%; } col.axis { width: 18%; }
th { padding: 7px 10px; font: 600 11px/1.2 system-ui, sans-serif;
  letter-spacing: 0.1em; text-transform: uppercase; color: #5b6472; }
th.pos { text-align: left; color: #0c6f63; }
th.neg { text-align: right; color: #b3421a; }
td { padding: 7px 6px; vertical-align: top; }
td.axis { text-align: center; font: 12px/1.4 ui-monospace, Menlo, monospace;
  color: #6b7280; white-space: nowrap; padding-top: 14px; }
tr { border-top: 1px solid #eceef2; }
.card { padding: 11px 13px; border: 1px solid #e2e5ea; border-radius: 7px;
  background: #fbfcfd; }
.card.pos { border-left: 3px solid #0d9488; }
.card.neg { border-right: 3px solid #ea580c; }
.card.mid { border-left: 3px solid #94a3b8; max-width: 620px; margin: 0 auto; }
.tag { display: inline-block; margin-bottom: 6px; padding: 2px 6px;
  border: 1px solid #cbd2da; border-radius: 3px; font: 600 9.5px/1.4 system-ui, sans-serif;
  letter-spacing: 0.14em; text-transform: uppercase; color: #64748b; }
.tag.pos { border-color: #5eccc0; color: #0c6f63; }
.tag.neg { border-color: #f0a882; color: #b3421a; }
.title { margin: 0 0 4px; font: 600 15px/1.35 Georgia, serif; word-wrap: break-word; }
.src { font-size: 12px; color: #6b7280; }
.sum { margin: 7px 0 0; font-size: 13.5px; color: #374151; }
.quote { margin: 8px 0 0; padding: 2px 0 2px 9px; border-left: 2px solid #cbd2da;
  font: italic 12.5px/1.5 Georgia, serif; color: #4b5563; }
.noquote { margin: 8px 0 0; font-size: 12px; color: #8b93a1; }
a { color: #0f766e; }
.readings { display: flex; flex-wrap: wrap; gap: 18px; }
.reading { flex: 1 1 340px; padding: 15px 17px; border: 1px solid #e2e5ea;
  border-radius: 7px; }
.reading.pos { border-top: 3px solid #0d9488; }
.reading.neg { border-top: 3px solid #ea580c; }
.if { margin: 12px 0 0; padding: 11px 13px; background: #f6f8fa;
  border-left: 2px solid #cbd2da; border-radius: 0 7px 7px 0; }
.if-label { display: block; margin-bottom: 5px; font-size: 10.5px;
  letter-spacing: 0.12em; text-transform: uppercase; color: #6b7280; }
.warn { display: inline-block; margin-left: 8px; padding: 2px 8px;
  border: 1px solid #b45309; border-radius: 999px; font-size: 11px; color: #8a5a12; }
sup a { text-decoration: none; }
ol.refs { margin: 0; padding-left: 22px; font-size: 13px; color: #4b5563; }
ol.refs li { margin-bottom: 7px; word-wrap: break-word; }
.foot { margin-top: 30px; padding-top: 14px; border-top: 1px solid #e2e5ea;
  font-size: 12px; color: #8b93a1; }
@media print { body { padding: 0; } tr, .reading { break-inside: avoid; } }
@media (max-width: 720px) {
  col.side, col.axis { width: auto; }
  td, th { display: block; width: 100%; }
  td.axis { text-align: left; padding: 12px 6px 2px; }
  .card.neg { border-left: 3px solid #ea580c; border-right: 1px solid #e2e5ea; }
}"""


def esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def safe_href(link: Any) -> Optional[str]:
    """A link is only a link if it is still http(s) at export time."""
    if not isinstance(link, str) or not link.strip():
        return None
    return link.strip() if urlparse(link).scheme.lower() in ALLOWED_SCHEMES else None


def anchor(text: Any, link: Any) -> str:
    href = safe_href(link)
    body = esc(text)
    if href is None:
        return body
    return f'<a href="{esc(href)}" rel="noopener noreferrer" target="_blank">{body}</a>'


def polarity_of(article: Dict[str, Any]) -> str:
    sentiment = article.get("sentiment")
    return sentiment if sentiment in SENTIMENTS else "unclassified"


def _class(polarity: str) -> str:
    return {"positive": "pos", "negative": "neg"}.get(polarity, "mid")


def _date(article: Dict[str, Any]) -> str:
    stamp = str(article.get("published") or "")[:10]
    return ("~ " + stamp) if article.get("date_approx") else stamp


def _grounding(article: Dict[str, Any]) -> str:
    evidence = article.get("evidence")
    if not evidence:
        return f'<p class="noquote">◇ {esc(NO_QUOTE)}</p>'
    return f'<p class="quote">❝ {esc(evidence)}</p>'


def _card(article: Dict[str, Any], polarity: str) -> str:
    kind = _class(polarity)
    tag = LABELS.get(article.get("sentiment"), "unclassified")
    summary = article.get("summary")
    parts = [
        f'<span class="tag {kind}">{esc(tag)}</span>',
        f'<p class="title">{anchor(article.get("title") or article.get("link"), article.get("link"))}</p>',
        f'<p class="src">{esc(article.get("source") or "unknown")} · {esc(_date(article))}</p>',
    ]
    if summary:
        parts.append(f'<p class="sum">{esc(summary)}</p>')
    parts.append(_grounding(article))
    return f'<div class="card {kind}">{"".join(parts)}</div>'


def _row(article: Dict[str, Any]) -> str:
    """One article as a table row: a side, or the whole width when it has none."""
    polarity = polarity_of(article)
    axis = f'<td class="axis">{esc(_date(article))}</td>'
    if polarity == "positive":
        return f"<tr><td>{_card(article, polarity)}</td>{axis}<td></td></tr>"
    if polarity == "negative":
        return f"<tr><td></td>{axis}<td>{_card(article, polarity)}</td></tr>"
    return f'<tr><td colspan="3">{_card(article, polarity)}</td></tr>'


def _timeline(articles: Sequence[Dict[str, Any]]) -> str:
    if not articles:
        return "<p>No articles were collected for this brief.</p>"
    head = (
        '<colgroup><col class="side"><col class="axis"><col class="side"></colgroup>'
        '<tr><th class="pos">Favourable</th><th></th><th class="neg">Unfavourable</th></tr>'
    )
    return f"<table>{head}{''.join(_row(article) for article in articles)}</table>"


# -- synthesis and its footnotes -----------------------------------------
def _reference_order(brief: Dict[str, Any]) -> Tuple[List[str], Dict[str, int]]:
    """Cited articles, numbered once in the order the two readings mention them."""
    synthesis = brief.get("synthesis") or {}
    order: List[str] = []
    for name, _title in SIDE_TITLES:
        block = synthesis.get(name) or {}
        for article_id in block.get("citations") or []:
            if article_id not in order:
                order.append(article_id)
    return order, {article_id: n for n, article_id in enumerate(order, start=1)}


def _footnotes(ids: Sequence[str], numbers: Dict[str, int]) -> str:
    return "".join(
        f'<sup class="cite"><a href="#ref{numbers[article_id]}">'
        f"[{numbers[article_id]}]</a></sup>"
        for article_id in ids or []
        if article_id in numbers
    )


def _reading(name: str, title: str, block: Any, numbers: Dict[str, int]) -> str:
    kind = _class(name)
    if not isinstance(block, dict):
        return f'<div class="reading {kind}"><h3>{esc(title)}</h3><p>Not analysed yet.</p></div>'
    warn = f'<span class="warn">{esc(UNGROUNDED)}</span>' if block.get("ungrounded") else ""
    notes = _footnotes(block.get("citations"), numbers)
    return (
        f'<div class="reading {kind}"><h3>{esc(title)}{warn}</h3>'
        f'<p>{esc(block.get("narrative"))}{notes}</p>'
        f'<div class="if"><span class="if-label">IF this narrative holds →</span>'
        f'<p>{esc(block.get("if_scenario"))}</p></div></div>'
    )


def _references(brief: Dict[str, Any], order: Sequence[str]) -> str:
    by_id = {article.get("id"): article for article in brief.get("articles") or []}
    items = []
    for number, article_id in enumerate(order, start=1):
        article = by_id.get(article_id) or {}
        title = anchor(article.get("title") or article_id, article.get("link"))
        source = esc(article.get("source") or "unknown")
        items.append(f'<li id="ref{number}">{title} — {source}, {esc(_date(article))}</li>')
    if not items:
        return ""
    return f'<h2>References</h2><ol class="refs">{"".join(items)}</ol>'


def _synthesis(brief: Dict[str, Any]) -> str:
    synthesis = brief.get("synthesis")
    if not isinstance(synthesis, dict):
        return "<h2>Both readings</h2><p>This brief has not been analysed yet.</p>"
    order, numbers = _reference_order(brief)
    readings = "".join(
        _reading(name, title, synthesis.get(name), numbers) for name, title in SIDE_TITLES
    )
    return (
        f'<h2>Both readings</h2><div class="readings">{readings}</div>'
        f'<p class="caveat">{esc(synthesis.get("caveat"))}</p>'
        f"{_references(brief, order)}"
    )


# -- document ------------------------------------------------------------
def _tally(articles: Sequence[Dict[str, Any]]) -> str:
    counts = {name: 0 for name in SENTIMENTS}
    for article in articles:
        if article.get("sentiment") in counts:
            counts[article["sentiment"]] += 1
    parts = " · ".join(f"<b>{counts[name]}</b> {esc(name)}" for name in SENTIMENTS)
    unclassified = len(articles) - sum(counts.values())
    tail = f" · <b>{unclassified}</b> unclassified" if unclassified else ""
    return f'<p class="tally">{parts}{tail}</p>'


def _header(brief: Dict[str, Any], generated: str) -> str:
    articles = brief.get("articles") or []
    chips = [
        ("articles", len(articles)),
        ("period", f"last {brief.get('period_days')} days"),
        ("editions", " + ".join(brief.get("lang") or [])),
        ("status", brief.get("status")),
        ("exported", generated),
    ]
    meta = "".join(
        f'<span class="chip">{esc(label)}: {esc(value)}</span>'
        for label, value in chips
        if str(value or "").strip()
    )
    return (
        f"<h1>{esc(brief.get('query') or brief.get('slug'))}</h1>"
        f'<div class="meta">{meta}</div>{_tally(articles)}'
    )


def render_export(brief: Dict[str, Any]) -> str:
    """One HTML document for this brief: no scripts, no external references."""
    generated = utcnow()
    articles = brief.get("articles") or []
    body = "".join(
        [
            _header(brief, generated),
            "<h2>Timeline</h2>",
            _timeline(articles),
            _synthesis(brief),
            f'<p class="foot">{esc(FOOT)}<br>Exported from janusline on {esc(generated)}.</p>',
        ]
    )
    title = esc(brief.get("query") or brief.get("slug") or "brief")
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title} — janusline</title>\n<style>\n{CSS}\n</style>\n</head>\n"
        f'<body>\n<div class="wrap">{body}</div>\n</body>\n</html>\n'
    )


def export_filename(slug: str) -> str:
    return f"{slug}-janusline.html"
