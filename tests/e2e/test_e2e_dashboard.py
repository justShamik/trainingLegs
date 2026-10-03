"""Dashboard: KPI cards, charts, window filters, activity detail, both sync buttons."""
import json
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e.seed import (
    ESCAPE_ACTIVITY_NAME, FULL_ACTIVITY_ID, FULL_ACTIVITY_NAME, OLD_ACTIVITY_NAME, SPARSE_ACTIVITY_ID,
)


def rows(page):
    return page.locator("table.data-table tbody tr")


def row_dates(page):
    return [r.locator("td").first.inner_text().strip() for r in rows(page).all()]


def test_kpis_and_charts_render(page):
    page.goto("/dashboard")
    for title in ("Weekly Volume (Last 7 Days)", "Sleep Score (Latest Night)", "Acute:Chronic Load"):
        expect(page.get_by_text(title).first).to_be_visible()
    expect(page.get_by_text("Last Synced with COROS")).to_be_visible()
    expect(page.locator("#lastSyncTime")).not_to_contain_text("Never")
    for cid in ("volumeChart", "sleepChart", "physioChart"):
        expect(page.locator(f"#{cid}")).to_be_visible()
    assert page.evaluate("window.__chartCount") == 3


def test_window_filters_7_30_90_all(page):
    counts = {}
    for label, days in (("7 Days", 7), ("30 Days", 30), ("90 Days", 90), ("All Time", 0)):
        page.goto("/dashboard")
        page.get_by_role("link", name=label).click()
        expect(page).to_have_url(re.compile(rf"days={days}$"))
        counts[days] = rows(page).count()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days + 1)).strftime("%Y-%m-%d")
        if days:
            assert all(d >= cutoff for d in row_dates(page)), f"{days}d window shows older rows"
    assert 0 < counts[7] < counts[30] < counts[90] <= counts[0], counts
    # only "All Time" reveals the 200-day-old run
    expect(page.get_by_text(OLD_ACTIVITY_NAME)).to_be_visible()
    page.goto("/dashboard?days=90")
    expect(page.get_by_text(OLD_ACTIVITY_NAME)).to_have_count(0)


def test_activity_names_are_html_escaped(page):
    page.goto("/dashboard?days=7")
    cell = page.locator("table.data-table td strong", has_text="Escape")
    expect(cell).to_have_text(ESCAPE_ACTIVITY_NAME)
    assert page.locator("table.data-table td strong b, table.data-table td strong i").count() == 0


def test_open_activity_with_full_running_dynamics_from_table(page):
    page.goto("/dashboard?days=7")
    row = rows(page).filter(has_text=FULL_ACTIVITY_NAME)
    row.get_by_role("link", name=re.compile("View Details")).click()
    expect(page).to_have_url(re.compile(f"/activity/{FULL_ACTIVITY_ID}$"))
    expect(page.get_by_role("heading", level=1)).to_have_text(FULL_ACTIVITY_NAME)
    for label, value in (("Avg Cadence", "178"), ("Stride Length", "112"), ("Ground Contact Time", "231"),
                         ("Vertical Oscillation", "8"), ("Running Power", "262")):
        card = page.locator(".card", has_text=label).first
        expect(card).to_contain_text(value)
    expect(page.locator("table.data-table tbody tr")).to_have_count(10)
    page.get_by_role("link", name=re.compile("Back to Dashboard")).click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("TRAINING DASHBOARD")


def test_sparse_activity_shows_not_available_not_zero(page):
    page.goto(f"/activity/{SPARSE_ACTIVITY_ID}")
    expect(page.get_by_text("Not Available").first).to_be_visible()
    expect(page.get_by_text("No lap split records available")).to_be_visible()


def _sync(page, button_name, overlay_text):
    """Click a sync button; verify overlay + highlighted button while in flight; wait for the result page."""
    page.goto("/dashboard")
    page.evaluate("sessionStorage.removeItem('__e2e_sync')")
    page.get_by_role("button", name=re.compile(button_name)).click(no_wait_after=True)
    page.wait_for_url(re.compile("sync_status="), timeout=30_000)
    state = json.loads(page.evaluate("sessionStorage.getItem('__e2e_sync')"))
    assert state["display"] == "flex" and state["width"] > 0, f"overlay not shown while syncing: {state}"
    assert "is-syncing" in state["btnClass"], state
    assert overlay_text in state["msg"], state
    expect(page.locator("#syncOverlay")).to_be_hidden()  # result page: overlay gone
    expect(page.get_by_role("button", name=re.compile(button_name))).not_to_have_class(re.compile("is-syncing"))


def test_sync_pending_shows_overlay_then_success_banner(page):
    _sync(page, "Sync Pending Data", "latest activities")
    expect(page).to_have_url(re.compile("sync_status=success"))
    banner = page.get_by_text("Sync Result:")
    expect(banner).to_be_visible()
    expect(page.get_by_text(re.compile("Sync INCREMENTAL completed successfully"))).to_be_visible()
    expect(page.get_by_text("Freshly Synced Run")).to_be_visible()
    expect(page.locator("#lastSyncTime")).not_to_contain_text("Never")


def test_sync_full_history_shows_overlay_then_success_banner(page):
    _sync(page, "Sync 365 Days History", "365 days")
    expect(page.get_by_text(re.compile("Sync FULL completed successfully"))).to_be_visible()
    page.get_by_role("link", name="All Time").click()
    expect(page.get_by_text("Historic Run 120d")).to_be_visible()


def test_back_button_never_leaves_overlay_stuck(page):
    _sync(page, "Sync Pending Data", "latest activities")
    page.goto("/plan")
    page.go_back()
    expect(page.locator("#syncOverlay")).to_be_hidden()
    expect(page.get_by_role("button", name=re.compile("Sync Pending Data"))).to_be_enabled()


def test_sync_failure_shows_error_banner(page, server):
    server.set_coros_mode("fail")
    _sync(page, "Sync Pending Data", "latest activities")
    expect(page).to_have_url(re.compile("sync_status=error"))
    expect(page.get_by_text(re.compile("failed", re.I)).first).to_be_visible()


def test_sync_when_not_authenticated_prompts_login(page, server):
    server.set_coros_mode("unauth")
    page.goto("/dashboard")
    expect(page.get_by_text("COROS ACCOUNT NOT CONNECTED")).to_be_visible()
    page.get_by_role("button", name=re.compile("Sync Pending Data")).click()
    expect(page.get_by_text(re.compile("login required", re.I))).to_be_visible(timeout=20_000)


def test_authenticate_button_triggers_login_flow(page, server):
    server.set_coros_mode("unauth")
    page.goto("/dashboard")
    page.get_by_role("button", name=re.compile("Authenticate COROS via Browser")).click()
    expect(page.get_by_text(re.compile("login window opened", re.I))).to_be_visible()
