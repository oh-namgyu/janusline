"""Browser round trips over the offline fixtures: create, collect, analyse, delete."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

QUERY = "Meridian Semiconductor"
ARTICLES = 8


# The app ships CSP `default-src 'self'`, which forbids eval inside the page, so
# every wait and assertion below goes through locators rather than page scripts.
def home(page: Page, server: str) -> None:
    page.goto(server + "/#/")
    expect(page.locator("#view-home")).to_be_visible()


def create_brief(page: Page, server: str, query: str) -> None:
    home(page, server)
    page.fill("#f-query", query)
    page.click("#f-submit")
    expect(page.locator("#view-brief")).to_be_visible()
    expect(page.locator("#bv-query")).to_have_text(query)


def delete_first_card(page: Page) -> None:
    page.locator(".card-actions").first.get_by_role("button", name="Delete").click()
    page.locator(".confirm-bar").first.get_by_role("button", name="Delete").click()


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

    page.click("#bv-analyze")
    expect(page.locator("#bv-status")).to_have_text("analyzed")
    expect(page.locator("#bv-analyze")).to_have_text("Re-analyze")
    # the offline analyst is deterministic: four for, two against, two neither
    expect(page.locator(".gauge-legend")).to_contain_text("4 positive")
    expect(page.locator(".gauge-legend")).to_contain_text("2 negative")
    expect(page.locator(".ratio-bar .ratio-pos")).to_be_visible()

    page.click("#bv-back")
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card-title")).to_have_text(QUERY)
    expect(page.locator(".card")).to_contain_text(f"{ARTICLES} articles")
    expect(page.locator(".card .pill")).to_have_text("analyzed")

    delete_first_card(page)
    expect(page.locator(".card")).to_have_count(0)
    expect(page.locator("#brief-empty")).to_be_visible()
    expect(page.locator("#brief-count")).to_have_text("0")
