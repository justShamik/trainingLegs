"""HR Zones page: protocol, analyse a synced test run, enter in COROS, plan integration, phone layout."""
import os
import re
import shutil

from playwright.sync_api import expect

from tests.e2e.conftest import _finish_context, _new_context
from tests.e2e.seed import ZONE_TEST_ACTIVITY_ID


def _analyse(page, sensor="Chest strap", temp="20"):
    page.goto("/zones")
    expect(page.locator("#activity_id")).to_have_value(ZONE_TEST_ACTIVITY_ID)   # titled "LTHR Test" -> preselected
    page.get_by_label(sensor).check()
    page.locator("#temperature_c").fill(temp)
    page.locator("#analyseBtn").click()


def test_nav_and_empty_state(page):
    page.goto("/")
    page.get_by_role("link", name="HR Zones").click()
    expect(page).to_have_url(re.compile(r"/zones$"))
    expect(page.locator("#currentLthr")).to_have_count(0)
    expect(page.locator("#testDue")).to_have_text("Due now")
    expect(page.get_by_role("heading", name="30-minute threshold time trial")).to_be_visible()
    expect(page.locator("#activity_id option", has_text="looks like a test")).to_have_count(1)


def test_analyse_run_shows_zones_and_mark_entered(page):
    _analyse(page)
    expect(page).to_have_url(re.compile(r"/zones\?test=\d+#result"))
    expect(page.get_by_role("heading", name="Threshold HR 168 bpm")).to_be_visible()
    expect(page.locator("#result .zone-conf")).to_have_text("Good confidence")
    expect(page.locator("#zoneRecommendation")).to_contain_text("Update COROS")
    expect(page.locator('#zoneTable tr[data-zone="Z2"] td').last).to_have_text("135–151 bpm")
    expect(page.locator('#zoneTable tr[data-zone="Z4"] td').last).to_have_text("160–171 bpm")
    expect(page.locator("#corosSteps")).to_contain_text("Threshold HR = 168 bpm")
    expect(page.locator("#currentLthr")).to_contain_text("168")
    page.locator("#markEnteredBtn").click()
    expect(page.locator("#enteredChip")).to_contain_text("Entered in COROS on")


def test_wrist_hot_test_is_poor_and_not_recommended(page):
    _analyse(page, sensor="Wrist (optical)", temp="31")
    expect(page.locator("#result .zone-conf")).to_have_text("Poor confidence")
    expect(page.locator("#zoneRecommendation")).to_contain_text("Don't change COROS")
    expect(page.locator("#currentLthr")).to_have_count(0)


def test_coros_outage_shows_plain_error_and_saves_nothing(page, server):
    shutil.rmtree(os.path.join(os.path.dirname(os.path.abspath(server.db_path)), "fit_cache"), ignore_errors=True)
    server.set_coros_mode("fail")
    _analyse(page)
    expect(page.locator("#zoneError")).to_contain_text("Couldn't get per-second data")
    expect(page.locator("#history")).to_have_count(0)


def test_delete_result_with_confirm(page):
    _analyse(page)
    page.once("dialog", lambda d: d.accept())
    page.locator("#deleteTestBtn").click()
    expect(page.get_by_text("Test result removed.")).to_be_visible()
    expect(page.locator("#history")).to_have_count(0)


def test_plan_uses_measured_threshold_after_test(page):
    page.goto("/plan")
    test_sessions = page.locator(".session-card", has_text="LTHR Test")
    if test_sessions.count():
        expect(test_sessions.first.locator(".zone-test-link")).to_have_attribute("href", "/zones#protocol")
    _analyse(page)
    page.goto("/plan")
    from tests.e2e.test_e2e_plan import create_season
    page.goto("/plan?new=1")
    create_season(page)
    expect(page.locator(".session-card", has_text="LTHR Test")).to_have_count(0)
    expect(page.get_by_text(re.compile(r"Threshold HR 168 bpm from your 30-min zone test"))).to_have_count(1)


def test_zones_page_fits_phone(request, chrome, server):
    ctx, observer = _new_context(request, chrome, server, viewport={"width": 390, "height": 844},
                                 device_scale_factor=2, is_mobile=True, has_touch=True)
    try:
        page = ctx.new_page()
        _analyse(page)
        expect(page.get_by_role("heading", name="Threshold HR 168 bpm")).to_be_visible()
        for _ in range(8):
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(80)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"/zones scrolls horizontally by {overflow}px on a phone"
    finally:
        _finish_context(request, ctx, observer)
