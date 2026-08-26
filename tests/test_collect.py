from hashlib import sha1

import pytest
from support import NOW, NOW_ISO, BigCollector, StubCollector, big_feed, cutoff, parse

from core.collect import (
    MAX_PER_EDITION,
    MAX_TOTAL,
    CollectError,
    dedupe,
    feed_url,
    normalise_link,
    normalise_title,
    parse_edition,
    strip_html,
)
from core.fake_collect import FakeCollector


# -- url + text helpers ---------------------------------------------------


def test_feed_url_encodes_query_and_edition() -> None:
    url = feed_url("samsung electronics & co", "ko")
    assert url.startswith("https://news.google.com/rss/search?")
    assert "q=samsung+electronics+%26+co" in url
    assert "hl=ko&gl=KR&ceid=KR%3Ako" in url
    assert "hl=en-US&gl=US&ceid=US%3Aen" in feed_url("x", "en")
    with pytest.raises(ValueError):
        feed_url("x", "fr")


def test_strip_html_unwraps_markup_and_entities() -> None:
    raw = '<a href="x" target="_blank">Head&amp;line</a>&nbsp;&nbsp;<font>Source</font>'
    assert strip_html(raw) == "Head&line Source"
    assert strip_html(None) == ""


def test_normalisers() -> None:
    assert normalise_link("https://A.example.com/path/?utm=1#frag") == (
        "https://a.example.com/path"
    )
    assert normalise_title("Factory fire halts production!  - Korea Herald") == (
        normalise_title("Factory fire halts production - Korea Herald")
    )


# -- parsing --------------------------------------------------------------


def test_parses_fields_from_saved_feed() -> None:
    first = parse("google_news_ko")[0]
    assert first["title"] == "반도체 수출 3분기 연속 증가 - 연합뉴스"
    assert first["source"] == "연합뉴스"
    assert first["link"] == "https://news.example.com/ko/exports-up?utm_source=google&oc=5"
    assert first["id"] == sha1(first["link"].encode("utf-8")).hexdigest()
    assert first["published"] == "2026-08-18T09:12:00+00:00"
    assert first["sentiment"] is None
    assert first["summary"] is None and first["evidence"] is None
    assert "date_approx" not in first


def test_snippet_is_html_stripped() -> None:
    snippet = parse("google_news_ko")[0]["snippet"]
    assert snippet == "반도체 수출 3분기 연속 증가 연합뉴스"
    assert "<" not in snippet and "&nbsp;" not in snippet


def test_hostile_title_is_kept_verbatim_for_text_rendering() -> None:
    titles = [article["title"] for article in parse("google_news_ko")]
    assert [t for t in titles if "script" in t] == [
        "<script>alert('xss')</script> 주가 급등 - 머니투데이"
    ]


def test_non_http_scheme_article_is_dropped() -> None:
    links = [article["link"] for article in parse("google_news_ko")]
    assert not any(link.startswith("javascript:") for link in links)
    assert all(link.startswith("https://") for link in links)


def test_period_filter_and_date_approx_fallback() -> None:
    articles = parse("google_news_ko", days=90)
    links = [article["link"] for article in articles]
    assert "https://news.example.com/ko/ancient" not in links

    undated = [a for a in articles if a["link"].endswith("/no-date")][0]
    assert undated["date_approx"] is True
    assert undated["published"] == NOW_ISO

    assert len(parse("google_news_ko", days=4)) == 2  # the undated one and 18 Aug
    wide = [a["link"] for a in parse("google_news_ko", days=1000)]
    assert "https://news.example.com/ko/ancient" in wide


def test_unparseable_response_is_retryable() -> None:
    with pytest.raises(CollectError) as err:
        parse_edition(b"<html>not a feed</html>", NOW_ISO, cutoff(90))
    assert err.value.retryable is True


def test_empty_but_valid_feed_is_not_an_error() -> None:
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    assert parse_edition(empty, NOW_ISO, cutoff(90)) == []


# -- dedupe ---------------------------------------------------------------


def test_dedupe_by_normalised_link_then_title() -> None:
    merged = parse("google_news_ko") + parse("google_news_en")
    unique = dedupe(merged)
    links = [article["link"] for article in unique]

    # same path, different tracking parameters -> the en copy is dropped
    assert "https://news.example.com/ko/exports-up?utm_campaign=en-edition" not in links
    # different url, same headline modulo punctuation -> also dropped
    assert "https://news.example.com/en/factory-fire-syndicated" not in links
    assert len(merged) - len(unique) == 2


# -- caps -----------------------------------------------------------------


def test_edition_and_total_caps() -> None:
    assert len(parse_edition(big_feed("ko", 25), NOW_ISO, cutoff(90))) == MAX_PER_EDITION
    articles = BigCollector().collect("q", 90, ["ko", "en"], now=NOW)
    assert len(articles) == MAX_TOTAL == 40
    assert len({article["id"] for article in articles}) == MAX_TOTAL


# -- collector ------------------------------------------------------------


def test_collect_merges_editions_sorted_desc() -> None:
    articles = StubCollector().collect("samsung electronics", 90, ["ko", "en"], now=NOW)
    published = [article["published"] for article in articles]
    assert published == sorted(published, reverse=True)
    assert len(articles) == 6  # 4 ko + 4 en, minus two duplicates
    assert {"연합뉴스", "Bloomberg", "Financial Times"} <= {a["source"] for a in articles}


def test_single_edition_only_fetches_that_edition() -> None:
    assert len(StubCollector().collect("q", 90, ["en"], now=NOW)) == 4


def test_fake_collector_is_deterministic_and_applies_the_rules() -> None:
    first = FakeCollector().collect("demo", 90, ["ko", "en"])
    second = FakeCollector().collect("demo", 90, ["ko", "en"])
    identity = [(a["id"], a["title"], a["link"]) for a in first]
    assert identity == [(a["id"], a["title"], a["link"]) for a in second]

    links = [article["link"] for article in first]
    assert not any(link.startswith("javascript:") for link in links)  # scheme drop
    assert "https://example.com/ko/exports-up?utm_campaign=en" not in links  # dupe link
    assert "https://example.com/en/fire-duplicate" not in links  # dupe title
    assert "https://example.com/en/ancient" not in links  # period filter
    assert any("<script>" in article["title"] for article in first)
    assert any(article.get("date_approx") for article in first)
    assert len(first) == 8
