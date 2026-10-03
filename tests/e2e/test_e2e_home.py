"""Home page (/): browser-local greeting, today dials, sync panel states, race watchlist + refresh."""
import json
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import _finish_context, _new_context
from tests.e2e.seed import TODAY_STEPS

IST = "Asia/Kolkata"


@pytest.fixture
def ist_ctx(request, chrome, server):
    """A desktop context pinned to the user's timezone (Delhi NCR)."""
    ctx, observer = _new_context(request, chrome, server, timezone_id=IST, locale="en-IN",
                                 viewport={"width": 1440, "height": 900})
    yield ctx
    _finish_context(request, ctx, observer)


@pytest.mark.parametrize("clock,greeting", [
    ("2026-10-03T08:15:00+05:30", "Good morning"),
    ("2026-10-03T11:59:00+05:30", "Good morning"),
    ("2026-10-03T12:00:00+05:30", "Good afternoon"),
    ("2026-10-03T16:30:00+05:30", "Good afternoon"),
    ("2026-10-03T19:45:00+05:30", "Good evening"),
    ("2026-10-03T23:10:00+05:30", "Hello, night owl"),
    ("2026-10-03T03:00:00+05:30", "Hello, night owl"),
])
def test_greeting_follows_browser_local_time(ist_ctx, clock, greeting):
    page = ist_ctx.new_page()
    page.clock.set_fixed_time(clock)
    page.goto("/")
    expect(page.locator("#homeGreeting")).to_have_text(greeting)
    expect(page.locator("#homeDate")).to_have_text("Saturday, 3 October")
    assert int(page.locator("#homeGreeting").get_attribute("data-hour")) == int(clock[11:13])


def test_dials_visible_with_numbers(page):
    page.goto("/")
    dials = page.locator(".home-dials .dial")
    expect(dials).to_have_count(4)
    page.locator("#today").scroll_into_view_if_needed()
    for i in range(4):
        expect(dials.nth(i)).to_have_class(re.compile(r"\bis-hydrated\b"))
        expect(dials.nth(i)).to_have_class(re.compile(r"\bis-in\b"))
        expect(dials.nth(i).locator("svg.dial__svg .dial__fill")).to_have_count(1)
    steps = page.locator('.dial-tile[data-metric="steps"] .dial__value')
    expect(steps).to_have_text(f"{TODAY_STEPS:,}")
    expect(page.locator('.dial-tile[data-metric="calories"] .dial__value')).to_contain_text("1,850")
    expect(page.locator('.dial-tile[data-metric="sleep"] .dial__value')).to_have_text(re.compile(r"^\d+:\d\dh$"))
    expect(page.locator('.dial-tile[data-metric="activity"] .dial__value')).to_have_text(re.compile(r"^(\d+min|—)$"))
    # the ring is drawn from data-pct (steps 8,421 / 10,000)
    assert page.locator('.dial-tile[data-metric="steps"] .dial').get_attribute("data-pct").startswith("84")


def test_races_listed_with_status_and_safe_links(page):
    page.goto("/")
    page.locator("#races").scroll_into_view_if_needed()
    expect(page.get_by_role("heading", name="Race watchlist")).to_be_visible()
    expect(page.get_by_role("heading", name="50K near Delhi NCR (Nov–Jan)")).to_be_visible()
    watch = page.locator("#watchlistRaces .race-card")
    ncr = page.locator("#ncrRaces .race-card")
    assert watch.count() > 0 and ncr.count() > 0
    expect(watch.first).to_be_visible()
    for card in watch.all() + ncr.all():
        assert card.get_attribute("data-status") in ("open", "not_started", "closed", "unknown")
        expect(card.locator(".race-card__status")).to_have_count(1)
    links = page.locator("a.race-card__source")
    assert links.count() > 0
    for a in links.all():
        assert a.get_attribute("target") == "_blank"
        assert "noopener" in (a.get_attribute("rel") or "")
    expect(page.get_by_text("Last checked:")).to_be_visible()


def _submit_and_record(page, button, url_re):
    page.evaluate("sessionStorage.removeItem('__e2e_sync')")
    button.click(no_wait_after=True)
    page.wait_for_url(url_re, timeout=60_000)
    return json.loads(page.evaluate("sessionStorage.getItem('__e2e_sync')"))


def test_sync_buttons_show_loading_state_and_return_home(page):
    page.goto("/")
    expect(page.locator("#syncPanel")).to_have_attribute("data-state", "connected")
    expect(page.locator("#tokenStatus")).to_contain_text("Token valid")
    state = _submit_and_record(page, page.locator("#homeSyncPendingBtn"), re.compile(r"/\?.*sync_status=success"))
    assert state["display"] == "flex" and state["width"] > 0, state
    assert "is-syncing" in state["btnClass"], state
    assert "latest activities" in state["msg"], state
    expect(page.locator("#syncOverlay")).to_be_hidden()
    expect(page.get_by_text("Sync Result:")).to_be_visible()
    expect(page.locator("#homeSyncPendingBtn")).to_be_enabled()
    expect(page.locator("#homeLastSync")).not_to_contain_text("Never")


def test_full_history_sync_from_home(page):
    page.goto("/")
    state = _submit_and_record(page, page.locator("#homeSyncFullBtn"), re.compile(r"/\?.*sync_status=success"))
    assert "is-syncing" in state["btnClass"] and "365 days" in state["msg"], state
    expect(page.get_by_text(re.compile("Sync FULL completed successfully"))).to_be_visible()


def test_race_refresh_shows_overlay_then_message(page):
    page.goto("/")
    expect(page.locator("#raceRefreshHint")).to_be_visible()  # never checked yet
    state = _submit_and_record(page, page.get_by_role("button", name="Check race websites now"),
                               re.compile(r"race_status="))
    assert state["display"] == "flex" and "is-syncing" in state["btnClass"], state
    assert "race" in state["msg"].lower(), state
    expect(page.get_by_text("Race check:")).to_be_visible()
    expect(page.locator("#racesLastChecked")).not_to_contain_text("never")
    expect(page.locator("#raceRefreshHint")).to_have_count(0)


def test_expired_token_offers_reconnect(page, server):
    server.set_coros_mode("expired")
    page.goto("/")
    expect(page.locator("#syncPanel")).to_have_attribute("data-state", "expired")
    expect(page.locator("#tokenStatus")).to_have_text(re.compile("Token expired — reconnect"))
    expect(page.locator("#homeSyncPendingBtn")).to_be_disabled()
    expect(page.locator("#homeSyncFullBtn")).to_be_disabled()
    expect(page.locator("#syncLockedReason")).to_contain_text("expired")
    page.locator("#homeConnectBtn").click()
    expect(page).to_have_url(re.compile(r"/\?.*sync_status=success"))
    expect(page.get_by_text(re.compile("login window opened", re.I))).to_be_visible()


def test_disconnected_disables_sync(page, server):
    server.set_coros_mode("unauth")
    page.goto("/")
    expect(page.locator("#tokenStatus")).to_contain_text("COROS not connected")
    expect(page.locator("#homeSyncPendingBtn")).to_be_disabled()
    expect(page.locator("#homeConnectBtn")).to_be_visible()
    # bfcache / pageshow must not re-enable server-locked buttons
    page.goto("/plan")
    page.go_back()
    expect(page.locator("#homeSyncPendingBtn")).to_be_disabled()


def test_navbar_connect_returns_to_current_page(page, server):
    server.set_coros_mode("unauth")
    page.goto("/strength")
    page.get_by_role("banner").get_by_role("button", name=re.compile("Connect COROS", re.I)).click()
    expect(page).to_have_url(re.compile(r"/strength\?.*sync_status=success"))


def test_full_scroll_has_no_console_errors(page):
    page.goto("/")
    for _ in range(8):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(120)
    expect(page.locator("#ncrRaces .race-card").last).to_be_visible()


@pytest.mark.parametrize("width", [390, 360])
def test_mobile_no_horizontal_scroll(request, chrome, server, width):
    ctx, observer = _new_context(request, chrome, server, viewport={"width": width, "height": 844},
                                 device_scale_factor=2, is_mobile=True, has_touch=True)
    try:
        page = ctx.new_page()
        page.goto("/")
        expect(page.locator("#homeGreeting")).to_be_visible()
        for _ in range(10):
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(80)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"home scrolls horizontally by {overflow}px at {width}px"
        expect(page.locator(".home-dials .dial")).to_have_count(4)
    finally:
        _finish_context(request, ctx, observer)
