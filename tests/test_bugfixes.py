"""Regression tests for the code-review bug fixes."""
import os
import tempfile
import pytest
from app.web.routes import create_app
from app.data.db import get_db_connection
from app.data.queries import (
    get_user_profile, save_user_profile, get_trend_charts_data, save_training_plan,
)
from app.data.sync import perform_sync
from app.engine.tracking import calculate_workout_adherence


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def client(temp_db):
    app = create_app(db_path=temp_db)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_key_only_profile_post_preserves_profile(temp_db, client):
    save_user_profile({"race_distance_type": "10K", "race_date": "2026-12-01",
                       "target_time_str": "45:00", "weekly_hours_available": 6.0,
                       "available_days": "Mon,Wed"}, db_path=temp_db)
    res = client.post("/profile", data={"gemini_api_key": "AIza-test"})
    assert res.status_code == 200
    profile = get_user_profile(db_path=temp_db)
    assert profile["gemini_api_key"] == "AIza-test"
    assert profile["race_distance_type"] == "10K"
    assert profile["target_time_str"] == "45:00"


def test_trend_charts_return_newest_rows(temp_db):
    from app.data.db import init_db
    init_db(temp_db)
    conn = get_db_connection(temp_db)
    for i in range(40):
        conn.execute(
            "INSERT INTO sleep_records (id, date, total_sleep_minutes, sleep_score) VALUES (?, ?, 420, 80)",
            (f"s{i}", f"2026-08-{i + 1:02d}" if i < 31 else f"2026-09-{i - 30:02d}"),
        )
    conn.commit()
    conn.close()
    labels = get_trend_charts_data(db_path=temp_db)["sleep_trend"]["labels"]
    assert len(labels) == 30
    assert labels[-1] == "2026-09-09"
    assert labels == sorted(labels)


def test_skipped_session_scores_zero():
    score, rating = calculate_workout_adherence(
        {"distance_km": 10.0, "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm"},
        {"status": "Skipped"},
    )
    assert score == 0.0
    assert "Skipped" in rating


def test_failed_mcp_calls_are_not_logged_as_success(temp_db):
    class FailingClient:
        call_failures = ["querySportRecords: exit code 1"]
        def is_authenticated(self): return True
        def fetch_workouts(self, since_date=None): return []
        def fetch_sleep_records(self, since_date=None): return []
        def fetch_daily_physiology(self, since_date=None): return []

    ok, count, msg, _ = perform_sync(client=FailingClient(), db_path=temp_db)
    assert ok is False and count == 0
    conn = get_db_connection(temp_db)
    statuses = [r["status"] for r in conn.execute("SELECT status FROM sync_logs")]
    conn.close()
    assert statuses == ["FAILED"]


def test_405_is_not_converted_to_500(client):
    res = client.get("/sync")
    assert res.status_code == 405


def test_json_encoded_mcp_text_is_unwrapped_and_parsed(monkeypatch):
    import json
    from app.mcp_client.coros_client import CorosMCPClient
    text = ("Sport Records — 2026-09-01 to 2026-09-29 (1 records)\n====\n\n"
            "1. Outdoor Run — 2026-09-29\n   Location: Countdown Intervals\n"
            "   Duration: 52:52 | Distance: 8.40 km\n   Average Pace: 6:17 /km | Avg HR: 155 bpm | Calories: 763 kcal\n"
            "   LabelId: 480672546503557126 | SportType: 100\n")
    stdout = json.dumps({"content": [{"type": "text", "text": json.dumps(text)}]})

    class Res:
        returncode = 0
        stderr = ""
    Res.stdout = stdout
    monkeypatch.setattr("app.mcp_client.coros_client.subprocess.run", lambda *a, **k: Res)
    client = CorosMCPClient()
    records = client.fetch_workouts()
    assert len(records) == 1
    assert records[0]["date"].startswith("2026-09-29")
    assert records[0]["distance_m"] == 8400.0


def test_hrv_and_resting_hr_parsers():
    from app.mcp_client.coros_client import CorosMCPClient
    c = CorosMCPClient()
    hrv = c._parse_hrv("HRV Assessment\n\n2026-09-29:\n  HRV Avg: 76 ms — Normal\n  Baseline: 85 ms\n\nSleep HRV Time Series\n2026-09-29:\n  hrv=5 ms")
    assert hrv == {"2026-09-29": {"hrv_score": 76.0, "rmssd_ms": 76.0}}
    assert c._parse_resting_hr("2026-09-29: 56 bpm\n2026-09-28: 54 bpm") == {"2026-09-29": 56, "2026-09-28": 54}


def test_legacy_targets_are_normalised_with_ranges():
    from app.engine.targets import normalize_target, describe_target
    d = describe_target("Easy / Zone 2 (<75% HRMax)")
    assert d["focus"] == "Heart Rate" and "bpm" in d["range"]
    assert describe_target("Tempo / Zone 4 (88-92% HRMax)")["focus"] == "Pace"
    assert normalize_target("Rest & Mobility") == "Rest & Mobility"
    new = "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"
    assert normalize_target(new) == new
    assert describe_target(new) == {"focus": "Heart Rate", "range": "130 – 145 bpm", "detail": "Zone 2 Easy, 6:00 – 6:30 /km"}


def test_plan_page_shows_focus_badge_and_range(temp_db, client):
    from app.engine.planner import TrainingPlanner
    save_user_profile({"race_distance_type": "Marathon", "race_date": "2027-04-18", "target_time_str": "3:45:00",
                       "weekly_hours_available": 8.0, "available_days": "Mon,Tue,Thu,Sat,Sun"}, db_path=temp_db)
    # HR zones only come from an observed max HR in COROS data (none is invented)
    conn = get_db_connection(temp_db)
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, max_hr)"
                 " VALUES ('hr1', '2026-09-01T07:00:00Z', 'Run', 'Run', 8000, 2900, 186)")
    conn.commit()
    conn.close()
    save_training_plan(TrainingPlanner(db_path=temp_db).generate_plan(), db_path=temp_db)
    html = client.get("/plan").data.decode("utf-8")
    assert "HEART RATE FOCUS" in html or "PACE FOCUS" in html
    assert "bpm" in html


def test_dashboard_has_loading_overlay_and_utc_sync_time(temp_db, client):
    conn = get_db_connection(temp_db)
    conn.execute("INSERT INTO sync_logs (sync_type, status, records_fetched, timestamp) VALUES ('FULL','SUCCESS',1,'2026-09-29 14:26:38')")
    conn.commit(); conn.close()
    html = client.get("/dashboard").data.decode("utf-8")
    assert 'id="syncOverlay"' in html
    assert 'data-utc="2026-09-29T14:26:38Z"' in html
