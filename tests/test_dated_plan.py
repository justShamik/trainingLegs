"""Sprint 9: dated 5-week plan (current week + next 4) - model, planner, guardrails, page, auto-match."""
import sqlite3
from datetime import date, timedelta

import pytest

from app.data.db import init_db, get_db_connection
from app.data.queries import (
    save_user_profile, save_training_plan, get_active_training_plan,
    auto_match_activities_to_sessions, calculate_weekly_compliance,
)
from app.engine.guardrails import validate_multiweek_plan, weekly_volumes
from app.engine.planner import TrainingPlanner
from app.engine.targets import describe_target
from app.web.routes import create_app

TODAY = date(2026, 9, 30)          # Wednesday
MONDAY = date(2026, 9, 28)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "dated_plan.db")
    init_db(path)
    return path


def _profile(db, **kw):
    data = {"race_distance_type": "Marathon", "race_date": "2027-03-01", "target_time_str": "3:45:00",
            "weekly_hours_available": 8.0, "available_days": "Mon,Tue,Thu,Sat,Sun",
            "injury_history": "None", "current_niggles": "None"}
    data.update(kw)
    save_user_profile(data, db_path=db)


def test_five_weeks_contiguous_dates_from_monday_of_current_week(db):
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    assert plan["start_date"] == MONDAY.isoformat()
    assert plan["end_date"] == (MONDAY + timedelta(days=34)).isoformat()
    assert plan["total_weeks"] == 5
    sessions = plan["sessions"]
    assert len(sessions) == 35
    dates = [date.fromisoformat(s["session_date"]) for s in sessions]
    assert dates == [MONDAY + timedelta(days=i) for i in range(35)]
    assert dates[0].weekday() == 0
    assert [s["week_number"] for s in sessions] == [w for w in range(1, 6) for _ in range(7)]
    for s in sessions:
        assert s["day_of_week"] == date.fromisoformat(s["session_date"]).strftime("%a")
        if s["session_type"] != "Rest":
            assert ("Heart Rate Focus:" in s["target_pace_or_hr"]) or ("Pace Focus:" in s["target_pace_or_hr"])
            assert describe_target(s["target_pace_or_hr"])["range"]


def test_periodisation_and_guardrails_hold_across_weeks(db):
    for dist in ("10K", "Marathon", "50K Ultra"):
        for days in ("Mon,Tue,Thu,Sat,Sun", "Mon,Tue,Wed,Thu,Fri,Sat,Sun", "Tue,Thu,Sat", "Mon,Wed,Fri,Sun"):
            _profile(db, race_distance_type=dist, available_days=days)
            plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
            ok, violations = validate_multiweek_plan(plan, 30.0)
            assert ok, (dist, days, violations)
            assert "Guardrail warning" not in plan["methodology_rationale"]
            vols = list(weekly_volumes(plan["sessions"]).values())
            assert len(vols) == 5
            # 3:1 pattern: build, build, build, deload, build
            assert vols[1] > vols[0] and vols[2] > vols[1] and vols[3] < vols[2] and vols[4] > vols[3]
            for prev, cur in zip(vols, vols[1:]):
                assert cur <= prev * 1.10 + 0.1


def test_available_days_and_niggles_respected(db):
    _profile(db, available_days="Tue,Thu,Sat")
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    runs = {s["day_of_week"] for s in plan["sessions"] if s["session_type"] != "Rest"}
    assert runs == {"Tue", "Thu", "Sat"}

    _profile(db, current_niggles="left calf")
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    assert not any(s["session_type"] == "Threshold" for s in plan["sessions"])
    assert "calf" in plan["methodology_rationale"]


def test_deload_request_restarts_cycle_and_ultra_routing(db):
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(is_deload=True, today=TODAY)
    vols = list(weekly_volumes(plan["sessions"]).values())
    assert plan["is_deload"] is True
    assert vols[0] < vols[1]                      # deload then rebuild
    assert validate_multiweek_plan(plan, 30.0)[0]
    _profile(db, race_distance_type="50K Ultra")
    ultra = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    assert "Uphill Athlete" in ultra["methodology_name"]
    assert any(s["session_type"] == "Vert/Time-on-Feet" for s in ultra["sessions"])


def test_race_inside_window_tapers(db):
    race = MONDAY + timedelta(days=24)            # Thursday of week 4
    _profile(db, race_date=race.isoformat())
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    vols = list(weekly_volumes(plan["sessions"]).values())
    assert vols[3] < vols[2] * 0.6                # race week halved
    assert vols[2] < vols[1]                      # week before race tapered
    assert validate_multiweek_plan(plan, 30.0)[0]


def test_save_and_load_dated_plan_with_deterministic_ids(db):
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    pid = save_training_plan(plan, db_path=db)
    loaded = get_active_training_plan(db_path=db)
    assert loaded["id"] == pid
    assert (loaded["start_date"], loaded["end_date"], loaded["total_weeks"]) == (plan["start_date"], plan["end_date"], 5)
    assert [s["id"] for s in loaded["sessions"]] == [f"{pid}_sess_{i}" for i in range(35)]
    assert len({s["id"] for s in loaded["sessions"]}) == 35
    assert loaded["sessions"][0]["session_date"] == MONDAY.isoformat()
    assert loaded["sessions"][34]["week_number"] == 5


def test_legacy_single_week_plan_is_backfilled(tmp_path):
    path = str(tmp_path / "legacy.db")
    init_db(path)
    conn = get_db_connection(path)
    conn.execute("INSERT INTO training_plans (id, goal_distance, total_volume_km, methodology_name, methodology_rationale, created_at)"
                 " VALUES ('old', 'Marathon', 40, 'M', 'R', '2026-09-30 10:00:00')")
    for i, d in enumerate(["Mon", "Wed", "Sat"]):
        conn.execute("INSERT INTO plan_sessions (id, plan_id, day_of_week, session_type, distance_km, stated_purpose)"
                     " VALUES (?, 'old', ?, 'Easy Aerobic', 8, 'x')", (f"old_sess_{i}", d))
    conn.commit()
    conn.close()
    init_db(path)   # migration is idempotent
    plan = get_active_training_plan(db_path=path)
    assert plan["start_date"] == "2026-09-28" and plan["end_date"] == "2026-10-04" and plan["total_weeks"] == 1
    assert [s["session_date"] for s in plan["sessions"]] == ["2026-09-28", "2026-09-30", "2026-10-03"]
    assert all(s["week_number"] == 1 for s in plan["sessions"])
    comp = calculate_weekly_compliance(db_path=path, today=TODAY)
    assert comp["total_sessions"] == 3


def _insert_run(db, act_id, day, km):
    conn = get_db_connection(db)
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr)"
                 " VALUES (?, ?, 'Run', 'Run', ?, 3000, 330, 140)", (act_id, day + "T07:00:00Z", km * 1000.0))
    conn.commit()
    conn.close()


def test_auto_match_prefers_same_date_then_adjacent_and_skips_future(db):
    _profile(db, available_days="Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    save_training_plan(plan, db_path=db)
    sessions = get_active_training_plan(db_path=db)["sessions"]
    past_runs = [s for s in sessions if s["distance_km"] and s["session_date"] <= TODAY.isoformat()]
    future_run = next(s for s in sessions if s["distance_km"] and s["session_date"] > TODAY.isoformat())
    a, b = past_runs[0], past_runs[1]
    # Activity A is the exact date of session a; a same-distance activity on a different day must not steal it
    _insert_run(db, "act_a", a["session_date"], a["distance_km"])
    _insert_run(db, "act_b", b["session_date"], b["distance_km"])
    # Activity on a FUTURE session date must never match
    future_day = (date.fromisoformat(future_run["session_date"])).isoformat()
    _insert_run(db, "act_future", future_day, future_run["distance_km"])

    matched = auto_match_activities_to_sessions(db_path=db, today=TODAY)
    assert matched >= 2
    after = {s["id"]: s for s in get_active_training_plan(db_path=db)["sessions"]}
    assert after[a["id"]]["matched_activity_id"] == "act_a"
    assert after[b["id"]]["matched_activity_id"] == "act_b"
    assert after[future_run["id"]]["status"] == "Pending"
    assert after[future_run["id"]]["matched_activity_id"] is None


def test_auto_match_adjacent_day_fallback(db):
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    save_training_plan(plan, db_path=db)
    sessions = get_active_training_plan(db_path=db)["sessions"]
    by_date = {s["session_date"]: s for s in sessions}
    # a run whose following day is a rest day, so the off-by-one activity has no same-date session to claim it
    target = next(s for s in sessions if s["distance_km"] and s["session_date"] < TODAY.isoformat()
                  and by_date[(date.fromisoformat(s["session_date"]) + timedelta(days=1)).isoformat()]["session_type"] == "Rest")
    off_day = (date.fromisoformat(target["session_date"]) + timedelta(days=1)).isoformat()
    _insert_run(db, "act_off", off_day, target["distance_km"])
    auto_match_activities_to_sessions(db_path=db, today=TODAY)
    after = {s["id"]: s for s in get_active_training_plan(db_path=db)["sessions"]}
    assert after[target["id"]]["matched_activity_id"] == "act_off"


def test_compliance_is_current_week_with_whole_plan_keys(db):
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    save_training_plan(plan, db_path=db)
    comp = calculate_weekly_compliance(db_path=db, today=TODAY)
    wk1 = weekly_volumes(plan["sessions"])[1]
    assert comp["week_number"] == 1 and comp["prescribed_total_km"] == wk1
    assert comp["plan_prescribed_total_km"] == round(sum(weekly_volumes(plan["sessions"]).values()), 1)
    later = calculate_weekly_compliance(db_path=db, today=TODAY + timedelta(days=14))
    assert later["week_number"] == 3 and later["prescribed_total_km"] == weekly_volumes(plan["sessions"])[3]


@pytest.fixture
def client(db):
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client()


def test_plan_page_shows_date_range_weeks_and_dates(db, client):
    _profile(db)
    today = date.today()
    plan = TrainingPlanner(db_path=db).generate_plan(today=today)
    save_training_plan(plan, db_path=db)
    html = client.get("/plan").data.decode("utf-8")
    start = date.fromisoformat(plan["start_date"])
    end = date.fromisoformat(plan["end_date"])
    assert f"Plan period: {start.strftime('%a')} {start.day} {start.strftime('%b %Y')} – {end.strftime('%a')} {end.day} {end.strftime('%b %Y')}" in html
    assert "5 weeks" in html and "current week + next 4" in html
    assert "Week 1 (current)" in html and "Week 5 -" in html
    assert "% vs previous week" in html
    assert f"{today.strftime('%a')} {today.day} {today.strftime('%b')}" in html   # today's session card date
    assert "TODAY" in html
    assert "This plan has ended" not in html


def test_plan_page_ended_plan_shows_regenerate_notice(db, client):
    _profile(db)
    old_today = date.today() - timedelta(days=60)
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=old_today), db_path=db)
    html = client.get("/plan").data.decode("utf-8")
    assert "This plan has ended" in html
    assert "Generate New 5-Week Plan" in html


def test_plan_generate_route_creates_five_week_plan(db, client):
    _profile(db)
    client.post("/plan/generate", data={"is_deload": "0"})
    plan = get_active_training_plan(db_path=db)
    assert plan["total_weeks"] == 5 and len(plan["sessions"]) == 35
    today = date.today()
    assert plan["start_date"] == (today - timedelta(days=today.weekday())).isoformat()
