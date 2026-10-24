"""Auto-match of shortened runs, S&C generated with the plan, plan History tab, Block Summary removal, nav label."""
import re
from datetime import date, timedelta

import pytest

from app.data.db import init_db, get_db_connection
from app.data.history import get_training_history
from app.data.queries import (auto_match_activities_to_sessions, get_active_training_plan, get_plan_strength_sessions,
                              save_training_plan, save_user_profile, delete_active_training_plan)
from app.engine.plan_bundle import create_training_plan
from app.engine.planner import TrainingPlanner
from app.engine.strength import SC_HARD

MONDAY = date(2026, 10, 19)


def _profile(db, race_date="2027-03-14", days="Mon,Tue,Thu,Sat,Sun"):
    save_user_profile({"race_distance_type": "Marathon", "race_date": race_date, "target_time_str": "3:30:00",
                       "weekly_hours_available": 7.0, "available_days": days, "injury_history": "None",
                       "current_niggles": "None"}, db_path=db)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "h.db")
    init_db(path)
    _profile(path)
    return path


def _run(db, act_id, day, km, hour="08:00:00Z"):
    conn = get_db_connection(db)
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr)"
                 " VALUES (?, ?, 'Outdoor Run', 'Run', ?, ?, 360, 150)", (act_id, f"{day}T{hour}", km * 1000, km * 360))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------------- auto-match
def _long_run(db):
    return next(s for s in get_active_training_plan(db_path=db)["sessions"] if s["session_type"] == "Long Run")


def test_short_run_on_long_run_day_counts_as_modified(db):
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=MONDAY), db_path=db)
    lr = _long_run(db)
    _run(db, "short", lr["session_date"], 4.02)               # the 24 Oct case: 4.0 km vs a ~10 km long run
    today = date.fromisoformat(lr["session_date"])
    assert auto_match_activities_to_sessions(db_path=db, today=today) >= 1
    after = next(s for s in get_active_training_plan(db_path=db)["sessions"] if s["id"] == lr["id"])
    assert after["matched_activity_id"] == "short" and after["status"] == "Modified"
    assert after["actual_distance_km"] == 4.02 and after["adherence_rating"]


def test_full_run_is_completed_and_adjacent_day_still_needs_similar_distance(db):
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=MONDAY), db_path=db)
    lr = _long_run(db)
    _run(db, "full", lr["session_date"], lr["distance_km"] * 0.9)
    nxt = (date.fromisoformat(lr["session_date"]) + timedelta(days=2)).isoformat()
    sessions = {s["session_date"]: s for s in get_active_training_plan(db_path=db)["sessions"]}
    auto_match_activities_to_sessions(db_path=db, today=date.fromisoformat(nxt))
    after = {s["id"]: s for s in get_active_training_plan(db_path=db)["sessions"]}
    assert after[lr["id"]]["status"] == "Completed"
    # a tiny run the day after a REST day must not be pulled onto a neighbouring session
    rest = next((d for d, s in sessions.items() if s["session_type"] == "Rest" and d > lr["session_date"]), None)
    if rest:
        _run(db, "tiny", rest, 0.5)
        auto_match_activities_to_sessions(db_path=db, today=date.fromisoformat(rest) + timedelta(days=1))
        assert all(s["matched_activity_id"] != "tiny" for s in get_active_training_plan(db_path=db)["sessions"])


# ------------------------------------------------------------------------------------------- S&C
def _sc(db, today=MONDAY):
    pid = create_training_plan(db_path=db, today=today)
    plan = get_active_training_plan(db_path=db)
    return plan, get_plan_strength_sessions(pid, db_path=db)


def test_new_plan_schedules_sc_with_rules(db):
    plan, sc = _sc(db)
    assert plan and sc and all(w["plan_id"] == plan["id"] for w in sc)
    by_date = {s["session_date"]: s for s in plan["sessions"]}
    for w in sc:
        d = date.fromisoformat(w["session_date"])
        assert w["session_date"] >= MONDAY.isoformat()
        nxt = by_date.get((d + timedelta(days=1)).isoformat())
        assert not nxt or nxt["session_type"] not in SC_HARD            # never the day before a hard run
        assert by_date[w["session_date"]]["session_type"] != "Long Run"
        assert w["exercises"] and w["phase"] in ("Base", "Build", "Peak", "Taper")
    per_week = {}
    for w in sc:
        per_week.setdefault(w["week_number"], []).append(date.fromisoformat(w["session_date"]))
    kinds = {wk["week_number"]: wk for wk in (plan.get("decisions") or {}).get("weeks", [])} or None
    for wn, days in per_week.items():
        assert len(days) <= 2
        assert all(abs((a - b).days) >= 2 for a in days for b in days if a != b)
        if kinds and kinds[wn]["kind"] == "deload":
            assert len(days) == 1


def test_mid_week_plan_skips_past_days(db):
    thursday = MONDAY + timedelta(days=3)
    _, sc = _sc(db, today=thursday)
    assert all(w["session_date"] >= thursday.isoformat() for w in sc)


def test_no_sc_near_or_in_race_week(tmp_path):
    db = str(tmp_path / "race.db")
    init_db(db)
    race = MONDAY + timedelta(days=7 * 3 + 6)                         # Sunday of week 4
    _profile(db, race_date=race.isoformat())
    _, sc = _sc(db)
    assert sc
    assert all(not (0 <= (race - date.fromisoformat(w["session_date"])).days <= 4) for w in sc)


def test_regenerated_plan_has_its_own_sc_and_old_one_is_hidden(db):
    _, first = _sc(db)
    plan, second = _sc(db)
    assert second and {w["plan_id"] for w in second} == {plan["id"]}
    assert not {w["db_id"] for w in first} & {w["db_id"] for w in second}


# --------------------------------------------------------------------------------------- history
def test_history_weeks_actual_vs_plan_of_record(db):
    # older plan (superseded) has nothing logged; the newer one (later discarded) has a logged run -> it is the record
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=MONDAY), db_path=db)
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=MONDAY), db_path=db)
    lr = _long_run(db)
    _run(db, "r1", lr["session_date"], 4.0)
    auto_match_activities_to_sessions(db_path=db, today=date.fromisoformat(lr["session_date"]))
    record_id = get_active_training_plan(db_path=db)["id"]
    delete_active_training_plan(db_path=db)
    today = MONDAY + timedelta(days=6)
    h = get_training_history(db_path=db, today=today, weeks=12)
    assert len(h["weeks"]) == 12 and h["weeks"][0]["start"] == MONDAY.isoformat() and h["weeks"][0]["is_current"]
    wk = h["weeks"][0]
    assert wk["plan_id"] == record_id and wk["actual_km"] == 4.0 and wk["runs"] == 1
    assert wk["long_run"]["actual_km"] == 4.0 and wk["compliance"]["modified_sessions"] == 1
    assert [p["status"] for p in h["plans"]] == ["discarded", "superseded"]
    assert h["weeks"][1]["planned_km"] is None and h["weeks"][1]["compliance"] is None
    assert len(h["chart"]["labels"]) == 12 and h["chart"]["actual"][-1] == 4.0


def test_history_counts_unplanned_runs_and_only_past_sessions(db):
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=MONDAY), db_path=db)
    _run(db, "old", (MONDAY - timedelta(days=10)).isoformat(), 12.0)
    h = get_training_history(db_path=db, today=MONDAY, weeks=4)
    prev = next(w for w in h["weeks"] if w["start"] == (MONDAY - timedelta(days=14)).isoformat())
    assert prev["actual_km"] == 12.0 and prev["planned_km"] is None
    this = h["weeks"][0]
    assert this["compliance"]["total_sessions"] <= 1                 # only Monday has happened


# ----------------------------------------------------------------------------------------- routes
@pytest.fixture
def client(db):
    from app.web.routes import create_app
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    app.config["TODAY"] = MONDAY
    return app.test_client()


def test_generate_creates_running_and_sc_and_plan_shows_chips(client, db):
    client.post("/plan/generate", data={"is_deload": "0"})
    plan = get_active_training_plan(db_path=db)
    sc = get_plan_strength_sessions(plan["id"], db_path=db)
    assert sc
    html = client.get("/plan").get_data(as_text=True)
    assert html.count('class="chip chip--lavender chip--raw sc-chip"') == len(sc)
    assert f'/strength?session={sc[0]["db_id"]}' in html


def test_plan_tabs_and_history_tab(client):
    client.post("/plan/generate", data={"is_deload": "0"})
    html = client.get("/plan").get_data(as_text=True)
    assert 'id="tab-history"' in html and 'id="historyWeeks"' not in html
    hist = client.get("/plan?tab=history").get_data(as_text=True)
    assert 'id="historyWeeks"' in hist and 'id="historyPlans"' in hist and "Training weeks" in hist
    assert 'id="today-session"' not in hist


def test_block_summary_removed(client):
    r = client.get("/block-summary")
    assert r.status_code == 301 and r.headers["Location"].endswith("/plan?tab=history")
    html = client.get("/plan").get_data(as_text=True)
    links = re.findall(r'<a href="([^"]+)" class="nav-link[^"]*">([^<]+)</a>', html)
    labels = [l for _, l in links]
    assert "Block Summary" not in labels and "S&amp;C" in labels and "Strength & S&C" not in html
    assert ("/strength", "S&amp;C") in links


def test_strength_page_shows_schedule_and_next_session(client, db):
    client.post("/plan/generate", data={"is_deload": "0"})
    plan = get_active_training_plan(db_path=db)
    sc = get_plan_strength_sessions(plan["id"], db_path=db)
    html = client.get("/strength").get_data(as_text=True)
    assert 'id="scSchedule"' in html and html.count('data-sc="') == len(sc)
    assert "Scheduled " in html and html.count("is-current") >= 1
    r = client.post("/strength/update", data={"workout_id": sc[0]["db_id"], "status": "Completed"})
    assert f"session={sc[0]['db_id']}" in r.headers["Location"]
    shown = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "✓ COMPLETED" in shown
    if len(sc) > 1:
        assert f'data-sc="{sc[1]["db_id"]}" class="is-current"' in client.get("/strength").get_data(as_text=True)
    client.post("/strength/generate", data={"phase": "Peak"})
    assert "One-off session" in client.get("/strength").get_data(as_text=True)
