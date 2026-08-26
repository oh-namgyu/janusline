from pathlib import Path

import pytest
from support import BrokenCollector, StubCollector, body, fixture, make_brief

from app import create_app
from core.collect import CollectError, GoogleNewsCollector
from core.fake_collect import FakeCollector


@pytest.fixture()
def app_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))

    def build(collector):
        application = create_app(collector=collector)
        application.config.update(TESTING=True)
        return application

    return build


def test_collect_endpoint_stores_articles(app_factory) -> None:
    app = app_factory(StubCollector())
    client = app.test_client()
    slug = make_brief(client)

    res = client.post(f"/api/briefs/{slug}/collect")
    assert res.status_code == 200
    brief = body(res)["data"]
    assert brief["status"] == "collected" and brief["synthesis"] is None
    assert len(brief["articles"]) == 6
    assert brief["articles"][0]["sentiment"] is None

    summary = body(client.get("/api/briefs"))["data"][0]
    assert summary["status"] == "collected" and summary["article_count"] == 6


def test_recollect_resets_analysis(app_factory) -> None:
    app = app_factory(StubCollector())
    client = app.test_client()
    store = app.config["STORAGE"]
    slug = make_brief(client)
    client.post(f"/api/briefs/{slug}/collect")

    brief = store.load_brief(slug)
    brief["status"] = "analyzed"
    brief["synthesis"] = {"positive": {}, "negative": {}, "caveat": "x"}
    for article in brief["articles"]:
        article["sentiment"] = "positive"
    store.save_brief(slug, brief)

    again = body(client.post(f"/api/briefs/{slug}/collect"))["data"]
    assert again["status"] == "collected" and again["synthesis"] is None
    assert all(article["sentiment"] is None for article in again["articles"])


def test_collect_failure_leaves_brief_byte_identical(app_factory) -> None:
    app = app_factory(BrokenCollector())
    client = app.test_client()
    store = app.config["STORAGE"]
    slug = make_brief(client)
    path = store.brief_file(slug)
    before = path.read_bytes()

    res = client.post(f"/api/briefs/{slug}/collect")
    assert res.status_code == 502
    payload = body(res)
    assert payload["ok"] is False and payload["retryable"] is True

    assert path.read_bytes() == before


def test_partial_edition_failure_leaves_brief_byte_identical(app_factory) -> None:
    """The first edition parses, the second dies: nothing is written."""

    class SecondEditionFails(GoogleNewsCollector):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def fetch(self, url: str) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return fixture("google_news_ko")
            raise CollectError("news feed unreachable (timeout)", retryable=True)

    collector = SecondEditionFails()
    app = app_factory(collector)
    client = app.test_client()
    store = app.config["STORAGE"]
    slug = make_brief(client)
    before = store.brief_file(slug).read_bytes()

    assert client.post(f"/api/briefs/{slug}/collect").status_code == 502
    assert collector.calls == 2
    assert store.brief_file(slug).read_bytes() == before
    assert store.load_brief(slug)["articles"] == []


def test_collect_honours_the_brief_period_and_editions(app_factory) -> None:
    app = app_factory(StubCollector())
    client = app.test_client()
    slug = make_brief(client, "single edition", lang=["en"])
    brief = body(client.post(f"/api/briefs/{slug}/collect"))["data"]
    assert len(brief["articles"]) == 4


def test_collect_unknown_slug(app_factory) -> None:
    client = app_factory(StubCollector()).test_client()
    assert client.post("/api/briefs/ghost/collect").status_code == 404
    assert client.post("/api/briefs/../collect").status_code in (400, 404)


def test_fake_collector_is_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))
    default = create_app().config["COLLECTOR"]
    assert isinstance(default, GoogleNewsCollector)
    assert not isinstance(default, FakeCollector)
    monkeypatch.setenv("JANUSLINE_FAKE", "1")
    assert isinstance(create_app().config["COLLECTOR"], FakeCollector)
