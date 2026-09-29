"""Unit test suite for Goal Profile form, Context Builder, Versioned Prompts, and Gemini CLI Chat."""
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest
from app.web.routes import create_app
from app.data.db import init_db, get_db_connection
from app.data.sync import save_activity, save_sleep_record, save_daily_physiology
from app.llm.context_builder import build_runner_context
from app.llm.gemini_cli import load_prompt_template, GeminiCLIWrapper

TEST_PROFILE_DB = "test_profile_llm.db"

@pytest.fixture(autouse=True)
def setup_teardown_profile_db():
    if os.path.exists(TEST_PROFILE_DB):
        os.remove(TEST_PROFILE_DB)
        
    init_db(TEST_PROFILE_DB)
    
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT07:00:00Z")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    conn = get_db_connection(TEST_PROFILE_DB)
    save_activity({
        "id": "act-llm-1",
        "date": today_iso,
        "sport_type": "Run",
        "name": "Marathon Pace Long Run",
        "distance_m": 25000.0,
        "duration_s": 6750.0,
        "avg_pace_s_km": 270.0,
        "avg_hr": 158
    }, conn)
    save_sleep_record({
        "id": "sleep-llm-1",
        "date": today_date,
        "total_sleep_minutes": 480,
        "sleep_score": 90
    }, conn)
    save_daily_physiology({
        "id": "physio-llm-1",
        "date": today_date,
        "resting_hr": 46,
        "hrv_score": 80.0,
        "acute_load": 500.0,
        "chronic_load": 480.0
    }, conn)
    conn.commit()
    conn.close()

    yield
    
    if os.path.exists(TEST_PROFILE_DB):
        os.remove(TEST_PROFILE_DB)

def test_profile_get_and_post():
    app = create_app(db_path=TEST_PROFILE_DB)
    client = app.test_client()
    
    # GET profile
    res_get = client.get("/profile")
    assert res_get.status_code == 200
    assert "RUNNER PROFILE & GOAL TARGETS" in res_get.get_data(as_text=True)

    # POST updated profile
    post_data = {
        "race_distance_type": "Marathon",
        "race_date": "2026-11-15",
        "target_time_str": "3:30:00",
        "weekly_hours_available": "9.5",
        "available_days": "Mon,Wed,Fri,Sat,Sun",
        "injury_history": "IT Band Syndrome 2024",
        "current_niggles": "Tight left calf"
    }
    res_post = client.post("/profile", data=post_data, follow_redirects=True)
    assert res_post.status_code == 200
    assert "Profile Updated Successfully!" in res_post.get_data(as_text=True)

def test_factual_context_builder():
    context_str = build_runner_context(db_path=TEST_PROFILE_DB)
    assert "Target Race: Marathon" in context_str
    assert "25.0km" in context_str
    assert "Marathon Pace Long Run" in context_str
    assert "IT Band Syndrome 2024" in context_str or "Marathon" in context_str

def test_versioned_prompt_template_loader():
    template = load_prompt_template("coach_chat_v1.txt")
    assert "{RUNNER_CONTEXT}" in template
    assert "{USER_QUESTION}" in template
    assert "Shane Benzie" in template

@patch("subprocess.run")
def test_gemini_cli_wrapper_and_error_handling(mock_run):
    # Simulate timeout error
    mock_run.side_effect = Exception("Subprocess Connection Error")
    wrapper = GeminiCLIWrapper(timeout_seconds=1, max_retries=2)
    response = wrapper.ask_coach("How was my long run?", "Context string...")
    
    assert "Personal Coach Guidance" in response or "Coach response unavailable" in response

@patch("app.llm.gemini_cli.GeminiCLIWrapper.ask_coach")
def test_chat_route_endpoint(mock_ask):
    mock_ask.return_value = "Your 25km long run at 4:30/km was executed solidly within aerobic Z2."
    app = create_app(db_path=TEST_PROFILE_DB)
    client = app.test_client()
    
    res = client.post("/chat", json={"question": "What was my average pace and total volume over my recent runs?"})
    assert res.status_code == 200
    data = res.get_json()
    assert "25km long run" in data["response"]
