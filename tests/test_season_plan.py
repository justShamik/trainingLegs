"""Season plans: length to race day, tune-up races, current fitness and goal check, pace progression, deload return,
set-up checklist, preview/create/refresh flow, Goal Profile tune-up races."""
from datetime import date, timedelta

import pytest

from app.data.db import init_db, get_db_connection
from app.data.queries import (get_active_training_plan, get_plan_strength_sessions, get_tune_up_races,
                              get_user_profile, save_tune_up_race, save_user_profile)
from app.engine.guardrails import HARD_SESSION_TYPES, validate_evidence_rules
from app.engine.plan_bundle import create_training_plan, plan_status, preview_season_plan, refresh_plan
from app.engine.plan_view import build_plan_view
from app.engine.planner import (TrainingPlanner, estimate_current_fitness, goal_check, suggest_tune_up_mode,
                                tune_up_recovery_days, vdot_from_performance)
from app.web.season_routes import setup_checklist

MONDAY = date(2026, 10, 26)
RACE = date(2027, 2, 28)          # Sunday


def _profile(db, **kw):
    p = {"race_distance_type": "Marathon", "race_date": RACE.isoformat(), "target_time_str": "3:30:00",
         "weekly_hours_available": 8.0, "available_days": "Mon,Tue,Thu,Sat,Sun", "injury_history": "None",
         "current_niggles": "None"}
    p.update(kw)
    save_user_profile(p, db_path=db)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "season.db")
    init_db(path)
    _profile(path)
    return path


def _season(db, today=MONDAY, **kw):
    return TrainingPlanner(db_path=db).generate_plan(today=today, season=True, **kw)


def _runs(db, days_ago_km_min, today=MONDAY):
    conn = get_db_connection(db)
    for i, (ago, km, minutes) in enumerate(days_ago_km_min):
        d = (today - timedelta(days=ago)).isoformat()
        conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s) VALUES (?,?,?,?,?,?)",
                     (f"r{i}", d + "T07:00:00Z", "Run", "Run", km * 1000, minutes * 60))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------------------- length
def test_season_runs_to_race_week_with_all_phases(db):
    plan = _season(db)
    assert plan["plan_kind"] == "season" and plan["total_weeks"] == 18
    assert plan["end_date"] == RACE.isoformat()
    phases = [w["phase"] for w in plan["week_summaries"]]
    assert phases[0] == "base" and phases[-1] == "race" and {"build", "peak", "taper"} <= set(phases)
    race = [s for s in plan["sessions"] if s["session_type"] == "Race"]
    assert len(race) == 1 and race[0]["session_date"] == RACE.isoformat()
    assert plan["runway"]["verdict"] == "ok"
    assert "Guardrail warning" not in plan["methodology_rationale"]


def test_block_plan_still_five_weeks(db):
    plan = TrainingPlanner(db_path=db).generate_plan(today=MONDAY)
    assert plan["total_weeks"] == 5 and plan["plan_kind"] == "block"


@pytest.mark.parametrize("weeks_out,verdict", [(7, "short"), (13, "tight"), (17, "ok"), (25, "long")])
def test_runway_verdicts(db, weeks_out, verdict):
    _profile(db, race_date=(MONDAY + timedelta(weeks=weeks_out, days=6)).isoformat())
    plan = _season(db)
    assert plan["runway"]["verdict"] == verdict and plan["total_weeks"] == weeks_out + 1


def test_season_capped_at_30_weeks(db):
    _profile(db, race_date=(MONDAY + timedelta(weeks=40)).isoformat())
    assert _season(db)["total_weeks"] == 30


# --------------------------------------------------------------------------------- volume progression
def test_volume_returns_after_deload_and_builds_over_the_season(db):
    plan = _season(db)
    ws = plan["week_summaries"]
    vols = {w["week_number"]: w["training_km"] for w in ws}
    for i, w in enumerate(ws[1:-1], start=1):
        prev = ws[i - 1]
        if prev["kind"] == "deload" and w["kind"] == "build":
            before = ws[i - 2]["training_km"]
            assert w["training_km"] >= before                        # back above the last loading week
    peak = max(vols[w["week_number"]] for w in ws if w["phase"] in ("build", "peak"))
    assert peak > 1.5 * vols[1]


def test_ten_percent_rule_uses_last_loading_week():
    from app.engine.guardrails import validate_multiweek_plan
    def week(n, km):
        return {"week_number": n, "session_type": "Easy Aerobic", "distance_km": km,
                "session_date": (MONDAY + timedelta(weeks=n - 1)).isoformat(), "day_of_week": "Mon"}
    plan = {"sessions": [week(1, 40), week(2, 32), week(3, 43)]}       # deload then +7.5% over week 1
    assert validate_multiweek_plan(plan, 40.0, max_consecutive=7)[0]
    plan = {"sessions": [week(1, 40), week(2, 32), week(3, 46)]}       # +15% over week 1 -> violation
    assert not validate_multiweek_plan(plan, 40.0, max_consecutive=7)[0]


# --------------------------------------------------------------------------------------- tune-up races
def test_tune_up_mode_and_recovery_rules():
    assert suggest_tune_up_mode(21.1, 21, 42.2)[0] == "race"
    assert suggest_tune_up_mode(21.1, 14, 42.2)[0] == "effort"
    assert suggest_tune_up_mode(42.2, 60, 42.2)[0] == "effort"
    assert suggest_tune_up_mode(10.0, 70, 21.1)[0] == "race"
    assert tune_up_recovery_days(21.1, "race") == 5 and tune_up_recovery_days(21.1, "effort") == 3
    assert tune_up_recovery_days(5.0, "race") == 2


def test_tune_up_race_is_scheduled_with_mini_taper_and_recovery(db):
    save_tune_up_race({"race_date": "2027-02-07", "distance": "Half Marathon", "name": "Half"}, db_path=db)
    plan = _season(db)
    by_date = {s["session_date"]: s for s in plan["sessions"]}
    tu = by_date["2027-02-07"]
    assert tu["session_type"] == "Tune-up Race" and tu["distance_km"] == 21.1
    assert by_date["2027-02-06"]["session_type"] == "Rest"
    info = plan["tune_ups"][0]
    assert info["mode"] == "race" and info["recovery_days"] == 5
    for off in list(range(-2, 0)) + list(range(1, 6)):
        d = (date(2027, 2, 7) + timedelta(days=off)).isoformat()
        assert by_date[d]["session_type"] not in HARD_SESSION_TYPES - {"Race"}, d
    week = next(w for w in plan["week_summaries"] if w["start_date"] == "2027-02-01")
    assert week["kind"] == "tuneup"
    assert any(i["topic"] == "Tune-up races" for i in plan["decisions"]["items"])
    assert "Guardrail warning" not in plan["methodology_rationale"]


def test_tune_up_user_mode_and_warnings(db):
    save_tune_up_race({"race_date": "2027-02-21", "distance": "10K", "mode": "race"}, db_path=db)    # in the taper
    save_tune_up_race({"race_date": "2027-02-16", "distance": "5K"}, db_path=db)                      # 5 days earlier
    plan = _season(db)
    t10 = next(t for t in plan["tune_ups"] if t["distance"] == "10K")
    assert t10["mode"] == "race" and t10["mode_reason"] == "set in your Goal Profile"
    assert any("taper" in w for w in t10["warnings"]) and any("days after" in w for w in t10["warnings"])


def test_tune_ups_after_goal_race_or_in_past_ignored(db):
    save_tune_up_race({"race_date": "2027-03-14", "distance": "10K"}, db_path=db)
    save_tune_up_race({"race_date": "2026-10-01", "distance": "10K"}, db_path=db)
    assert _season(db)["tune_ups"] == []


# ----------------------------------------------------------------------------- fitness, goal check, paces
def test_fitness_from_best_run_then_tune_up_result(db):
    assert estimate_current_fitness(db, MONDAY) is None
    _runs(db, [(3, 10.0, 60.0), (5, 8.0, 36.0), (40, 21.1, 95.0), (70, 10.0, 40.0)])
    f = estimate_current_fitness(db, MONDAY)
    assert f["source"] == "best recent run" and f["vdot"] == round(vdot_from_performance(21100, 95.0), 1)


def test_goal_check_verdicts():
    f = {"vdot": 40.0, "source": "best recent run"}
    assert goal_check(41.0, f, 12, "Marathon", 42.195)["verdict"] == "realistic"
    assert goal_check(43.5, f, 12, "Marathon", 42.195)["verdict"] == "ambitious"
    assert goal_check(50.0, f, 12, "Marathon", 42.195)["verdict"] == "unlikely"
    assert goal_check(45.0, None, 12, "Marathon", 42.195) is None


def test_paces_progress_from_current_to_goal(db):
    _runs(db, [(5, 10.0, 56.0)])                                  # ~VDOT 36 vs goal 3:30 (~44.6)
    plan = _season(db)
    assert plan["goal_check"]["verdict"] in ("ambitious", "unlikely")
    thr = [s for s in plan["sessions"] if s["session_type"] == "Threshold"]
    first, last = thr[0]["target_pace_or_hr"], thr[-1]["target_pace_or_hr"]
    assert first != last
    topics = [i["topic"] for i in plan["decisions"]["items"]]
    assert "Goal check" in topics and "Pace progression" in topics


# --------------------------------------------------------------------------------- create / refresh
def test_preview_overrides_do_not_touch_profile(db):
    plan = preview_season_plan(db_path=db, today=MONDAY, overrides={"target_time_str": "3:15:00"})
    assert plan["goal"]["target_time"] == "3:15:00"
    assert get_user_profile(db_path=db)["target_time_str"] == "3:30:00"
    assert get_active_training_plan(db_path=db) is None


def test_create_season_plan_with_sc_and_status(db):
    create_training_plan(db_path=db, today=MONDAY, season=True)
    plan = get_active_training_plan(db_path=db)
    assert plan["plan_kind"] == "season" and plan["total_weeks"] == 18
    assert get_plan_strength_sessions(plan["id"], db_path=db)
    st = plan_status(plan, db_path=db, today=MONDAY)
    assert st["season"] and not st["profile_changed"] and not st["refresh_due"]
    assert plan_status(plan, db_path=db, today=MONDAY + timedelta(days=8))["refresh_due"]
    _profile(db, available_days="Mon,Wed,Fri,Sun")
    assert plan_status(plan, db_path=db, today=MONDAY)["profile_changed"] == ["available_days"]


def test_refresh_keeps_past_and_logged_sessions_and_week_numbers(db):
    create_training_plan(db_path=db, today=MONDAY, season=True)
    plan = get_active_training_plan(db_path=db)
    later = MONDAY + timedelta(days=9)                             # Wednesday of week 2
    conn = get_db_connection(db)
    conn.execute("UPDATE plan_sessions SET status = 'Completed', actual_distance_km = 9 WHERE plan_id = ? AND "
                 "session_date = ?", (plan["id"], (MONDAY + timedelta(days=1)).isoformat()))
    conn.execute("UPDATE plan_sessions SET status = 'Skipped' WHERE plan_id = ? AND session_date = ?",
                 (plan["id"], (later + timedelta(days=2)).isoformat()))        # a future day already decided
    conn.commit()
    conn.close()
    before = {s["session_date"]: s for s in plan["sessions"]}
    res = refresh_plan(db_path=db, today=later)
    after_plan = get_active_training_plan(db_path=db)
    after = {s["session_date"]: s for s in after_plan["sessions"]}
    assert after_plan["id"] == plan["id"] and res["added"] > 0
    assert set(after) == set(before)                               # one session per day, nothing lost
    assert after[(MONDAY + timedelta(days=1)).isoformat()]["status"] == "Completed"
    assert after[(later + timedelta(days=2)).isoformat()]["status"] == "Skipped"
    for d, s in after.items():
        assert s["week_number"] == before[d]["week_number"]
    assert after_plan["total_weeks"] == plan["total_weeks"]
    vm = build_plan_view(after_plan, today=later)
    assert [p["key"] for p in vm["phases"]][-1] == "race"
    sc = get_plan_strength_sessions(plan["id"], db_path=db)
    assert len({w["session_date"] for w in sc}) == len(sc)        # no duplicate S&C days


def test_phase_grouping(db):
    create_training_plan(db_path=db, today=MONDAY, season=True)
    vm = build_plan_view(get_active_training_plan(db_path=db), today=MONDAY)
    keys = [p["key"] for p in vm["phases"]]
    assert keys[0] == "base" and keys[-1] == "race" and "taper" in keys
    assert sum(p["n_weeks"] for p in vm["phases"]) == vm["total_weeks"]
    assert vm["phases"][0]["is_current"] and not vm["phases"][-1]["is_current"]


# ------------------------------------------------------------------------------------- checklist
def test_setup_checklist(tmp_path):
    db = str(tmp_path / "c.db")
    init_db(db)
    c = setup_checklist(get_user_profile(db_path=db), [], MONDAY)
    assert not c["ready"] and [i["ok"] for i in c["items"]] == [False, False, False, True]
    _profile(db)
    c = setup_checklist(get_user_profile(db_path=db), [], MONDAY)
    assert c["ready"]
    _profile(db, race_date="2026-10-01")
    assert not setup_checklist(get_user_profile(db_path=db), [], MONDAY)["items"][0]["ok"]


# ----------------------------------------------------------------------------------------- routes
@pytest.fixture
def client(db):
    from app.web.routes import create_app
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    app.config["TODAY"] = MONDAY
    return app.test_client()


def test_plan_page_setup_then_preview_then_create(client, db):
    html = client.get("/plan").get_data(as_text=True)
    assert 'id="createPlanForm"' in html and "Generate Build Week" not in html
    prev = client.get("/plan/preview?distance=Marathon&target_time=3:20:00")
    body = prev.get_data(as_text=True)
    assert prev.status_code == 200 and "Season length" in body and body.count('data-phase="') >= 4
    assert get_active_training_plan(db_path=db) is None
    r = client.post("/plan/create", data={"distance": "Marathon", "target_time": "3:20:00"})
    assert r.headers["Location"].endswith("/plan?created=1")
    assert get_user_profile(db_path=db)["target_time_str"] == "3:20:00"
    html = client.get("/plan?created=1").get_data(as_text=True)
    assert 'id="planCreated"' in html and 'id="phaseTimeline"' in html and 'id="planBasis"' in html
    assert 'id="createPlanForm"' not in html and 'id="newPlanBtn"' in html
    assert 'id="createPlanForm"' in client.get("/plan?new=1").get_data(as_text=True)
    r = client.post("/plan/refresh")
    assert "refreshed=" in r.headers["Location"]


def test_preview_rejects_bad_target(client):
    r = client.get("/plan/preview?distance=Marathon&target_time=fast")
    assert r.status_code == 302 and "error=" in r.headers["Location"]


def test_incomplete_profile_shows_checklist(tmp_path):
    from app.web.routes import create_app
    db = str(tmp_path / "e.db")
    init_db(db)
    app = create_app(db_path=db)
    app.config["TODAY"] = MONDAY
    html = app.test_client().get("/plan").get_data(as_text=True)
    assert "Answer a few questions before we set up your plan" in html and 'id="completeProfileBtn"' in html
    assert 'href="/profile?next=/plan#availability"' in html


def test_profile_next_redirect_and_tune_up_crud(client, db):
    html = client.get("/profile?next=/plan").get_data(as_text=True)
    assert 'name="next" value="/plan"' in html and "Save and continue to plan" in html
    form = {k: v for k, v in get_user_profile(db_path=db).items() if k in (
        "race_distance_type", "race_date", "target_time_str", "weekly_hours_available", "available_days",
        "injury_history", "current_niggles")}
    r = client.post("/profile", data={**form, "next": "/plan"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/plan")
    r = client.post("/profile", data={**form, "next": "https://evil.example"})
    assert r.status_code == 302 and "evil" not in r.headers["Location"]
    ok = client.post("/profile/races", data={"tu_race_date": "2027-02-07", "tu_distance": "Half Marathon", "name": "H",
                                              "priority": "B", "mode": "auto", "tu_target_time": "1:39:00"})
    assert "race_saved=1" in ok.headers["Location"]
    for bad, msg in [({"tu_race_date": "2026-10-01", "tu_distance": "10K"}, "future"),
                     ({"tu_race_date": "2027-01-10", "tu_distance": "Ultra"}, "distance"),
                     ({"tu_race_date": "nope", "tu_distance": "10K"}, "date"),
                     ({"tu_race_date": "2027-01-10", "tu_distance": "10K", "tu_target_time": "quick"}, "Target")]:
        r = client.post("/profile/races", data=bad)
        assert "race_error" in r.headers["Location"] and msg.lower() in r.headers["Location"].lower()
    races = get_tune_up_races(db_path=db)
    assert len(races) == 1 and races[0]["target_time_str"] == "1:39:00"
    assert 'id="tuneUpTable"' in client.get("/profile").get_data(as_text=True)
    client.post(f"/profile/races/{races[0]['id']}/delete")
    assert get_tune_up_races(db_path=db) == []
