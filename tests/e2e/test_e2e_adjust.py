"""Session adjustments in the browser: swap for an alternative, missed + rebalance, and cancel (no JS needed)."""
import re
import sqlite3
from datetime import date, timedelta

from playwright.sync_api import expect

# Repeating 7-day cycle anchored on TODAY (offset 0): rest days around it keep every guardrail satisfied
CYCLE = [("Threshold", 6), ("Easy Aerobic", 7), ("Rest", 0), ("Easy Aerobic", 7), ("Long Run", 14),
         ("Easy Aerobic", 6), ("Rest", 0)]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _plan_with_threshold_today(db_path: str) -> None:
    """Active 5-week plan whose session TODAY is a 6 km Threshold run; recent runs removed so auto-match
    on /plan load cannot complete it."""
    from app.data.queries import save_training_plan
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sessions = []
    for w in range(5):
        for i in range(7):
            d = monday + timedelta(days=7 * w + i)
            stype, km = CYCLE[(d - today).days % 7]
            sessions.append({
                "session_type": stype, "distance_km": float(km), "duration_min": float(km * 6),
                "target_pace_or_hr": ("Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)" if stype == "Threshold"
                                      else "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"
                                      if stype != "Rest" else "Rest & Recovery"),
                "stated_purpose": f"{stype} session", "week_number": w + 1, "day_of_week": DAYS[i],
                "session_date": d.isoformat()})
    save_training_plan({"start_date": monday.isoformat(), "total_weeks": 5, "total_volume_km": 41.0,
                        "goal_distance": "Marathon", "methodology_name": "E2E adjust plan",
                        "methodology_rationale": "Crafted for the adjust flow", "sessions": sessions}, db_path=db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("DELETE FROM activities WHERE substr(date, 1, 10) >= ?", ((today - timedelta(days=2)).isoformat(),))
        conn.commit()
    finally:
        conn.close()


def _open_adjust(page):
    page.goto("/plan")
    today_card = page.locator("#today-session")
    expect(today_card).to_contain_text("Threshold")
    today_card.get_by_role("link", name="Can't do this? Swap or rebalance").click()
    expect(page).to_have_url(re.compile(r"/session/.+/adjust$"))
    expect(page.get_by_role("heading", level=1)).to_have_text("Can't do this session?")


def _choose_reason(page, reason):
    page.locator("#reason").select_option(reason)
    page.get_by_role("button", name="Show options").click()
    expect(page.locator("#swap-card")).to_be_visible()


def test_swap_flow_end_to_end(page, server):
    _plan_with_threshold_today(server.db_path)
    _open_adjust(page)
    page.locator("#note").fill("Airport day")
    _choose_reason(page, "travel")
    page.locator("label[data-option=easy]").click()
    page.get_by_role("button", name="Preview swap").click()
    expect(page.get_by_text("Preview – nothing saved yet")).to_be_visible()
    row = page.locator("#adjust-changes tbody tr")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("Threshold 6 km")
    expect(row).to_contain_text("Easy Aerobic")
    page.get_by_role("button", name="Confirm changes").click()
    expect(page).to_have_url(re.compile(r"/plan\?adjusted=swap$"))
    expect(page.locator("#adjust-saved")).to_contain_text("Session swapped.")
    card = page.locator("#today-session")
    expect(card).to_contain_text("Originally: Threshold 6 km")
    expect(card).to_contain_text("Swapped")
    expect(card).to_contain_text("Airport day")
    expect(card.locator(".stat-main").first).to_have_text("Easy Aerobic")
    # still adjustable (not done yet), and logging it records Modified
    card.get_by_text("Log / Update Workout Status").click()
    card.get_by_role("button", name="Save Status").click()
    expect(page.locator("#today-session")).to_contain_text("MODIFIED")


def test_missed_and_rebalance_flow_end_to_end(page, server):
    _plan_with_threshold_today(server.db_path)
    _open_adjust(page)
    _choose_reason(page, "time")
    page.get_by_role("button", name="Preview rebalanced week").click()
    expect(page.get_by_text("Preview – nothing saved yet")).to_be_visible()
    table = page.locator("#adjust-changes")
    expect(table.locator("tr", has_text="Missed").first).to_contain_text("Skipped")
    expect(page.get_by_text("How the week was rebalanced")).to_be_visible()
    page.get_by_role("button", name="Confirm changes").click()
    expect(page).to_have_url(re.compile(r"/plan\?adjusted=missed$"))
    expect(page.locator("#adjust-saved")).to_contain_text("week rebalanced")
    card = page.locator("#today-session")
    expect(card).to_contain_text("SKIPPED")
    expect(card).to_contain_text("Missed")
    expect(card.get_by_role("link", name="Can't do this? Swap or rebalance")).to_have_count(0)
    expect(page.get_by_text(re.compile(r"✗ 1"))).to_be_visible()


def test_illness_offers_only_rest_or_very_easy(page, server):
    _plan_with_threshold_today(server.db_path)
    _open_adjust(page)
    _choose_reason(page, "illness")
    options = page.locator("#swap-form label[data-option]")
    expect(options).to_have_count(2)
    expect(page.locator("label[data-option=rest]")).to_contain_text("Recommended")
    expect(page.locator("label[data-option=very_easy]")).to_be_visible()


def test_cancel_from_adjust_and_preview_saves_nothing(page, server):
    _plan_with_threshold_today(server.db_path)
    _open_adjust(page)
    page.locator("#adjust-cancel").click()
    expect(page).to_have_url(re.compile(r"/plan$"))
    _open_adjust(page)
    _choose_reason(page, "weather")
    page.get_by_role("button", name="Preview swap").click()
    expect(page.get_by_role("button", name="Confirm changes")).to_be_visible()
    page.get_by_role("link", name="Choose a different option").click()
    expect(page.locator("#swap-card")).to_be_visible()
    page.get_by_role("button", name="Preview rebalanced week").click()
    page.locator("#adjust-cancel").click()
    expect(page).to_have_url(re.compile(r"/plan$"))
    card = page.locator("#today-session")
    expect(card).to_contain_text("PENDING")
    expect(card).to_contain_text("Threshold")
    expect(page.get_by_text(re.compile("Originally:"))).to_have_count(0)
    expect(page.locator("#adjust-saved")).to_have_count(0)
