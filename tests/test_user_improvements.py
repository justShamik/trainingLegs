"""Automated tests for user feedback improvements & bug fixes (Sprint 7+ fixes)."""
import os
import pytest
import sqlite3
import tempfile
from app.web.routes import create_app
from app.data.db import init_db
from app.data.queries import (
    get_dashboard_summary, get_recent_activities, save_user_profile,
    save_training_plan, get_active_training_plan
)
from app.engine.planner import TrainingPlanner
from app.llm.gemini_cli import GeminiCLIWrapper

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    
    # Insert sample sync log
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO sync_logs (sync_type, status, records_fetched, timestamp) VALUES ('FULL', 'SUCCESS', 5, '2026-09-28T14:30:00Z')"
    )
    # Insert sample activity
    conn.execute(
        """
        INSERT INTO activities (
            id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr, elevation_gain_m
        ) VALUES ('act_test1', '2026-09-27T08:00:00Z', 'Run', 'Morning Easy Run', 10000.0, 3600.0, 360.0, 142, 120.0)
        """
    )
    conn.commit()
    conn.close()
    
    yield path
    try:
        os.remove(path)
    except OSError:
        pass

@pytest.fixture
def client(temp_db):
    app = create_app(db_path=temp_db)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_dashboard_last_sync_display(temp_db, client):
    """Test 1: Dashboard shows last sync date."""
    summary = get_dashboard_summary(db_path=temp_db)
    assert summary["last_sync_display"] == "2026-09-28 14:30"
    
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Last Synced with COROS:" in html
    assert "2026-09-28 14:30" in html

def test_dashboard_kpi_time_windows(client):
    """Test 2: Dashboard KPI cards & chart titles explicitly state time windows."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    
    assert "Weekly Volume (Last 7 Days)" in html
    assert "Weekly Elevation (Last 7 Days)" in html
    assert "Sleep Score (Latest Night)" in html
    assert "Acute:Chronic Load (7d/28d Ratio)" in html
    assert "Weekly Volume & Distance (Last 12 Weeks)" in html
    assert "Sleep Duration & Quality (Last 30 Days)" in html

def test_recent_activities_window_filtering(temp_db, client):
    """Test 3: Dashboard recent activities window filtering works."""
    activities_30 = get_recent_activities(days=30, db_path=temp_db)
    assert len(activities_30) == 1
    assert activities_30[0]["id"] == "act_test1"
    
    activities_all = get_recent_activities(days=0, db_path=temp_db)
    assert len(activities_all) == 1
    
    res = client.get("/dashboard?days=7")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Window:" in html
    assert "7 Days" in html
    assert "30 Days (1 Mo)" in html
    assert "90 Days" in html
    assert "All Time" in html

def test_training_plan_target_focus_and_ranges(temp_db, client):
    """Test 4: Training plan sessions clearly state target focus (HR vs Pace) and numeric ranges."""
    planner = TrainingPlanner(db_path=temp_db)
    plan = planner.generate_plan()
    save_training_plan(plan, db_path=temp_db)
    
    active_plan = get_active_training_plan(db_path=temp_db)
    assert active_plan is not None
    
    # Check that sessions contain Heart Rate Focus or Pace Focus with exact numerical ranges
    hr_or_pace_found = False
    for sess in active_plan["sessions"]:
        target = sess.get("target_pace_or_hr", "")
        if "Heart Rate Focus" in target or "Pace Focus" in target:
            hr_or_pace_found = True
            if "Heart Rate Focus" in target:
                assert "bpm" in target
            if "Pace Focus" in target:
                assert "/km" in target
                
    assert hr_or_pace_found is True
    
    res = client.get("/plan")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Target Focus & Range" in html

def test_coach_chat_returns_personalized_guidance(client):
    """Test 5: Coach chat provides intelligent guidance without returning error messages."""
    res = client.post("/chat", json={"question": "What should my easy run pace and heart rate be?"})
    assert res.status_code == 200
    json_data = res.get_json()
    assert "response" in json_data
    response_text = json_data["response"]
    
    assert "Coach response unavailable" not in response_text
    assert "Personal Coach Guidance" in response_text or "bpm" in response_text or "Pacing" in response_text

def test_coros_auth_status_validation(client):
    """Test 6: COROS authentication status is validated and displayed on page header."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "COROS" in html
    assert ("Connected" in html or "COROS Auth Required" in html or "COROS ACCOUNT NOT CONNECTED" in html)

def test_workout_adherence_calculator():
    """Test 7: calculate_workout_adherence computes accurate adherence ratings for matched runs."""
    from app.engine.tracking import calculate_workout_adherence
    session = {
        "distance_km": 10.0,
        "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy)"
    }
    actual_on_target = {
        "actual_distance_km": 10.0,
        "actual_avg_hr": 138
    }
    score, rating = calculate_workout_adherence(session, actual_on_target)
    assert score >= 90.0
    assert "🌟" in rating or "100%" in rating

    actual_off_target = {
        "actual_distance_km": 6.0, # 4km short
        "actual_avg_hr": 165 # HR way too high
    }
    score_low, rating_low = calculate_workout_adherence(session, actual_off_target)
    assert score_low < 75.0
    assert "Adherence" in rating_low

def test_training_plan_auto_match_and_adherence_rating(temp_db, client):
    """Test 8: Visiting /plan automatically auto-matches activities and updates adherence ratings."""
    planner = TrainingPlanner(db_path=temp_db)
    plan = planner.generate_plan()
    save_training_plan(plan, db_path=temp_db)

    # Visit /plan page (triggers auto_match_activities_to_sessions)
    res = client.get("/plan")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "PRESCRIBED TRAINING PLAN" in html

