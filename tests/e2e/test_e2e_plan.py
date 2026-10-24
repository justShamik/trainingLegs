"""Training plan: generate build/deload, discard (confirm dialog), log workouts, auto-match, block summary."""
import re

from playwright.sync_api import expect


def accept_next_dialog(page, expected_text=None):
    seen = []

    def handler(dialog):
        seen.append(dialog.message)
        dialog.accept()

    page.once("dialog", handler)
    return seen


def create_season(page):
    """Set up a season plan from the plan page: preview, then create."""
    if not page.locator("#createPlanForm").count():
        page.goto("/plan?new=1")
    page.locator("#previewPlanBtn").click()
    expect(page.locator("#runwayCard")).to_be_visible()
    page.locator("#createPlanBtn").click()
    expect(page.locator("#planCreated")).to_be_visible()
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()


def test_seeded_plan_is_shown(page):
    page.goto("/plan")
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()
    expect(page.get_by_text("Volume Compliance")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Discard Plan"))).to_be_visible()


def test_discard_plan_confirm_accept_then_create_season(page):
    page.goto("/plan")
    seen = accept_next_dialog(page)
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    expect(page.get_by_text("No Active Training Plan Generated")).to_be_visible()
    assert seen and "discard" in seen[0].lower()
    expect(page.get_by_role("button", name=re.compile("Discard Plan"))).to_have_count(0)
    expect(page.locator("#createPlanForm")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Generate Build Week"))).to_have_count(0)
    create_season(page)
    expect(page.locator("#phaseTimeline")).to_be_visible()


def test_discard_with_several_plans_stays_discarded_after_reload(page):
    page.goto("/plan")
    create_season(page)
    accept_next_dialog(page)
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    expect(page.get_by_text("No Active Training Plan Generated")).to_be_visible()
    page.reload()
    expect(page.get_by_text("No Active Training Plan Generated")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Discard Plan"))).to_have_count(0)


def test_discard_plan_dialog_dismissed_keeps_plan(page):
    page.goto("/plan")
    page.once("dialog", lambda d: d.dismiss())
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()
    expect(page.get_by_text("No Active Training Plan Generated")).to_have_count(0)


def _open_first_log_form(page):
    details = page.locator("details.disclosure").first
    details.get_by_text("Log / Update Workout Status").click()
    return details


def test_log_workout_completed_via_form(page):
    page.goto("/plan")
    details = _open_first_log_form(page)
    details.locator("input[name=actual_distance_km]").fill("8.2")
    details.locator("input[name=actual_duration_min]").fill("50")
    details.locator("input[name=actual_avg_hr]").fill("146")
    details.locator("input[name=user_notes]").fill("Felt <b>great</b>")
    details.get_by_role("button", name="Save Status").click()
    expect(page).to_have_url(re.compile(r"/plan$"))
    expect(page.get_by_text("COMPLETED").first).to_be_visible()
    expect(page.get_by_text("Post-Run Feedback").first).to_be_visible()
    expect(page.get_by_text("Workout Adherence Rating").first).to_be_visible()


def test_log_workout_skipped_and_modified(page):
    page.goto("/plan")
    details = _open_first_log_form(page)
    details.locator("select[name=status]").select_option("Skipped")
    details.get_by_role("button", name="Save Status").click()
    expect(page.get_by_text("SKIPPED").first).to_be_visible()

    details = _open_first_log_form(page)
    details.locator("select[name=status]").select_option("Modified")
    details.locator("input[name=actual_distance_km]").fill("4")
    details.get_by_role("button", name="Save Status").click()
    expect(page.get_by_text("MODIFIED").first).to_be_visible()


def test_auto_match_button(page):
    page.goto("/plan")
    page.get_by_role("button", name=re.compile("Auto-Match COROS Runs")).click()
    expect(page).to_have_url(re.compile(r"/plan$"))
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()


def test_plan_page_without_plan_and_generate_from_empty(page):
    page.goto("/plan")
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    create_season(page)


def test_history_tab_replaces_block_summary(page):
    page.goto("/plan")
    expect(page.get_by_role("banner").get_by_role("link", name="Block Summary")).to_have_count(0)
    page.locator("#tab-history").click()
    expect(page).to_have_url(re.compile(r"/plan\?tab=history$"))
    expect(page.locator("#historyWeeks tbody tr")).to_have_count(12)
    expect(page.locator("#historyWeeks tr.is-current")).to_contain_text("This week")
    expect(page.locator("#historyPlans tbody tr").first).to_contain_text("Active")
    expect(page.locator("#historyChart")).to_be_visible()
    assert page.locator("#historyChart").bounding_box()["height"] > 50
    page.goto("/block-summary")
    expect(page).to_have_url(re.compile(r"/plan\?tab=history$"))


def test_generate_plan_also_schedules_sc(page):
    page.goto("/plan")
    create_season(page)
    page.get_by_role("button", name=re.compile(r"Week 2 -")).click()
    chip = page.locator(".sc-chip").first
    expect(chip).to_be_visible()
    chip.click()
    expect(page).to_have_url(re.compile(r"/strength\?session="))
    expect(page.locator("#scSchedule")).to_be_visible()
    expect(page.locator("#scDate")).to_contain_text("Scheduled")


def test_plan_shows_period_banner_weeks_and_collapse(page):
    page.goto("/plan")
    expect(page.get_by_text(re.compile(r"Plan period: \w{3} \d+ \w{3} \d{4} – \w{3} \d+ \w{3} \d{4} \(5 weeks"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"Week 1 \(current\)"))).to_be_visible()
    # weeks sit inside phase cards: open every phase to reach week 5
    for ph in page.locator("details.phase-card:not([open])").all():
        ph.locator("summary.phase-card__head").click()
    expect(page.get_by_role("button", name=re.compile(r"Week 5 -"))).to_be_visible()
    week2_body = page.locator("#week-body-2")
    expect(week2_body).to_be_hidden()
    page.get_by_role("button", name=re.compile(r"Week 2 -")).click()
    expect(week2_body).to_be_visible()
    expect(page.locator("#today-session")).to_have_count(1)
