"""Unit tests for Sprint 6: Strength & Conditioning Engine & Web Routes."""
import pytest
import sqlite3
from app.data.db import init_db, get_db_connection
from app.data.queries import (
    seed_strength_exercises_if_empty, get_available_exercises,
    save_user_profile, save_strength_workout, get_active_strength_workout,
    update_strength_workout_status
)
from app.engine.strength import StrengthEngine
from app.web.routes import create_app

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_coach_sprint6.db")
    init_db(db_file)
    
    save_user_profile({
        "race_distance_type": "Marathon",
        "race_date": "2026-11-15",
        "target_time_str": "3:30:00",
        "weekly_hours_available": 8.0,
        "available_days": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
        "current_niggles": "None"
    }, db_path=db_file)
    
    return db_file

@pytest.fixture
def app_client(temp_db):
    app = create_app(db_path=temp_db)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_seed_and_get_available_exercises(temp_db):
    """Verify exercise library seeding and full retrieval when no niggles exist."""
    exercises = get_available_exercises(niggles_str="None", db_path=temp_db)
    assert len(exercises) >= 10
    names = [e["name"] for e in exercises]
    assert "Bulgarian Split Squat" in names
    assert "Romanian Deadlift (RDL)" in names
    assert "Pallof Press" in names


def test_niggle_safety_contraindication_filtering(temp_db):
    """Verify exercises with contraindicated niggles are filtered out (FR-4.2 / FR-4.4)."""
    # Active niggle: Knee & Achilles
    safe = get_available_exercises(niggles_str="Knee, Achilles", db_path=temp_db)
    safe_names = [e["name"] for e in safe]
    
    # Contraindicated exercises must NOT be present
    assert "Bulgarian Split Squat" not in safe_names
    assert "Weighted Eccentric Calf Raise" not in safe_names
    assert "Pogo Hops (Ankle Stiffness)" not in safe_names
    
    # Safe exercises MUST be present
    assert "Pallof Press" in safe_names
    assert "Seated Soleus Calf Raise" in safe_names
    assert "Chest-Supported Dumbbell Row" in safe_names


def test_strength_engine_phase_periodisation(temp_db):
    """Verify S&C Engine enforces running phase periodisation rules (FR-4.3)."""
    engine = StrengthEngine(db_path=temp_db)

    # Base Phase
    base_workout = engine.generate_workout(phase="Base")
    assert base_workout["phase"] == "Base"
    assert len(base_workout["exercises"]) >= 4
    for ex in base_workout["exercises"]:
        assert ex["prescribed_sets"] == 3
        assert "10-12" in ex["prescribed_reps"]
        assert ex["prescribed_rpe"] == 7

    # Build Phase
    build_workout = engine.generate_workout(phase="Build")
    assert build_workout["phase"] == "Build"
    for ex in build_workout["exercises"]:
        assert ex["prescribed_sets"] == 3
        assert "5-6" in ex["prescribed_reps"]
        assert ex["prescribed_rpe"] == 8

    # Taper Phase
    taper_workout = engine.generate_workout(phase="Taper")
    assert taper_workout["phase"] == "Taper"
    for ex in taper_workout["exercises"]:
        assert ex["prescribed_sets"] == 2
        assert ex["prescribed_rpe"] == 5


def test_strength_web_routes(app_client, temp_db):
    """Verify GET /strength, POST /strength/generate, POST /strength/update (AC-6.7)."""
    # GET /strength (auto-generates initial workout)
    res_get = app_client.get("/strength")
    assert res_get.status_code == 200
    assert b"RUNNER STRENGTH &amp; CONDITIONING" in res_get.data or b"RUNNER STRENGTH" in res_get.data

    # POST /strength/generate (Build phase)
    res_gen = app_client.post("/strength/generate", data={"phase": "Build"}, follow_redirects=True)
    assert res_gen.status_code == 200
    assert b"BUILD" in res_gen.data

    # Verify active workout saved in DB
    workout = get_active_strength_workout(db_path=temp_db)
    assert workout is not None
    assert workout["phase"] == "Build"

    # POST /strength/update (Mark completed)
    res_upd = app_client.post("/strength/update", data={"workout_id": workout["id"], "status": "Completed"}, follow_redirects=True)
    assert res_upd.status_code == 200
    assert b"COMPLETED" in res_upd.data
