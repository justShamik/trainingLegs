"""Unit test suite for Web Routes, HTML templates, and Load Performance."""
import os
import time
from datetime import datetime
import pytest
from app.web.routes import create_app
from app.data.db import init_db, get_db_connection
from app.data.sync import save_activity, save_sleep_record, save_daily_physiology

TEST_WEB_DB = "test_web_routes.db"

@pytest.fixture(autouse=True)
def setup_teardown_web_db():
    if os.path.exists(TEST_WEB_DB):
        os.remove(TEST_WEB_DB)
        
    init_db(TEST_WEB_DB)
    
    today_iso = datetime.utcnow().strftime("%Y-%m-%dT07:00:00Z")
    today_date = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Populate fixture data into DB
    conn = get_db_connection(TEST_WEB_DB)
    save_activity({
        "id": "act-web-100",
        "date": today_iso,
        "sport_type": "Run",
        "name": "Tempo Threshold Run",
        "distance_m": 10000.0,
        "duration_s": 2700.0,
        "avg_pace_s_km": 270.0,
        "avg_hr": 165,
        "avg_cadence": 180,
        # missing fields: stride_length_cm, ground_contact_time_ms, vertical_oscillation_mm
        "splits": [
            {"id": "act-web-100_split_1", "split_index": 1, "distance_m": 1000.0, "duration_s": 270.0}
        ]
    }, conn)
    
    save_sleep_record({
        "id": "sleep-web-100",
        "date": today_date,
        "total_sleep_minutes": 490,
        "sleep_score": 88
    }, conn)
    
    save_daily_physiology({
        "id": "physio-web-100",
        "date": today_date,
        "resting_hr": 48,
        "hrv_score": 75.0,
        "acute_load": 400.0,
        "chronic_load": 380.0
    }, conn)
    conn.commit()
    conn.close()

    yield
    
    if os.path.exists(TEST_WEB_DB):
        os.remove(TEST_WEB_DB)

def test_dashboard_route_renders_data():
    app = create_app(db_path=TEST_WEB_DB)
    client = app.test_client()
    
    start_t = time.time()
    response = client.get("/dashboard")
    elapsed_seconds = time.time() - start_t
    
    print(f"\n[DASHBOARD LOAD TIME] Render completed in {elapsed_seconds*1000:.2f}ms")
    
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TRAINING DASHBOARD" in html
    assert "Tempo Threshold Run" in html
    assert "10.0" in html  # 10.0 km
    assert elapsed_seconds < 1.0, f"Dashboard load took {elapsed_seconds:.2f}s, exceeding 1.0s target"

def test_activity_detail_renders_form_metrics_and_na_badges():
    app = create_app(db_path=TEST_WEB_DB)
    client = app.test_client()
    
    response = client.get("/activity/act-web-100")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    
    assert "Tempo Threshold Run" in html
    assert "180" in html  # Cadence
    assert "Not Available" in html  # Explicit fallback for missing stride/GCT

def test_404_error_suppresses_stack_trace():
    app = create_app(db_path=TEST_WEB_DB)
    client = app.test_client()
    
    response = client.get("/activity/non-existent-activity-id")
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    
    assert "Resource Not Found" in html
    assert "Traceback" not in html
    assert "Exception" not in html

def test_sync_route_endpoint():
    app = create_app(db_path=TEST_WEB_DB)
    client = app.test_client()
    
    response = client.post("/sync", data={"full": "1"}, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Sync Result:" in html

def test_plan_discard_route_endpoint():
    from app.engine.planner import TrainingPlanner
    from app.data.queries import save_training_plan, get_active_training_plan

    app = create_app(db_path=TEST_WEB_DB)
    planner = TrainingPlanner(db_path=TEST_WEB_DB)
    plan = planner.generate_plan()
    save_training_plan(plan, db_path=TEST_WEB_DB)

    assert get_active_training_plan(db_path=TEST_WEB_DB) is not None

    client = app.test_client()
    response = client.post("/plan/discard", follow_redirects=True)
    assert response.status_code == 200
    assert get_active_training_plan(db_path=TEST_WEB_DB) is None

