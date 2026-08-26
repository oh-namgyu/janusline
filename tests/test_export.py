"""The standalone export: escaping, link safety, footnotes and the route."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app import create_app
from core.export import export_filename, render_export
from core.schema import new_brief
from tests.support import NOW_ISO, make_articles

HOSTILE = "<script>alert('xss')</script> & \"quoted\""


def brief_with(articles, synthesis: Any = None, query: str = "Auric Foundry") -> Dict[str, Any]:
    brief = new_brief("auric-foundry", query, 90, ["ko", "en"])
    brief["articles"] = list(articles)
    brief["synthesis"] = synthesis
    brief["status"] = "analyzed" if synthesis else "collected"
    return brief


def classified(count: int = 3) -> list:
    articles = make_articles(count)
    for article, sentiment in zip(articles, ("positive", "negative", "neutral")):
        article.update(
            sentiment=sentiment,
            summary=f"Summary of {article['title']}.",
            evidence=article["title"] if sentiment != "neutral" else None,
        )
    return articles


def synthesis_for(articles) -> Dict[str, Any]:
    return {
        "positive": {
            "narrative": "The favourable reading.",
            "if_scenario": "IF it holds, the trend continues.",
            "citations": [articles[0]["id"]],
        },
        "negative": {
            "narrative": "The unfavourable reading.",
            "if_scenario": "IF it holds, the trend reverses.",
            "citations": [articles[1]["id"]],
        },
        "caveat": "Machine-generated analysis of headlines only.",
    }


# -- document shape ------------------------------------------------------
def test_document_is_self_contained() -> None:
    articles = classified()
    document = render_export(brief_with(articles, synthesis_for(articles)))
    assert document.startswith("<!doctype html>")
    assert "<style>" in document
    # no scripts and nothing to fetch: the only URLs are the article links
    assert "<script" not in document
    assert "src=" not in document
    assert "<link" not in document
    assert "@import" not in document


def test_header_and_tally_report_the_real_distribution() -> None:
    document = render_export(brief_with(classified()))
    assert "Auric Foundry" in document
    assert "last 90 days" in document
    assert "ko + en" in document
    assert "<b>1</b> positive" in document
    assert "<b>1</b> negative" in document


def test_unclassified_articles_are_counted_separately() -> None:
    document = render_export(brief_with(make_articles(2)))
    assert "<b>2</b> unclassified" in document
    assert "unclassified</span>" in document


def test_each_side_lands_in_its_own_column() -> None:
    articles = classified()
    document = render_export(brief_with(articles))
    positive = '<tr><td><div class="card pos">'
    negative = '<tr><td></td><td class="axis">'
    assert positive in document
    assert negative in document
    # neutral spans the whole width instead of taking a side
    assert '<tr><td colspan="3"><div class="card mid">' in document


def test_missing_evidence_is_marked_rather_than_hidden() -> None:
    articles = classified()
    document = render_export(brief_with(articles))
    assert "no direct quote" in document
    assert "❝ Headline 0" in document


def test_approximate_dates_keep_their_marker() -> None:
    articles = classified(1)
    articles[0]["date_approx"] = True
    document = render_export(brief_with(articles))
    assert "~ " + NOW_ISO[:10] in document


# -- escaping and link safety -------------------------------------------
def test_hostile_strings_are_escaped_everywhere() -> None:
    articles = classified(1)
    articles[0].update(title=HOSTILE, source=HOSTILE, summary=HOSTILE, evidence=HOSTILE)
    synthesis = synthesis_for(classified(2))
    synthesis["positive"]["narrative"] = HOSTILE
    synthesis["caveat"] = HOSTILE
    document = render_export(brief_with(articles, synthesis, query=HOSTILE))
    assert "<script" not in document
    assert "alert('xss')" not in document
    assert "&lt;script&gt;" in document


def test_only_http_links_stay_links() -> None:
    articles = classified(2)
    articles[0]["link"] = "javascript:alert(1)"
    document = render_export(brief_with(articles))
    assert "javascript:alert(1)" not in document
    assert 'rel="noopener noreferrer" target="_blank"' in document


# -- synthesis and footnotes --------------------------------------------
def test_readings_carry_numbered_footnotes() -> None:
    articles = classified()
    document = render_export(brief_with(articles, synthesis_for(articles)))
    assert "The favourable reading." in document
    assert "IF this narrative holds" in document
    assert '<a href="#ref1">[1]</a>' in document
    assert '<li id="ref2">' in document
    assert "Machine-generated analysis" in document


def test_uncited_reading_is_labelled_not_presented_as_fact() -> None:
    articles = classified()
    synthesis = synthesis_for(articles)
    synthesis["positive"] = {**synthesis["positive"], "citations": [], "ungrounded": True}
    document = render_export(brief_with(articles, synthesis))
    assert "insufficient citations" in document


def test_unanalysed_brief_says_so_instead_of_faking_a_reading() -> None:
    document = render_export(brief_with(make_articles(1)))
    assert "has not been analysed yet" in document
    assert "References" not in document


def test_empty_brief_exports_without_a_table() -> None:
    document = render_export(brief_with([]))
    assert "No articles were collected" in document
    assert "<table>" not in document


# -- route ---------------------------------------------------------------
@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))
    application = create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def test_export_route_downloads_a_named_file(client) -> None:
    res = client.post("/api/briefs", json={"query": "Auric Foundry"})
    slug = json.loads(res.data)["data"]["slug"]
    got = client.get(f"/api/briefs/{slug}/export")
    assert got.status_code == 200
    assert got.mimetype == "text/html"
    assert got.headers["Content-Disposition"] == f'attachment; filename="{slug}-janusline.html"'
    assert b"Auric Foundry" in got.data


def test_export_route_rejects_unknown_and_malformed_slugs(client) -> None:
    assert client.get("/api/briefs/missing-brief/export").status_code == 404
    assert client.get("/api/briefs/Not_A_Slug/export").status_code == 400


def test_filename_is_derived_from_the_slug() -> None:
    assert export_filename("auric-foundry") == "auric-foundry-janusline.html"
