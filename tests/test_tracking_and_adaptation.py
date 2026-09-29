"""Unit tests for Sprint 5: Tracking, Execution Feedback, Overtraining Risk Detection & Adaptation."""
import pytest
import sqlite3
import os
from app.data.db import init_db, get_db_connection
from app.data.queries import (
    save_training_plan, get_active_training_plan, update_session_status,
    calculate_weekly_compliance, auto_match_activities_to_sessions,
    save_user_profile
)
from app.engine.tracking import generate_post_run_feedback, detect_overtraining_risk
from app.engine.planner import TrainingPlanner

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_coach_sprint5.db")
    init_db(db_file)
    
    # Setup default user profile
    save_user_profile({
        "race_distance_type": "Marathon",
        "race_date": "2026-11-15",
        "target_time_str": "3:30:00",
        "weekly_hours_available": 8.0,
        "available_days": "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
    }, db_path=db_file)
    
    return db_file


def test_post_run_feedback_generation():
    """Verify factual post-run execution feedback generation (FR-3.4)."""
    session = {
        "session_type": "Easy Aerobic",
        "distance_km": 10.0,
        "target_pace_or_hr": "Easy / Zone 2"
    }

    # Fast easy run with high HR
    fast_actual = {
        "actual_distance_km": 10.0,
        "actual_duration_min": 45.0,
        "actual_avg_pace_s_km": 270.0,  # 4:30/km
        "actual_avg_hr": 165
    }
    fb_fast = generate_post_run_feedback(session, fast_actual)
    assert "Distance on target" in fb_fast
    assert "Heart rate was elevated" in fb_fast or "Pace was fast" in fb_fast

    # Skipped session
    skipped_actual = {"status": "Skipped"}
    fb_skipped = generate_post_run_feedback(session, skipped_actual)
    assert "Session marked as skipped" in fb_skipped


def test_auto_match_activities_to_sessions(temp_db):
    """Verify auto-matching completed COROS activities to plan sessions (FR-3.1)."""
    conn = get_db_connection(temp_db)
    conn.execute("""
        INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr)
        VALUES ('act_run_01', '2026-09-21', 'Run', 'Morning Easy Run', 10200.0, 3400.0, 333.0, 142)
    """)
    conn.commit()
    conn.close()

    planner = TrainingPlanner(db_path=temp_db)
    plan = planner.generate_plan()
    save_training_plan(plan, db_path=temp_db)

    matched_count = auto_match_activities_to_sessions(db_path=temp_db)
    assert matched_count >= 1

    active_plan = get_active_training_plan(db_path=temp_db)
    completed_sessions = [s for s in active_plan["sessions"] if s.get("status") == "Completed"]
    assert len(completed_sessions) >= 1
    assert completed_sessions[0]["matched_activity_id"] == "act_run_01"


def test_weekly_compliance_calculation(temp_db):
    """Verify weekly volume & session compliance calculation (FR-3.2)."""
    planner = TrainingPlanner(db_path=temp_db)
    plan = planner.generate_plan()
    plan_id = save_training_plan(plan, db_path=temp_db)

    active_plan = get_active_training_plan(db_path=temp_db)
    sessions = active_plan["sessions"]
    
    # Mark first 2 running sessions completed, 1 skipped
    run_sessions = [s for s in sessions if s["session_type"] != "Rest"]
    if len(run_sessions) >= 3:
        update_session_status(run_sessions[0]["id"], "Completed", actual_distance_km=run_sessions[0]["distance_km"], db_path=temp_db)
        update_session_status(run_sessions[1]["id"], "Completed", actual_distance_km=run_sessions[1]["distance_km"], db_path=temp_db)
        update_session_status(run_sessions[2]["id"], "Skipped", db_path=temp_db)

    comp = calculate_weekly_compliance(plan_id=plan_id, db_path=temp_db)
    assert comp["completed_sessions"] == 2
    assert comp["skipped_sessions"] == 1
    assert comp["session_compliance_pct"] > 0.0


def test_overtraining_risk_detection(temp_db):
    """Verify overtraining & fatigue risk flag detection (FR-3.3 / AC-5.5)."""
    # Normal baseline test
    norm = detect_overtraining_risk(db_path=temp_db)
    assert norm["is_flagged"] is False

    # Insert fatigue signals: ACWR > 1.35 + 3 days of poor sleep (<65)
    conn = get_db_connection(temp_db)
    conn.execute("""
        INSERT INTO daily_physiology (id, date, acute_load, chronic_load, hrv_score)
        VALUES ('phys_01', '2026-09-21', 1400.0, 950.0, 42.0)
    """)
    for i in range(3):
        conn.execute(f"""
            INSERT INTO sleep_records (id, date, total_sleep_minutes, sleep_score)
            VALUES ('sleep_0{i}', '2026-09-1{7+i}', 320, 58)
        """)
    conn.commit()
    conn.close()

    risk = detect_overtraining_risk(db_path=temp_db)
    assert risk["is_flagged"] is True
    assert risk["risk_level"] in ("HIGH_RISK", "CRITICAL")
    assert risk["recommended_adjustment_pct"] < 0.0


def test_adaptive_plan_regeneration(temp_db):
    """Verify plan engine adapts next week's plan on low compliance or fatigue flags (AC-5.6)."""
    # Trigger fatigue flag
    conn = get_db_connection(temp_db)
    conn.execute("""
        INSERT INTO daily_physiology (id, date, acute_load, chronic_load, hrv_score)
        VALUES ('phys_crit', '2026-09-21', 1600.0, 1000.0, 38.0)
    """)
    for i in range(3):
        conn.execute(f"""
            INSERT INTO sleep_records (id, date, total_sleep_minutes, sleep_score)
            VALUES ('sleep_bad_{i}', '2026-09-1{7+i}', 300, 50)
        """)
    conn.commit()
    conn.close()

    planner = TrainingPlanner(db_path=temp_db)
    adapted_plan = planner.generate_plan()

    assert "ADAPTATION ALERT: Fatigue detected" in adapted_plan["methodology_rationale"]
    assert adapted_plan["is_deload"] is True
