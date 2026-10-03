"""Unit test suite for Plan Generation Engine and Deterministic Guardrails."""
import os
import pytest
from app.data.db import init_db
from app.data.queries import save_user_profile, get_active_training_plan
from app.engine.guardrails import (
    validate_plan_volume_increase, validate_no_back_to_back_hard_days,
    validate_max_consecutive_days, validate_80_20_intensity, validate_weekly_plan
)
from app.engine.planner import TrainingPlanner

TEST_PLAN_DB = "test_plan_engine.db"

@pytest.fixture(autouse=True)
def setup_teardown_plan_db():
    if os.path.exists(TEST_PLAN_DB):
        os.remove(TEST_PLAN_DB)
    init_db(TEST_PLAN_DB)
    yield
    if os.path.exists(TEST_PLAN_DB):
        os.remove(TEST_PLAN_DB)

def test_guardrail_volume_increase():
    assert validate_plan_volume_increase(50.0, 54.0) is True   # +8%
    assert validate_plan_volume_increase(50.0, 58.0) is False  # +16%

def test_guardrail_no_back_to_back_hard_days():
    valid_sessions = [
        {"day_of_week": "Tue", "session_type": "Threshold"},
        {"day_of_week": "Wed", "session_type": "Easy Aerobic"},
        {"day_of_week": "Thu", "session_type": "Easy Aerobic"},
        {"day_of_week": "Sat", "session_type": "Long Run"}
    ]
    invalid_sessions = [
        {"day_of_week": "Tue", "session_type": "Threshold"},
        {"day_of_week": "Wed", "session_type": "Long Run"}
    ]
    assert validate_no_back_to_back_hard_days(valid_sessions) is True
    assert validate_no_back_to_back_hard_days(invalid_sessions) is False

def test_guardrail_max_consecutive_days():
    valid_5_days = [
        {"session_type": "Easy Aerobic"},
        {"session_type": "Easy Aerobic"},
        {"session_type": "Rest"},
        {"session_type": "Threshold"},
        {"session_type": "Easy Aerobic"}
    ]
    invalid_5_consecutive = [
        {"session_type": "Easy Aerobic"},
        {"session_type": "Easy Aerobic"},
        {"session_type": "Threshold"},
        {"session_type": "Easy Aerobic"},
        {"session_type": "Long Run"}  # 5 active days in a row without rest
    ]
    assert validate_max_consecutive_days(valid_5_days, max_consecutive=4) is True
    assert validate_max_consecutive_days(invalid_5_consecutive, max_consecutive=4) is False

def test_guardrail_80_20_intensity():
    valid_plan_sessions = [
        {"session_type": "Threshold", "distance_km": 8.0},     # 16% hard
        {"session_type": "Easy Aerobic", "distance_km": 12.0},  # 24% easy
        {"session_type": "Easy Aerobic", "distance_km": 10.0},  # 20% easy
        {"session_type": "Long Run", "distance_km": 20.0}       # 40% easy/long
    ] # Total 50km, easy = 42km = 84%
    assert validate_80_20_intensity(valid_plan_sessions) is True

def test_end_to_end_plan_generation_for_3_profiles():
    # 1. 10K Goal Profile
    save_user_profile({
        "race_distance_type": "10K",
        "race_date": "2026-10-15",
        "target_time_str": "0:45:00",
        "weekly_hours_available": 6.0,
        "available_days": "Mon,Tue,Thu,Sat"
    }, db_path=TEST_PLAN_DB)
    
    planner_10k = TrainingPlanner(db_path=TEST_PLAN_DB)
    plan_10k = planner_10k.generate_plan()
    assert plan_10k["goal_distance"] == "10K"
    assert "Daniels" in plan_10k["methodology_name"]
    assert len(plan_10k["sessions"]) == 35  # 5 weeks x 7 dated days
    assert plan_10k["total_weeks"] == 5

    # 2. Marathon Goal Profile
    save_user_profile({
        "race_distance_type": "Marathon",
        "race_date": "2026-11-20",
        "target_time_str": "3:45:00",
        "weekly_hours_available": 8.0
    }, db_path=TEST_PLAN_DB)
    
    planner_mara = TrainingPlanner(db_path=TEST_PLAN_DB)
    plan_mara = planner_mara.generate_plan()
    assert plan_mara["goal_distance"] == "Marathon"
    assert "Pfitzinger" in plan_mara["methodology_name"] or "Daniels" in plan_mara["methodology_name"]

    # 3. 50K Ultra Goal Profile
    save_user_profile({
        "race_distance_type": "50K Ultra",
        "race_date": "2026-12-05",
        "target_time_str": "6:00:00",
        "weekly_hours_available": 10.0
    }, db_path=TEST_PLAN_DB)
    
    planner_ultra = TrainingPlanner(db_path=TEST_PLAN_DB)
    plan_ultra = planner_ultra.generate_plan()
    assert plan_ultra["goal_distance"] == "50K Ultra"
    assert "Uphill Athlete" in plan_ultra["methodology_name"]
    # Check Vert / Time-on-feet session presence
    session_types = [s["session_type"] for s in plan_ultra["sessions"]]
    assert "Vert/Time-on-Feet" in session_types
