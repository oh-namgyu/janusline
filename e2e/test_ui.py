"""Browser round trips over the offline fixtures: create, collect, analyse, delete."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

QUERY = "Meridian Semiconductor"
ARTICLES = 8
# fixture headlines the offline analyst classifies the same way every run
POSITIVE_TITLE = "Analysts raise price target after strong quarter"
NEGATIVE_TITLE = "Regulator opens antitrust review"
NEUTRAL_TITLE = "Supplier dispute heads to arbitration"
UNGROUNDED_TITLE = "Factory fire halts production - Korea Herald"
HOSTILE_TITLE = "<script>alert('xss')</script> 주가 급등"
MOBILE = {"width": 480, "height": 900}


# The app ships CSP `default-src 'self'`, which forbids eval inside the page, so
# every wait and assertion below goes through locators rather than page scripts.
def home(page: Page, server: str) -> None:
    page.goto(server + "/#/")
    expect(page.locator("#view-home")).to_be_visible()


def open_brief(page: Page, server: str, slug: str) -> None:
    page.goto(f"{server}/#/brief/{slug}")
    expect(page.locator("#view-brief")).to_be_visible()
    expect(page.locator("#bv-status")).to_have_text("analyzed")


def create_brief(page: Page, server: str, query: str) -> None:
    home(page, server)
    page.fill("#f-query", query)
    page.click("#f-submit")
    expect(page.locator("#view-brief")).to_be_visible()
    expect(page.locator("#bv-query")).to_have_text(query)


def delete_first_card(page: Page) -> None:
    page.locator(".card-actions").first.get_by_role("button", name="Delete").click()
    page.locator(".confirm-bar").first.get_by_role("button", name="Delete").click()


def centre_of(page: Page) -> float:
    box = page.locator("#timeline").bounding_box()
    return box["x"] + box["width"] / 2


def test_create_collect_analyse_and_delete(page: Page, server: str) -> None:
    home(page, server)
    expect(page.locator("#brief-empty")).to_be_visible()
    expect(page.locator("#brief-count")).to_have_text("0")

    # creating runs the collection too, so the brief arrives already filled
    create_brief(page, server, QUERY)
    expect(page.locator("#bv-status")).to_have_text("collected")
    expect(page.locator("#bv-meta")).to_contain_text(f"{ARTICLES} articles")
    expect(page.locator("#bv-meta")).to_contain_text("ko + en")
    expect(page.locator("#bv-cost")).to_contain_text("your API credits")
    expect(page.locator("#bv-collect")).to_have_text("Re-collect")

    # nothing is classified yet, so every article rides the axis as a chip
    expect(page.locator(".tl-entry")).to_have_count(ARTICLES)
    expect(page.locator(".tl-chip")).to_have_count(ARTICLES)
    expect(page.locator(".tl-tag").first).to_have_text("unclassified")
    expect(page.locator("#synth-positive .synth-empty")).to_be_visible()

    page.click("#bv-analyze")
    expect(page.locator("#bv-status")).to_have_text("analyzed")
    expect(page.locator("#bv-analyze")).to_have_text("Re-analyze")
    # the offline analyst is deterministic: four for, two against, two neither
    expect(page.locator(".gauge-legend")).to_contain_text("4 positive")
    expect(page.locator(".gauge-legend")).to_contain_text("2 negative")
    expect(page.locator(".ratio-bar .ratio-pos")).to_be_visible()
    # a quarter neutral is not an ambiguous query
    expect(page.locator("#bv-ambiguous")).to_be_hidden()

    page.click("#bv-back")
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card-title")).to_have_text(QUERY)
    expect(page.locator(".card")).to_contain_text(f"{ARTICLES} articles")
    expect(page.locator(".card .pill")).to_have_text("analyzed")

    delete_first_card(page)
    expect(page.locator(".card")).to_have_count(0)
    expect(page.locator("#brief-empty")).to_be_visible()
    expect(page.locator("#brief-count")).to_have_text("0")


def test_timeline_puts_each_side_on_its_own_side(page: Page, server: str, analysed: str) -> None:
    open_brief(page, server, analysed)
    expect(page.locator(".tl-entry")).to_have_count(ARTICLES)

    favourable = page.locator(".tl-pos", has_text=POSITIVE_TITLE)
    unfavourable = page.locator(".tl-neg", has_text=NEGATIVE_TITLE)
    expect(favourable).to_have_count(1)
    expect(unfavourable).to_have_count(1)
    expect(favourable.locator(".tl-tag")).to_have_text("positive")
    expect(unfavourable.locator(".tl-tag")).to_have_text("negative")

    # the sides are not just class names: they are left and right of the axis
    centre = centre_of(page)
    left = favourable.bounding_box()
    right = unfavourable.bounding_box()
    assert left["x"] + left["width"] <= centre
    assert right["x"] >= centre

    # neutral rides the axis as a chip, and undated articles say so
    expect(page.locator(".tl-chip")).to_have_count(2)
    expect(page.locator(".tl-chip", has_text=NEUTRAL_TITLE)).to_have_count(1)
    expect(page.locator(".tl-meta", has_text="~").first).to_be_visible()
    expect(page.locator(".tl-tick-date").first).to_be_visible()

    # grounding: a quote where the model found one, a mark where it did not
    expect(favourable.locator(".tl-quote")).to_contain_text(POSITIVE_TITLE)
    ungrounded = page.locator(".tl-neg", has_text=UNGROUNDED_TITLE)
    expect(ungrounded.locator(".tl-noquote")).to_contain_text("no direct quote")

    # article links leave the app in an isolated tab
    link = favourable.locator(".tl-title .link")
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert link.get_attribute("target") == "_blank"


def test_both_readings_and_their_citations(page: Page, server: str, analysed: str) -> None:
    open_brief(page, server, analysed)

    for side in ("#synth-positive", "#synth-negative"):
        expect(page.locator(f"{side} .synth-text")).not_to_be_empty()
        expect(page.locator(f"{side} .synth-if-label")).to_contain_text("IF this narrative holds")
        expect(page.locator(f"{side} .synth-if-text")).not_to_be_empty()
    expect(page.locator("#synth-positive .synth-text")).to_contain_text("Auric Foundry")
    expect(page.locator("#synth-caveat")).to_contain_text("Machine-generated")
    expect(page.locator("#synth-caveat")).to_contain_text("never fetched")

    # a citation is a reference into the timeline, and it goes there
    cites = page.locator("#synth-negative .synth-cite")
    expect(cites).to_have_count(2)
    cites.first.click()
    expect(page.locator(".is-cited")).to_have_count(1)
    expect(page.locator(".tl-neg.is-cited")).to_have_count(1)


def test_hostile_headline_stays_literal(page: Page, server: str, analysed: str) -> None:
    dialogs: list = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    open_brief(page, server, analysed)
    hostile = page.locator(".tl-card", has_text=HOSTILE_TITLE)
    expect(hostile).to_have_count(1)
    expect(hostile.locator(".tl-title")).to_have_text(HOSTILE_TITLE)

    scripts = page.locator("script")
    bodies = [scripts.nth(index).text_content() or "" for index in range(scripts.count())]
    assert not any("alert('xss')" in body for body in bodies)
    assert dialogs == []


def test_narrow_viewport_stacks_and_names_the_polarity(page: Page, server: str, analysed: str) -> None:
    page.set_viewport_size(MOBILE)
    open_brief(page, server, analysed)

    favourable = page.locator(".tl-pos", has_text=POSITIVE_TITLE)
    unfavourable = page.locator(".tl-neg", has_text=NEGATIVE_TITLE)
    # left and right are gone: both sides start at the same edge, full width
    left = favourable.bounding_box()
    right = unfavourable.bounding_box()
    assert abs(left["x"] - right["x"]) < 1
    assert abs(left["width"] - right["width"]) < 1

    # so the polarity has to be said in words, not only in colour
    expect(favourable.locator(".tl-tag")).to_be_visible()
    expect(favourable.locator(".tl-tag")).to_have_text("positive")
    expect(unfavourable.locator(".tl-tag")).to_have_text("negative")
    assert page.locator(".tl-node").first.is_hidden()

    # the two readings stack as well
    positive = page.locator("#synth-positive").bounding_box()
    negative = page.locator("#synth-negative").bounding_box()
    assert negative["y"] > positive["y"]
    assert abs(positive["x"] - negative["x"]) < 1


def test_export_is_a_standalone_document(page: Page, server: str, analysed: str, tmp_path) -> None:
    response = page.request.get(f"{server}/api/briefs/{analysed}/export")
    assert response.status == 200
    disposition = response.headers["content-disposition"]
    assert f'attachment; filename="{analysed}-janusline.html"' == disposition

    document = response.text()
    assert "Auric Foundry" in document
    assert "<script" not in document
    assert "Favourable reading" in document and "Unfavourable reading" in document
    assert "IF this narrative holds" in document
    assert "Machine-generated" in document
    assert POSITIVE_TITLE in document and NEGATIVE_TITLE in document
    # the hostile fixture headline is escaped, not neutralised by removal
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)" in document

    # it has to stand on its own: no origin, no network, no scripts
    saved = tmp_path / "export.html"
    saved.write_text(document, encoding="utf-8")
    requests: list = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(saved.as_uri())
    expect(page.locator("h1")).to_have_text("Auric Foundry")
    expect(page.locator(".card.pos", has_text=POSITIVE_TITLE)).to_have_count(1)
    expect(page.locator(".card.neg", has_text=NEGATIVE_TITLE)).to_have_count(1)
    expect(page.locator(".card.mid", has_text=NEUTRAL_TITLE)).to_have_count(1)
    expect(page.locator("ol.refs li")).not_to_have_count(0)
    assert requests == [saved.as_uri()]


def test_export_button_is_offered_once_there_is_something_to_export(
    page: Page, server: str, analysed: str
) -> None:
    open_brief(page, server, analysed)
    expect(page.locator("#bv-export")).to_be_enabled()
    # the endpoint answers with an attachment, so the tab the button opens turns
    # into a download rather than a page — the request is what can be observed
    with page.context.expect_event("request", lambda r: "/export" in r.url) as sent:
        page.click("#bv-export")
    assert sent.value.url.endswith(f"/api/briefs/{analysed}/export")
