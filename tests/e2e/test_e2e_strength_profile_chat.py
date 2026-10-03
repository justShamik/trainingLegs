"""Strength, profile, chat (sample + free text + escaping + API key), and a mobile smoke run."""
import re

import pytest
from playwright.sync_api import expect

from app.data.queries import get_user_profile

PHASES = ["Base", "Build", "Peak", "Taper"]


# ------------------------------------------------------------------- strength
@pytest.mark.parametrize("phase", PHASES)
def test_strength_generate_each_phase(page, phase):
    page.goto("/strength")
    page.get_by_role("button", name=re.compile(f"{phase} Phase", re.I)).click()
    expect(page).to_have_url(re.compile(r"/strength$"))
    expect(page.get_by_text(f"RUNNING PHASE: {phase.upper()}")).to_be_visible()
    expect(page.get_by_text("Form & Safety Cues").first).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Mark Workout Completed"))).to_be_visible()


def test_strength_mark_completed(page):
    page.goto("/strength")
    page.get_by_role("button", name=re.compile("Mark Workout Completed")).click()
    expect(page.get_by_text("COMPLETED").first).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Mark Workout Completed"))).to_have_count(0)
    # regenerating produces a fresh, not-yet-completed workout
    page.get_by_role("button", name=re.compile("Peak Phase", re.I)).click()
    expect(page.get_by_role("button", name=re.compile("Mark Workout Completed"))).to_be_visible()


def test_strength_auto_generates_when_none_exists(page, server):
    import sqlite3
    conn = sqlite3.connect(server.db_path)
    conn.execute("DELETE FROM strength_workouts")
    conn.commit()
    conn.close()
    page.goto("/strength")
    expect(page.get_by_text(re.compile("RUNNING PHASE:"))).to_be_visible()


# -------------------------------------------------------------------- profile
def test_profile_save_roundtrip(page, server):
    page.goto("/profile")
    page.locator("select[name=race_distance_type]").select_option(index=1)
    chosen = page.locator("select[name=race_distance_type]").input_value()
    page.locator("input[name=race_date]").fill("2027-04-18")
    page.locator("input[name=target_time_str]").fill("1:39:59")
    page.locator("input[name=weekly_hours_available]").fill("9.5")
    page.locator("input[name=available_days]").fill("Mon,Wed,Sat")
    page.locator("textarea[name=injury_history]").fill("Shin splints 2024")
    page.locator("textarea[name=current_niggles]").fill("left calf tight")
    page.get_by_role("button", name=re.compile("save", re.I)).click()
    expect(page.get_by_text("Profile Updated Successfully")).to_be_visible()

    prof = get_user_profile(db_path=server.db_path)
    assert prof["race_distance_type"] == chosen
    assert prof["race_date"] == "2027-04-18"
    assert prof["target_time_str"] == "1:39:59"
    assert float(prof["weekly_hours_available"]) == 9.5
    assert prof["available_days"] == "Mon,Wed,Sat"
    assert prof["current_niggles"] == "left calf tight"

    page.goto("/profile")
    expect(page.locator("input[name=target_time_str]")).to_have_value("1:39:59")
    expect(page.locator("textarea[name=injury_history]")).to_have_value("Shin splints 2024")


def test_niggle_in_profile_filters_strength_exercises(page):
    page.goto("/profile")
    page.locator("textarea[name=current_niggles]").fill("knee")
    page.get_by_role("button", name=re.compile("save", re.I)).click()
    page.goto("/strength")
    page.get_by_role("button", name=re.compile("Build Phase", re.I)).click()
    expect(page.get_by_text("INJURY & NIGGLE SAFETY FILTER ACTIVE")).to_be_visible()


def test_api_key_only_save_from_chat_does_not_wipe_profile(page, server):
    before = get_user_profile(db_path=server.db_path)
    page.goto("/chat")
    page.get_by_text("Configure Gemini API Key").click()
    page.locator("#geminiApiKeyInput").fill("AIzaSy-e2e-not-a-real-key")
    dialogs = []
    page.once("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.get_by_role("button", name="Save Key").click()
    page.wait_for_function("true")
    expect(page.locator("#geminiApiKeyInput")).to_be_visible()
    page.wait_for_timeout(500)
    assert dialogs and "saved successfully" in dialogs[0]
    after = get_user_profile(db_path=server.db_path)
    assert after["gemini_api_key"] == "AIzaSy-e2e-not-a-real-key"
    for k in ("race_distance_type", "race_date", "target_time_str", "weekly_hours_available",
              "available_days", "injury_history", "current_niggles"):
        assert after[k] == before[k], f"profile field {k} was wiped by key-only save"
    page.goto("/profile")
    expect(page.locator("input[name=target_time_str]")).to_have_value(before["target_time_str"])


# ----------------------------------------------------------------------- chat
def _coach_messages(page):
    return page.locator("#chatFeed .msg-coach .msg-text")


@pytest.mark.parametrize("label", ["Recent Volume & Pace Analysis", "ACWR Load Safety Check", "Sleep & HRV Recovery Trend"])
def test_chat_sample_questions_get_answers(page, label):
    page.goto("/chat")
    before = _coach_messages(page).count()
    page.get_by_role("button", name=re.compile(re.escape(label))).click()
    expect(_coach_messages(page)).to_have_count(before + 1, timeout=20_000)
    expect(_coach_messages(page).last).to_contain_text("E2E COACH ECHO")
    expect(page.locator("#loadingIndicator")).to_be_hidden()
    expect(page.locator("#sendBtn")).to_be_enabled()


def test_chat_free_text_and_html_is_escaped(page):
    page.goto("/chat")
    evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script><b>bold</b>'
    page.once("dialog", lambda d: d.dismiss())
    page.locator("#userInput").fill(evil)
    page.get_by_role("button", name="Send").click()
    expect(_coach_messages(page)).to_have_count(2, timeout=20_000)
    assert page.evaluate("window.__pwned") is None
    assert page.locator("#chatFeed img, #chatFeed script, #chatFeed b").count() == 0
    expect(page.locator("#chatFeed .msg-user .msg-text")).to_have_text(evil)
    expect(_coach_messages(page).last).to_contain_text("<b>bold</b>")  # echoed back as literal text


def test_chat_blank_input_is_blocked(page):
    page.goto("/chat")
    page.get_by_role("button", name="Send").click()
    expect(_coach_messages(page)).to_have_count(1)  # only the welcome message


# --------------------------------------------------------------------- mobile
@pytest.mark.parametrize("path", ["/", "/dashboard", "/plan", "/strength", "/block-summary", "/profile", "/chat", "/activity/e2e_full_dynamics"])
def test_mobile_390_smoke(mobile_page, path):
    mobile_page.goto(path)
    expect(mobile_page.get_by_role("heading", level=1)).to_be_visible()
    assert mobile_page.evaluate("window.innerWidth") == 390
    overflow = mobile_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"{path}: page scrolls horizontally by {overflow}px at 390px width"
    expect(mobile_page.get_by_role("banner").get_by_role("link", name="Coach Chat", exact=True)).to_be_visible()
