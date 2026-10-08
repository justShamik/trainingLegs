"""Discard Plan must leave no active plan, even when older plans exist (they must not resurface)."""
import sqlite3
from datetime import date

import pytest

from app.data.db import init_db, get_db_connection
from app.data.queries import (
    save_training_plan, get_active_training_plan, delete_active_training_plan,
    calculate_weekly_compliance, auto_match_activities_to_sessions,
)
from app.engine.planner import TrainingPlanner
from app.web.routes import create_app


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "discard.db")
    init_db(path)
    from app.data.queries import save_user_profile
    save_user_profile({"race_distance_type": "Marathon", "race_date": "2027-04-18", "target_time_str": "3:45:00",
                       "weekly_hours_available": 8.0, "available_days": "Mon,Tue,Thu,Sat,Sun",
                       "injury_history": "None", "current_niggles": "None"}, db_path=path)
    return path


def _save_plans(db, n):
    ids = []
    for _ in range(n):
        ids.append(save_training_plan(TrainingPlanner(db_path=db).generate_plan(), db_path=db))
    return ids


def _statuses(db):
    conn = get_db_connection(db)
    rows = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM training_plans")}
    conn.close()
    return rows


def test_new_plan_supersedes_previous(db):
    first, second = _save_plans(db, 2)
    assert get_active_training_plan(db_path=db)["id"] == second
    assert _statuses(db) == {first: "superseded", second: "active"}


def test_discard_with_older_plans_leaves_no_active_plan(db):
    _save_plans(db, 3)
    assert delete_active_training_plan(db_path=db) is True
    assert get_active_training_plan(db_path=db) is None
    assert calculate_weekly_compliance(db_path=db)["total_sessions"] == 0
    assert auto_match_activities_to_sessions(db_path=db) == 0
    # history is kept, nothing comes back
    assert sorted(_statuses(db).values()) == ["discarded", "superseded", "superseded"]
    assert delete_active_training_plan(db_path=db) is False


def test_generate_after_discard_becomes_active(db):
    _save_plans(db, 2)
    delete_active_training_plan(db_path=db)
    new_id = _save_plans(db, 1)[0]
    assert get_active_training_plan(db_path=db)["id"] == new_id


def test_discard_route_and_reload_show_empty_state(db):
    _save_plans(db, 2)
    client = create_app(db_path=db).test_client()
    resp = client.post("/plan/discard", follow_redirects=True)
    assert b"No Active Training Plan Generated" in resp.data
    again = client.get("/plan")
    assert b"No Active Training Plan Generated" in again.data
    assert b"Discard Plan" not in again.data


def test_migration_keeps_only_newest_legacy_plan_active(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE training_plans (id TEXT PRIMARY KEY, version INTEGER, goal_distance TEXT,
                    race_date TEXT, total_volume_km REAL, methodology_name TEXT, methodology_rationale TEXT,
                    is_deload INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    for pid, ts in (("old", "2026-09-01 10:00:00"), ("mid", "2026-10-08 17:20:17"), ("new", "2026-10-08 17:26:09")):
        conn.execute("INSERT INTO training_plans (id, total_volume_km, created_at) VALUES (?, 0, ?)", (pid, ts))
    conn.commit()
    conn.close()

    init_db(path)
    assert _statuses(path) == {"old": "superseded", "mid": "superseded", "new": "active"}
    assert delete_active_training_plan(db_path=path) is True
    assert get_active_training_plan(db_path=path) is None


def test_activity_matched_to_discarded_plan_can_match_new_plan(db):
    today = date(2026, 9, 30)
    old_id = save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=today), db_path=db)
    target = next(s for s in get_active_training_plan(db_path=db)["sessions"]
                  if s.get("distance_km") and s["session_date"] <= "2026-09-29")
    conn = get_db_connection(db)
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr)"
                 " VALUES ('act_x', ?, 'Run', 'Run', ?, 3400, 333, 142)",
                 (target["session_date"] + "T07:00:00Z", target["distance_km"] * 1000.0))
    conn.commit()
    conn.close()
    assert auto_match_activities_to_sessions(plan_id=old_id, db_path=db, today=today) >= 1

    delete_active_training_plan(db_path=db)
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=today), db_path=db)
    assert auto_match_activities_to_sessions(db_path=db, today=today) >= 1
