"""Season plan flow: Goal Profile checklist, tune-up races, preview -> create, phase drill-down, refresh, monthly push."""
import re
import sqlite3
from datetime import date, timedelta

from playwright.sync_api import expect

from tests.e2e.test_e2e_plan import accept_next_dialog, create_season


def _clear_history_answers(server):
    conn = sqlite3.connect(server.db_path)
    conn.execute("UPDATE user_profile SET injury_history = NULL, current_niggles = NULL")
    conn.commit()
    conn.close()


def _discard(page):
    page.goto("/plan")
    accept_next_dialog(page)
    page.get_by_role("button", name=re.compile("Discard Plan")).click()
    expect(page.get_by_text("No Active Training Plan Generated")).to_be_visible()


def test_checklist_sends_to_profile_and_back(page, server):
    _clear_history_answers(server)
    _discard(page)
    expect(page.get_by_text("Answer a few questions before we set up your plan")).to_be_visible()
    expect(page.locator('#setupChecklist li[data-check="history"]')).to_have_class(re.compile("is-missing"))
    expect(page.locator("#createPlanForm")).to_have_count(0)
    page.locator('#setupChecklist li[data-check="history"] a').click()
    expect(page).to_have_url(re.compile(r"/profile\?next=/plan#history$"))
    expect(page.locator("#profileNext")).to_be_visible()
    page.locator("textarea[name=injury_history]").fill("None")
    page.locator("textarea[name=current_niggles]").fill("None")
    page.get_by_role("button", name="Save and continue to plan").click()
    expect(page).to_have_url(re.compile(r"/plan$"))
    expect(page.locator("#createPlanForm")).to_be_visible()
    expect(page.locator('#setupChecklist li.is-missing')).to_have_count(0)


def test_tune_up_race_flows_into_the_season(page):
    race_day = date.today() + timedelta(days=100)
    tune = race_day - timedelta(days=35)
    page.goto("/profile#races")
    page.locator("#tuName").fill("City Half")
    page.locator("#tuDate").fill(tune.isoformat())
    page.locator("#tuDistance").select_option("Half Marathon")
    page.locator("#addTuneUpBtn").click()
    expect(page.locator("#raceSaved")).to_be_visible()
    expect(page.locator("#tuneUpTable")).to_contain_text("City Half")
    page.goto("/plan?new=1")
    expect(page.locator("#plan-setup")).to_contain_text("City Half")
    page.locator("#previewPlanBtn").click()
    expect(page.locator(f'#tuneUpCard li[data-tuneup="{tune.isoformat()}"]')).to_contain_text("race it")
    page.locator("#createPlanBtn").click()
    expect(page.locator("#planCreated")).to_be_visible()
    card = page.locator(".session-card", has=page.locator(".stat-main", has_text=re.compile(r"^Tune-up Race$")))
    phase = page.locator("details.phase-card", has=card)
    if phase.get_attribute("open") is None:
        phase.locator("summary.phase-card__head").click()
    week = phase.locator(".week-section", has=card)
    toggle = week.locator(".week-toggle")
    if toggle.get_attribute("aria-expanded") == "false":
        toggle.click()
    expect(card.first).to_be_visible()


def test_phase_outline_drilldown_and_refresh(page):
    page.goto("/plan")
    create_season(page)
    phases = page.locator("details.phase-card")
    assert phases.count() >= 3
    expect(page.locator("details.phase-card[open]")).to_have_count(1)
    last = phases.last
    expect(last).to_have_attribute("data-phase", "race")
    last.locator("summary.phase-card__head").click()
    toggle = last.locator(".week-toggle").last
    if toggle.get_attribute("aria-expanded") == "false":
        toggle.click()
    expect(last.locator(".session-card", has_text="Race").first).to_be_visible()
    expect(page.locator("#planBasis")).to_contain_text("Built from")
    page.locator("#refreshPlanBtn").click()
    expect(page.locator("#planRefreshed")).to_be_visible()
    expect(page.locator("#phaseTimeline")).to_be_visible()


def test_push_by_month(page):
    page.goto("/plan")
    create_season(page)
    page.locator("#sendToCorosBtn").click()
    months = page.locator("#pushWindows a[data-month]")
    assert months.count() >= 3
    expect(months.first).to_have_class(re.compile("is-active"))
    key = months.nth(1).get_attribute("data-month")
    months.nth(1).click()
    expect(page).to_have_url(re.compile(rf"/plan/push\?month={key}$"))
    dates = [d for d in page.locator(".push-item").evaluate_all("els => els.map(e => e.dataset.date)")]
    assert dates and all(d.startswith(key) for d in dates)
