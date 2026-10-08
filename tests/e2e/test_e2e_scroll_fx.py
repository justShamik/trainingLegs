"""Shared scroll choreography (app/static/js/scroll-fx.js: GSAP + ScrollTrigger + Lenis) on every page.

For each page: the GSAP mode engages, scrolling the whole page raises no console errors, every
counted number / split heading ends with exactly the server-rendered text, nothing the script
claimed is left invisible, and ?motion=classic turns it off.
"""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.seed import FULL_ACTIVITY_ID

PAGES = ["/", "/dashboard", "/plan", "/strength", "/block-summary", "/profile", "/chat",
         f"/activity/{FULL_ACTIVITY_ID}", "/analytics"]

VALUES = ".card-value, .kpi-value, .kpi__value, .dial__value"
HEADINGS = "main h1, main h2, main h3"

SNAPSHOT_JS = """([vals, heads]) => ({
  values: [...document.querySelectorAll(vals)].map(e => e.textContent),
  headings: [...document.querySelectorAll(heads)].map(e => e.textContent),
})"""

# every element the script took over (or is still waiting to reveal) must end fully visible
STUCK_JS = """() => [...document.querySelectorAll(
    '[data-reveal="none"], .fx-pending, .split-inner, .scrub-word')]
  .filter(el => !el.closest('[hidden]') && el.getClientRects().length)
  .filter(el => {
    const cs = getComputedStyle(el), tf = cs.transform;
    const moved = tf !== 'none' && tf !== 'matrix(1, 0, 0, 1, 0, 0)';
    return el.classList.contains('fx-pending') || parseFloat(cs.opacity) < 0.999 || moved;
  })
  .map(el => (el.className || el.tagName) + ' op=' + getComputedStyle(el).opacity + ' tf=' + getComputedStyle(el).transform)"""

# the hero recedes while scrolled away; back at the top it must be fully restored
HERO_JS = """() => [...document.querySelectorAll('.page-hero__text, [data-fx-hero]')]
  .map(el => getComputedStyle(el)).filter(cs => parseFloat(cs.opacity) < 0.999
     || (cs.transform !== 'none' && cs.transform !== 'matrix(1, 0, 0, 1, 0, 0)')).length"""


IN_VIEW_REVEALED = """() => [...document.querySelectorAll('.fx-pending')]
  .filter(el => !el.closest('[hidden]'))
  .every(el => el.getBoundingClientRect().top > innerHeight * 0.85)"""

ALL_OPAQUE = "sel => [...document.querySelectorAll(sel)].every(c => getComputedStyle(c).opacity === '1')"


def scroll_through(page, step=700, pause=90):
    """Wheel to the bottom of the page (Lenis turns wheel events into smooth scrolling)."""
    page.mouse.move(40, 300)
    last = -1
    for _ in range(60):
        page.mouse.wheel(0, step)
        page.wait_for_timeout(pause)
        y = page.evaluate("Math.round(window.scrollY)")
        at_bottom = page.evaluate("window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4")
        if at_bottom and y == last:
            break
        last = y
    page.wait_for_timeout(1800)  # let batch reveals / count-ups finish


def snapshot(page):
    return page.evaluate(SNAPSHOT_JS, [VALUES, HEADINGS])


def scroll_top_and_settle(page):
    page.evaluate("window.ScrollFx && window.ScrollFx.lenis ? window.ScrollFx.lenis.scrollTo(0, {immediate: true}) : window.scrollTo(0, 0)")
    page.wait_for_timeout(600)


@pytest.mark.parametrize("path", PAGES)
def test_scroll_fx_engages_settles_and_keeps_server_text(page, path):
    page.goto(path + ("&" if "?" in path else "?") + "motion=classic")
    expect(page.locator("main")).to_be_visible()
    server = snapshot(page)

    page.goto(path)
    html = page.locator("html")
    expect(html).to_have_class(re.compile(r"\bgsap-fx\b"))
    expect(html).to_have_class(re.compile(r"\blenis\b"))
    if page.locator(".page-hero h1").count():
        expect(page.locator(".page-hero h1 .split-word")).not_to_have_count(0)
    # before any count-up starts the real values are shown, never a placeholder
    first = page.evaluate(SNAPSHOT_JS, [VALUES, HEADINGS])
    assert first["headings"] == server["headings"]

    # cards already in view on load must reveal without any scrolling
    page.wait_for_function(IN_VIEW_REVEALED, timeout=4000)

    scroll_through(page)
    final = snapshot(page)
    assert final["values"] == server["values"], f"{path}: counted values differ from server text"
    assert final["headings"] == server["headings"], f"{path}: heading text changed by word splitting"
    assert page.evaluate(STUCK_JS) == [], f"{path}: elements left invisible/transformed"
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1
    scroll_top_and_settle(page)
    assert page.evaluate(HERO_JS) == 0, f"{path}: hero not restored at the top"


@pytest.mark.parametrize("path", PAGES)
def test_classic_motion_disables_scroll_fx(page, path):
    page.goto(path + "?motion=classic")
    expect(page.locator("main")).to_be_visible()
    cls = page.locator("html").get_attribute("class") or ""
    assert "gsap-fx" not in cls and "lenis" not in cls.split()
    expect(page.locator(".split-word, .scrub-word")).to_have_count(0)
    expect(page.locator("html")).to_have_class(re.compile(r"\bjs-motion\b"))


def test_reduced_motion_disables_scroll_fx(request, chrome, server):
    from tests.e2e.conftest import _finish_context, _new_context
    ctx, observer = _new_context(request, chrome, server, reduced_motion="reduce")
    try:
        page = ctx.new_page()
        page.goto("/dashboard")
        expect(page.locator("main")).to_be_visible()
        assert "gsap-fx" not in (page.locator("html").get_attribute("class") or "")
        expect(page.locator(".split-word")).to_have_count(0)
    finally:
        _finish_context(request, ctx, observer)


@pytest.mark.allow_errors(r"404")
def test_error_page_scroll_fx(page):
    resp = page.goto("/definitely-not-a-page")
    assert resp.status == 404
    expect(page.locator("html")).to_have_class(re.compile(r"\bgsap-fx\b"))
    expect(page.get_by_text("Resource Not Found")).to_be_visible()
    page.wait_for_timeout(1800)
    assert page.evaluate(STUCK_JS) == []
    page.get_by_role("link", name="Return to Dashboard").click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("TRAINING DASHBOARD")


def test_dashboard_charts_render_and_are_untransformed(page):
    page.goto("/dashboard")
    expect(page.locator("html")).to_have_class(re.compile(r"\bgsap-fx\b"))
    scroll_through(page)
    assert page.evaluate("window.__chartCount") == 3
    for cid in ("volumeChart", "sleepChart", "physioChart"):
        box = page.locator(f"#{cid}").bounding_box()
        assert box and box["width"] > 0 and box["height"] > 0, cid
    tf = page.evaluate("[...document.querySelectorAll('.chart-card')].map(c => getComputedStyle(c).transform + '|' + getComputedStyle(c).opacity)")
    assert all(t == "none|1" for t in tf), tf


def test_chat_feed_scrolls_internally(page):
    page.goto("/chat")
    expect(page.locator("html")).to_have_class(re.compile(r"\bgsap-fx\b"))
    feed = page.locator("#chatFeed")
    expect(feed).to_have_attribute("data-lenis-prevent", "")
    # fill the feed so it overflows
    page.evaluate("""() => { const f = document.getElementById('chatFeed');
        for (let i = 0; i < 30; i++) { const d = document.createElement('div'); d.className = 'msg msg-coach';
          d.innerHTML = '<div class="msg-text">line ' + i + '</div>'; f.appendChild(d); }
        f.scrollTop = 0; }""")
    feed.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    box = feed.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    win_before = page.evaluate("window.scrollY")
    page.mouse.wheel(0, 300)
    page.wait_for_timeout(500)
    assert page.evaluate("document.getElementById('chatFeed').scrollTop") > 0
    assert abs(page.evaluate("window.scrollY") - win_before) < 2, "wheel over the feed scrolled the page"
    # the form still works
    page.locator("#userInput").fill("How is my training?")
    page.locator("#sendBtn").click()
    expect(page.locator("#chatFeed .msg-user .msg-text").last).to_have_text("How is my training?")


def test_plan_week_toggles_reveal_their_cards(page):
    page.goto("/plan")
    expect(page.locator("html")).to_have_class(re.compile(r"\bgsap-fx\b"))
    body = page.locator("#week-body-3")
    expect(body).to_be_hidden()
    page.get_by_role("button", name=re.compile(r"Week 3 -")).click()
    expect(body).to_be_visible()
    cards = body.locator(".session-card")
    assert cards.count() > 0
    page.wait_for_function(ALL_OPAQUE, arg="#week-body-3 .session-card", timeout=4000)
    # close and reopen: still visible, and the page can still be scrolled to the end
    page.get_by_role("button", name=re.compile(r"Week 3 -")).click()
    expect(body).to_be_hidden()
    page.get_by_role("button", name=re.compile(r"Week 3 -")).click()
    expect(body).to_be_visible()
    page.wait_for_function(ALL_OPAQUE, arg="#week-body-3 .session-card", timeout=4000)
    # a <details> log form inside an opened card still opens
    det = body.locator("details.disclosure").first
    det.locator("summary").click()
    expect(det.locator("form")).to_be_visible()
    scroll_through(page)
    assert page.evaluate(STUCK_JS) == []
