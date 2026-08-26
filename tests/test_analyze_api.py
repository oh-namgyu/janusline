from pathlib import Path

import pytest
from support import (
    BrokenLLM,
    CountingLLM,
    GarbageLLM,
    StubCollector,
    UnconfiguredLLM,
    body,
    make_brief,
)

from app import create_app
from core.analyze import CAVEAT
from core.collect import GoogleNewsCollector
from core.fake_llm import FakeText
from core.llm import AnthropicText, LLMError
from core.prompts import SYSTEM_CLASSIFY

EMPTY_FEED = (
    '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
    "<title>nothing found</title></channel></rss>"
).encode("utf-8")


class EmptyCollector(GoogleNewsCollector):
    def fetch(self, url: str) -> bytes:
        return EMPTY_FEED


@pytest.fixture()
def app_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))

    def build(llm, collector=None):
        application = create_app(collector=collector or StubCollector(), llm=llm)
        application.config.update(TESTING=True)
        return application

    return build


def collected(app) -> tuple:
    client = app.test_client()
    slug = make_brief(client)
    assert client.post(f"/api/briefs/{slug}/collect").status_code == 200
    return client, slug, app.config["STORAGE"]


# --- happy path ------------------------------------------------------------


def test_analyze_classifies_every_article_and_writes_both_readings(app_factory) -> None:
    app = app_factory(FakeText())
    client, slug, _store = collected(app)

    res = client.post(f"/api/briefs/{slug}/analyze")
    assert res.status_code == 200
    brief = body(res)["data"]
    assert brief["status"] == "analyzed"
    assert len(brief["articles"]) == 6
    seen = {article["sentiment"] for article in brief["articles"]}
    assert seen <= {"positive", "negative", "neutral"}
    assert seen >= {"positive", "negative"}

    synthesis = brief["synthesis"]
    for side in ("positive", "negative"):
        assert synthesis[side]["narrative"] and synthesis[side]["if_scenario"]
        assert isinstance(synthesis[side]["citations"], list)
    assert synthesis["caveat"] == CAVEAT


def test_analysis_shows_up_in_the_listing(app_factory) -> None:
    app = app_factory(FakeText())
    client, slug, _store = collected(app)
    client.post(f"/api/briefs/{slug}/analyze")
    summary = body(client.get("/api/briefs"))["data"][0]
    assert summary["status"] == "analyzed"
    assert sum(summary["sentiment_counts"].values()) == summary["article_count"] == 6


def test_evidence_that_is_not_in_the_article_is_stored_as_null(app_factory) -> None:
    app = app_factory(FakeText())
    client, slug, _store = collected(app)
    articles = body(client.post(f"/api/briefs/{slug}/analyze"))["data"]["articles"]
    demoted = [a for a in articles if a["evidence"] is None and a["summary"]]
    assert len(demoted) == 1 and "fire" in demoted[0]["title"].lower()


def test_one_analysis_is_one_call_per_batch_plus_one(app_factory) -> None:
    llm = CountingLLM()
    app = app_factory(llm)
    client, slug, _store = collected(app)
    client.post(f"/api/briefs/{slug}/analyze")
    systems = [system for system, _user in llm.calls]
    assert systems.count(SYSTEM_CLASSIFY) == 1 and len(systems) == 2


def test_reanalysis_keeps_the_articles_and_replaces_the_synthesis(app_factory) -> None:
    app = app_factory(FakeText())
    client, slug, store = collected(app)
    first = body(client.post(f"/api/briefs/{slug}/analyze"))["data"]

    store.mutate_brief(slug, lambda brief: brief["synthesis"].update({"caveat": "stale"}))
    second = body(client.post(f"/api/briefs/{slug}/analyze"))["data"]

    assert second["status"] == "analyzed"
    assert [a["id"] for a in second["articles"]] == [a["id"] for a in first["articles"]]
    assert [a["sentiment"] for a in second["articles"]] == [
        a["sentiment"] for a in first["articles"]
    ]
    assert second["synthesis"]["caveat"] == CAVEAT


def test_recollecting_sends_the_brief_back_to_collected(app_factory) -> None:
    app = app_factory(FakeText())
    client, slug, _store = collected(app)
    client.post(f"/api/briefs/{slug}/analyze")
    again = body(client.post(f"/api/briefs/{slug}/collect"))["data"]
    assert again["status"] == "collected" and again["synthesis"] is None
    assert client.post(f"/api/briefs/{slug}/analyze").status_code == 200


# --- refusals --------------------------------------------------------------


def test_analyze_needs_collected_articles(app_factory) -> None:
    app = app_factory(FakeText())
    client = app.test_client()
    slug = make_brief(client)
    res = client.post(f"/api/briefs/{slug}/analyze")
    assert res.status_code == 409 and body(res)["ok"] is False


def test_analyze_refuses_an_empty_collection(app_factory) -> None:
    app = app_factory(FakeText(), EmptyCollector())
    client, slug, _store = collected(app)
    res = client.post(f"/api/briefs/{slug}/analyze")
    assert res.status_code == 409 and "no articles" in body(res)["error"]


def test_analyze_unknown_and_bad_slugs(app_factory) -> None:
    client = app_factory(FakeText()).test_client()
    assert client.post("/api/briefs/ghost/analyze").status_code == 404
    assert client.post("/api/briefs/../analyze").status_code in (400, 404)


# --- failure leaves the brief untouched ------------------------------------


def unchanged_after(app, status: int) -> dict:
    """Collect, then let the analyst fail: brief.json must not move a byte."""
    client, slug, store = collected(app)
    before = store.brief_file(slug).read_bytes()

    res = client.post(f"/api/briefs/{slug}/analyze")
    assert res.status_code == status
    assert store.brief_file(slug).read_bytes() == before
    assert store.load_brief(slug)["status"] == "collected"
    assert all(article["sentiment"] is None for article in store.load_brief(slug)["articles"])
    return body(res)


def test_missing_key_is_503_and_changes_nothing(app_factory) -> None:
    payload = unchanged_after(app_factory(UnconfiguredLLM()), 503)
    assert payload["error"] == "llm-not-configured"


@pytest.mark.parametrize("retryable", [True, False])
def test_provider_failure_is_502_and_changes_nothing(app_factory, retryable: bool) -> None:
    payload = unchanged_after(app_factory(BrokenLLM(retryable)), 502)
    assert payload["retryable"] is retryable and "RateLimitError" in payload["error"]


def test_unusable_output_is_502_with_a_preview_and_changes_nothing(app_factory) -> None:
    payload = unchanged_after(app_factory(GarbageLLM("I refuse. " * 200)), 502)
    assert payload["error"] == "invalid-llm-output"
    assert payload["raw_preview"].startswith("I refuse.") and len(payload["raw_preview"]) == 500


class SynthesisFails(FakeText):
    """Classification answers normally; the closing call never lands."""

    def generate(self, system: str, user: str) -> str:
        if system == SYSTEM_CLASSIFY:
            return super().generate(system, user)
        raise LLMError("Overloaded: try again later", retryable=True)


def test_synthesis_failure_leaves_no_partial_classification(app_factory) -> None:
    payload = unchanged_after(app_factory(SynthesisFails()), 502)
    assert payload["ok"] is False and payload["retryable"] is True


# --- wiring ----------------------------------------------------------------


def test_fake_analyst_is_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))
    assert isinstance(create_app().config["LLM"], AnthropicText)
    monkeypatch.setenv("JANUSLINE_FAKE", "1")
    assert isinstance(create_app().config["LLM"], FakeText)


def test_model_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JANUSLINE_MODEL", raising=False)
    assert AnthropicText().model == "claude-sonnet-5"
    monkeypatch.setenv("JANUSLINE_MODEL", "claude-opus-5")
    assert AnthropicText().model == "claude-opus-5"
