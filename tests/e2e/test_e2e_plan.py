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


def test_seeded_plan_is_shown(page):
    page.goto("/plan")
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()
    expect(page.get_by_text("Volume Compliance")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Discard Plan"))).to_be_visible()


def test_discard_plan_confirm_accept_then_generate_build_and_deload(page):
    page.goto("/plan")
    seen = accept_next_dialog(page)
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    expect(page.get_by_text("No Active Training Plan Generated")).to_be_visible()
    assert seen and "discard" in seen[0].lower()
    expect(page.get_by_role("button", name=re.compile("Discard Plan"))).to_have_count(0)

    page.get_by_role("button", name=re.compile("Generate Build Week")).click()
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()
    expect(page.get_by_text("(DELOAD)")).to_have_count(0)
    build_volume = page.get_by_text(re.compile(r"TARGET VOLUME")).inner_text()

    page.get_by_role("button", name=re.compile("Generate Deload Week")).click()
    expect(page.get_by_text("(DELOAD)")).to_be_visible()
    assert page.get_by_text(re.compile(r"TARGET VOLUME")).inner_text() != build_volume


def test_discard_with_several_plans_stays_discarded_after_reload(page):
    page.goto("/plan")
    page.get_by_role("button", name=re.compile("Generate Build Week")).click()
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()
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
    details = page.locator("details").first
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
    page.get_by_role("button", name=re.compile("Generate Build Week")).click()
    expect(page.get_by_text(re.compile("METHODOLOGY:"))).to_be_visible()


def test_block_summary_reachable_and_consistent_with_plan(page):
    page.goto("/plan")
    page.get_by_role("banner").get_by_role("link", name="Block Summary").click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("4-WEEK TRAINING BLOCK SUMMARY")
    expect(page.get_by_text("Block Prescribed Volume")).to_be_visible()
    expect(page.get_by_text("Historical Block Reports")).to_be_visible()
    expect(page.get_by_text(re.compile("No historical 4-week blocks"))).to_be_visible()


def test_plan_shows_period_banner_weeks_and_collapse(page):
    page.goto("/plan")
    expect(page.get_by_text(re.compile(r"Plan period: \w{3} \d+ \w{3} \d{4} – \w{3} \d+ \w{3} \d{4} \(5 weeks"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"Week 1 \(current\)"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"Week 5 -"))).to_be_visible()
    week2_body = page.locator("#week-body-2")
    expect(week2_body).to_be_hidden()
    page.get_by_role("button", name=re.compile(r"Week 2 -")).click()
    expect(week2_body).to_be_visible()
    expect(page.locator("#today-session")).to_have_count(1)
