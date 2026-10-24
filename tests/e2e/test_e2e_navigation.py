"""Navbar, brand link, 404 page: every page links to every other page."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.seed import FULL_ACTIVITY_ID

# (navbar link text, url regex, h1 text)
GREETING = re.compile(r"Good (morning|afternoon|evening)|Hello")
NAV = [
    ("Home", r"/$", GREETING),
    ("Dashboard", r"/dashboard$", "TRAINING DASHBOARD"),
    ("Training Plan", r"/plan$", "PRESCRIBED TRAINING PLAN"),
    ("S&C", r"/strength$", "RUNNER STRENGTH"),
    ("HR Zones", r"/zones$", "Your training zones"),
    ("Goal Profile", r"/profile$", "RUNNER PROFILE"),
    ("Coach Chat", r"/chat$", "AI RUNNING COACH CHAT"),
]
START_PAGES = ["/", "/dashboard", "/plan", "/plan?tab=history", "/strength", "/zones", "/profile", "/chat",
               f"/activity/{FULL_ACTIVITY_ID}"]


@pytest.mark.parametrize("start", START_PAGES)
def test_every_navbar_link_from_every_page(page, start):
    for text, url_re, h1 in NAV:
        page.goto(start)
        nav = page.get_by_role("banner")
        nav.get_by_role("link", name=text, exact=True).click()
        expect(page).to_have_url(re.compile(url_re))
        expect(page.get_by_role("heading", level=1)).to_contain_text(h1)
        expect(nav.get_by_role("link", name=text, exact=True)).to_have_class(re.compile(r"\bactive\b"))


def test_brand_logo_returns_to_home(page):
    page.goto("/plan")
    page.get_by_role("banner").get_by_role("link", name=re.compile("RUNNING", re.I)).first.click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_role("heading", level=1)).to_contain_text(GREETING)


@pytest.mark.allow_errors(r"404")
def test_404_page_is_friendly_and_recoverable(page):
    resp = page.goto("/definitely-not-a-page")
    assert resp.status == 404
    expect(page.get_by_text("Resource Not Found")).to_be_visible()
    expect(page.get_by_text("Traceback")).to_have_count(0)
    page.get_by_role("link", name="Return to Dashboard").click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("TRAINING DASHBOARD")


@pytest.mark.allow_errors(r"404")
def test_unknown_activity_is_404_not_500(page):
    resp = page.goto("/activity/does-not-exist")
    assert resp.status == 404
    expect(page.get_by_text("Resource Not Found")).to_be_visible()


def test_navbar_shows_coros_status(page):
    page.goto("/")
    expect(page.get_by_role("banner").get_by_text(re.compile("COROS Connected", re.I))).to_be_visible()


def test_navbar_offers_connect_when_unauthenticated(page, server):
    server.set_coros_mode("unauth")
    page.goto("/plan")
    expect(page.get_by_role("banner").get_by_role("button", name=re.compile("Connect COROS", re.I))).to_be_visible()


def test_pages_declare_a_favicon_so_browsers_do_not_404(page):
    page.goto("/")
    assert page.locator("link[rel=icon]").count() == 1
