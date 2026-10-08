"""Session adjustments: swap for an alternative / missed + rebalance (app/engine/reschedule.py + routes)."""
import re
from datetime import date, timedelta

import pytest

from app.data.db import get_db_connection, init_db
from app.data.queries import (
    auto_match_activities_to_sessions, calculate_weekly_compliance, get_active_training_plan,
    save_training_plan, save_user_profile, update_session_status,
)
from app.engine import reschedule as rs
from app.engine.guardrails import HARD_SESSION_TYPES
from app.engine.planner import TrainingPlanner
from app.web.routes import create_app

MONDAY = date(2026, 9, 28)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ALL_DAYS = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "adjust.db")
    init_db(path)
    return path


def _profile(db, days="Mon,Tue,Thu,Sat,Sun"):
    save_user_profile({"race_distance_type": "Marathon", "race_date": "2027-03-01", "target_time_str": "3:45:00",
                       "weekly_hours_available": 8.0, "available_days": days, "injury_history": "None",
                       "current_niggles": "None"}, db_path=db)


def _session(stype, km):
    if stype == "Rest":
        return {"session_type": "Rest", "distance_km": 0.0, "duration_min": 0.0, "target_pace_or_hr": "Rest & Recovery",
                "stated_purpose": "Rest"}
    target = rs.EASY_TARGET if stype in ("Easy Aerobic", "Long Run") else "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)"
    return {"session_type": stype, "distance_km": float(km), "duration_min": float(round(km * 6)),
            "target_pace_or_hr": target, "stated_purpose": f"{stype} purpose"}


def _crafted_plan(db, week, weeks=2):
    """Save a plan whose every week follows `week` (7 (type, km) tuples, Mon..Sun), starting MONDAY."""
    sessions = []
    for w in range(weeks):
        for i, (stype, km) in enumerate(week):
            s = _session(stype, km)
            s.update(week_number=w + 1, day_of_week=DAYS[i], session_date=(MONDAY + timedelta(days=7 * w + i)).isoformat())
            sessions.append(s)
    plan_id = save_training_plan({"start_date": MONDAY.isoformat(), "total_weeks": weeks, "total_volume_km": 40.0,
                                  "sessions": sessions}, db_path=db)
    return plan_id, get_active_training_plan(db_path=db)


def _sid(plan, offset):
    return next(s["id"] for s in plan["sessions"] if s["session_date"] == (MONDAY + timedelta(days=offset)).isoformat())


def _changes(p):
    return {c["session_id"]: c for c in p["changes"]}


def _final(plan, proposal):
    """Plan sessions with the proposal applied (in memory)."""
    after = {c["session_id"]: c["after"] for c in proposal["changes"]}
    return [{**s, **after.get(s["id"], {})} for s in plan["sessions"]]


def _no_back_to_back_hard(sessions):
    eff = rs.effective_sessions(sessions)
    return all(not (a["session_type"] in HARD_SESSION_TYPES and b["session_type"] in HARD_SESSION_TYPES)
               for a, b in zip(eff, eff[1:]))


def _week_km(sessions, week=1):
    return round(sum(float(s.get("distance_km") or 0) for s in rs.effective_sessions(sessions)
                     if int(s.get("week_number") or 1) == week), 1)


BASE_WEEK = [("Rest", 0), ("Threshold", 8), ("Easy Aerobic", 8), ("Easy Aerobic", 8), ("Rest", 0),
             ("Long Run", 16), ("Easy Aerobic", 6)]


# ------------------------------------------------------------------ swap options
def test_swap_options_illness_steers_to_rest_or_very_easy(db):
    _, plan = _crafted_plan(db, BASE_WEEK)
    thr = next(s for s in plan["sessions"] if s["session_type"] == "Threshold")
    opts = rs.swap_options(thr, "illness")
    assert [o["key"] for o in opts] == ["rest", "very_easy"]
    assert opts[0]["recommended"]
    assert opts[1]["after"]["session_type"] == "Easy Aerobic" and opts[1]["after"]["duration_min"] <= 20
    assert all(o["after"]["session_type"] not in HARD_SESSION_TYPES for o in opts)


def test_swap_options_are_lower_load(db):
    _, plan = _crafted_plan(db, BASE_WEEK)
    for s in plan["sessions"][:7]:
        if s["session_type"] == "Rest":
            continue
        opts = rs.swap_options(s, "time")
        assert 2 <= len(opts) <= 4
        assert sum(o["recommended"] for o in opts) == 1
        assert {"xtrain", "rest"} <= {o["key"] for o in opts}
        for o in opts:
            a = o["after"]
            assert a["distance_km"] <= s["distance_km"]
            assert a["session_type"] in (s["session_type"], "Easy Aerobic", "Cross-Training", "Rest")
            assert a["session_type"] == s["session_type"] or a["session_type"] not in HARD_SESSION_TYPES
        if s["session_type"] == "Threshold":
            easy = next(o for o in opts if o["key"] == "easy")
            assert easy["after"]["duration_min"] == s["duration_min"]          # easy aerobic of similar time
        if s["session_type"] == "Long Run":
            assert next(o for o in opts if o["key"] == "short")["after"]["session_type"] == "Long Run"


def test_swap_only_from_today_in_current_week(db):
    _, plan = _crafted_plan(db, BASE_WEEK)
    today = MONDAY + timedelta(days=2)  # Wed
    with pytest.raises(rs.AdjustError):
        rs.propose_swap(plan, _sid(plan, 1), "easy", "time", today=today)       # yesterday
    with pytest.raises(rs.AdjustError):
        rs.propose_swap(plan, _sid(plan, 8), "easy", "time", today=today)       # next week
    assert rs.can_mark_missed(next(s for s in plan["sessions"] if s["id"] == _sid(plan, 1)), today)
    adj = rs.adjustable_sessions(plan, today)
    assert adj[_sid(plan, 1)] == {"swap": False, "missed": True}
    assert adj[_sid(plan, 2)] == {"swap": True, "missed": True}
    assert _sid(plan, 0) not in adj and _sid(plan, 8) not in adj              # rest day / next week


# ------------------------------------------------------------------ rebalancing rules
def test_missed_quality_moves_to_later_easy_day_only_if_spacing_allows(db):
    week = [("Rest", 0), ("Easy Aerobic", 6), ("Threshold", 8), ("Rest", 0), ("Easy Aerobic", 8),
            ("Long Run", 16), ("Easy Aerobic", 6)]
    _, plan = _crafted_plan(db, week)
    wed = _sid(plan, 2)
    # Thu is not an available day; Fri and Sun are next to the Sat long run -> nowhere safe: drop, don't cram
    p = rs.propose_missed(plan, wed, "time", today=MONDAY + timedelta(days=2), available_days="Mon,Tue,Wed,Fri,Sat,Sun")
    assert p["valid"]
    ch = _changes(p)
    assert ch[wed]["after"]["status"] == "Skipped"
    final = _final(plan, p)
    assert sum(1 for s in rs.effective_sessions(final)[:7] if s["session_type"] == "Threshold") == 0
    assert next(s for s in final if s["id"] == _sid(plan, 3))["session_type"] == "Rest"   # Thu stays rest
    assert any("dropped rather than crammed" in n for n in p["notes"])
    assert _no_back_to_back_hard(final)

    # With Thu available the session moves there (Thu Threshold, Fri easy, Sat long run)
    p = rs.propose_missed(plan, wed, "time", today=MONDAY + timedelta(days=2), available_days=ALL_DAYS)
    final = _final(plan, p)
    thu = next(s for s in final if s["id"] == _sid(plan, 3))
    assert thu["session_type"] == "Threshold" and thu["distance_km"] == 8.0
    assert _changes(p)[_sid(plan, 3)]["action"] == "Threshold moved here"
    assert _no_back_to_back_hard(final)
    assert p["valid"]


def test_missed_long_run_is_protected_by_moving_it(db):
    _, plan = _crafted_plan(db, BASE_WEEK)
    sat = _sid(plan, 5)
    p = rs.propose_missed(plan, sat, "travel", today=MONDAY + timedelta(days=5), available_days="Mon,Tue,Thu,Sat,Sun")
    final = _final(plan, p)
    sun = next(s for s in final if s["id"] == _sid(plan, 6))
    assert sun["session_type"] == "Long Run" and sun["distance_km"] == 16.0
    assert _no_back_to_back_hard(final)   # next Monday is rest, Tuesday threshold
    assert p["valid"]


def test_missed_easy_run_no_cramming(db):
    _, plan = _crafted_plan(db, BASE_WEEK)
    wed = _sid(plan, 2)
    before = {s["id"]: s for s in plan["sessions"]}
    p = rs.propose_missed(plan, wed, "time", today=MONDAY + timedelta(days=2), available_days="Mon,Tue,Wed,Thu,Sat,Sun")
    assert p["valid"]
    added = 0.0
    for c in p["changes"]:
        if c["session_id"] == wed:
            continue
        b, a = before[c["session_id"]], c["after"]
        assert a["session_type"] == b["session_type"] == "Easy Aerobic"     # only easy runs receive volume
        inc = a["distance_km"] - b["distance_km"]
        assert 0 < inc <= b["distance_km"] * rs.MAX_DAY_INCREASE + 1e-9    # <= +10% per run
        added += inc
    assert added <= 8.0 * rs.MAX_CARRY_SHARE + 1e-9                        # at most a modest share comes back
    final = _final(plan, p)
    assert _week_km(final) <= _week_km(plan["sessions"]) - 8.0 + 2.0      # the week never re-grows to plan
    assert _week_km(final) < _week_km(plan["sessions"])


def test_missed_with_illness_adds_nothing_and_eases_next_hard_day(db):
    week = [("Rest", 0), ("Easy Aerobic", 8), ("Rest", 0), ("Threshold", 8), ("Rest", 0),
            ("Long Run", 16), ("Easy Aerobic", 6)]
    _, plan = _crafted_plan(db, week)
    tue = _sid(plan, 1)
    p = rs.propose_missed(plan, tue, "illness", today=MONDAY + timedelta(days=1), available_days=ALL_DAYS)
    ch = _changes(p)
    thu = ch[_sid(plan, 3)]["after"]
    assert thu["session_type"] == "Easy Aerobic" and thu["distance_km"] <= 4.0
    assert _sid(plan, 5) not in ch                     # long run 4 days later untouched
    assert all(c["after"]["distance_km"] <= c["before"]["distance_km"] for c in p["changes"])


def test_rebalanced_generated_plans_pass_guardrails(db):
    for days in ("Mon,Tue,Thu,Sat,Sun", ALL_DAYS, "Tue,Thu,Sat", "Mon,Wed,Fri,Sun"):
        for weekday in range(7):
            _profile(db, days)
            today = MONDAY + timedelta(days=weekday)
            save_training_plan(TrainingPlanner(db_path=db).generate_plan(today=today), db_path=db)
            plan = get_active_training_plan(db_path=db)
            prior = rs.weekly_volumes(plan["sessions"])[1]
            for s in plan["sessions"][:7]:
                if not rs.can_mark_missed(s, today):
                    continue
                for reason in ("time", "illness"):
                    p = rs.propose_missed(plan, s["id"], reason, today=today, available_days=days)
                    assert p["valid"], (days, weekday, s["session_type"], p["new_violations"])
                    final = _final(plan, p)
                    skip_only = [{**x, "status": "Skipped"} if x["id"] == s["id"] else x for x in plan["sessions"]]
                    keys, raw = rs.check_guardrails(final, prior, 1)
                    base_keys, _ = rs.check_guardrails(skip_only, prior, 1)
                    assert keys <= base_keys, (days, weekday, raw)
                    assert _no_back_to_back_hard(final)
                    assert _week_km(final) <= _week_km(plan["sessions"])
                    # rest days only become run days when available
                    avail = rs.parse_available_days(days)
                    for c in p["changes"]:
                        if c["before"]["session_type"] == "Rest":
                            assert date.fromisoformat(c["date"]).weekday() in avail
                if rs.can_swap(s, today):
                    for o in rs.swap_options(s, "time"):
                        sp = rs.propose_swap(plan, s["id"], o["key"], "time", today=today)
                        assert len(sp["changes"]) == 1


# ------------------------------------------------------------------ preview / confirm / compliance
@pytest.fixture
def client_plan(db):
    _profile(db, ALL_DAYS)
    _, plan = _crafted_plan(db, BASE_WEEK)
    app = create_app(db_path=db)
    app.testing = True
    app.config["TODAY"] = MONDAY + timedelta(days=1)   # Tue (threshold day)
    return app.test_client(), plan, db


def _rows(db):
    conn = get_db_connection(db)
    rows = [dict(r) for r in conn.execute("SELECT * FROM plan_sessions ORDER BY session_date")]
    conn.close()
    return rows


def test_adjust_pages_and_preview_do_not_write(client_plan):
    client, plan, db = client_plan
    tue = _sid(plan, 1)
    before = _rows(db)
    r = client.get(f"/session/{tue}/adjust")
    assert r.status_code == 200 and b"Pick a reason first" not in r.data and b"Show options" in r.data
    r = client.get(f"/session/{tue}/adjust?reason=travel")
    assert b"Swap for an alternative" in r.data and b"Missed \xe2\x80\x93 rebalance my week" in r.data
    assert b'value="short"' in r.data and b"Recommended" in r.data
    r = client.get(f"/session/{tue}/adjust/preview?mode=swap&option=easy&reason=travel")
    assert r.status_code == 200 and b"Confirm changes" in r.data and b"Easy Aerobic" in r.data
    r = client.get(f"/session/{tue}/adjust/preview?mode=missed&reason=time")
    assert r.status_code == 200 and b"Threshold moved here" in r.data
    assert b'href="/plan"' in r.data                                     # cancel
    assert _rows(db) == before                                           # nothing saved
    # Not adjustable -> 400 with an explanation, still nothing saved
    r = client.get(f"/session/{_sid(plan, 8)}/adjust/preview?mode=swap&option=easy&reason=time")
    assert r.status_code == 400
    assert client.get("/session/nope/adjust").status_code == 404
    assert _rows(db) == before


def _token(client, sid, query):
    html = client.get(f"/session/{sid}/adjust/preview?{query}").data.decode()
    return re.search(r'name="token" value="([0-9a-f]+)"', html).group(1)


def test_confirm_swap_writes_and_keeps_original(client_plan):
    client, plan, db = client_plan
    tue = _sid(plan, 1)
    token = _token(client, tue, "mode=swap&option=easy&reason=travel&note=Airport")
    r = client.post(f"/session/{tue}/adjust", data={"mode": "swap", "option": "easy", "reason": "travel",
                                                     "note": "Airport", "token": token})
    assert r.status_code == 302 and "/plan?adjusted=swap" in r.headers["Location"]
    row = next(x for x in _rows(db) if x["id"] == tue)
    assert row["session_type"] == "Easy Aerobic" and row["status"] == "Pending"
    assert (row["original_session_type"], row["original_distance_km"]) == ("Threshold", 8.0)
    assert row["adjustment_kind"] == "swap" and row["adjustment_reason"] == "Travel" and row["adjustment_note"] == "Airport"
    page = client.get("/plan?adjusted=swap").data.decode()
    assert "Originally: Threshold 8 km" in page and "Session swapped." in page

    # Logging it as Completed records Modified; compliance stays against the ORIGINAL prescription
    update_session_status(tue, "Completed", actual_distance_km=6.0, db_path=db)
    assert next(x for x in _rows(db) if x["id"] == tue)["status"] == "Modified"
    comp = calculate_weekly_compliance(db_path=db, today=MONDAY + timedelta(days=1))
    assert comp["prescribed_total_km"] == 46.0          # 8+8+8+16+6 original
    assert comp["completed_total_km"] == 6.0
    assert comp["completed_sessions"] == 0 and comp["modified_sessions"] == 1

    # A second adjustment keeps the first original
    client.application.config["TODAY"] = MONDAY + timedelta(days=2)
    wed = _sid(plan, 2)
    token = _token(client, wed, "mode=swap&option=rest&reason=time")
    client.post(f"/session/{wed}/adjust", data={"mode": "swap", "option": "rest", "reason": "time", "token": token})
    row = next(x for x in _rows(db) if x["id"] == wed)
    assert row["status"] == "Skipped" and row["session_type"] == "Rest" and row["original_session_type"] == "Easy Aerobic"
    comp = calculate_weekly_compliance(db_path=db, today=MONDAY + timedelta(days=2))
    assert comp["total_sessions"] == 5 and comp["skipped_sessions"] == 1   # rest swap still counts as a session


def test_confirm_missed_rebalances_and_stale_token_saves_nothing(client_plan):
    client, plan, db = client_plan
    tue = _sid(plan, 1)
    before = _rows(db)
    r = client.post(f"/session/{tue}/adjust", data={"mode": "missed", "reason": "time", "token": "deadbeef"})
    assert r.status_code == 302 and "stale=1" in r.headers["Location"]
    assert _rows(db) == before
    token = _token(client, tue, "mode=missed&reason=time")
    r = client.post(f"/session/{tue}/adjust", data={"mode": "missed", "reason": "time", "token": token})
    assert r.status_code == 302
    rows = {x["id"]: x for x in _rows(db)}
    assert rows[tue]["status"] == "Skipped" and rows[tue]["adjustment_kind"] == "missed"
    assert rows[tue]["adherence_rating"] and "Skipped" in rows[tue]["adherence_rating"]
    wed = rows[_sid(plan, 2)]
    assert wed["session_type"] == "Threshold" and wed["original_session_type"] == "Easy Aerobic"
    assert wed["adjustment_kind"] == "rebalance"
    comp = calculate_weekly_compliance(db_path=db, today=MONDAY + timedelta(days=1))
    assert comp["prescribed_total_km"] == 46.0 and comp["skipped_sessions"] == 1
    page = client.get("/plan?adjusted=missed").data.decode()
    assert "Originally: Easy Aerobic 8 km" in page and "week rebalanced" in page


def test_auto_match_marks_adjusted_session_modified(client_plan):
    client, plan, db = client_plan
    tue = _sid(plan, 1)
    token = _token(client, tue, "mode=swap&option=short&reason=time")
    client.post(f"/session/{tue}/adjust", data={"mode": "swap", "option": "short", "reason": "time", "token": token})
    conn = get_db_connection(db)
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s) VALUES "
                 "('a1', ?, 'Run', 'Short tempo', 5000, 1500)", ((MONDAY + timedelta(days=1)).isoformat() + "T07:00:00Z",))
    conn.commit()
    conn.close()
    assert auto_match_activities_to_sessions(db_path=db, today=MONDAY + timedelta(days=1)) == 1
    row = next(x for x in _rows(db) if x["id"] == tue)
    assert row["status"] == "Modified" and row["matched_activity_id"] == "a1"


def test_unadjusted_sessions_keep_existing_behaviour(client_plan):
    client, plan, db = client_plan
    tue = _sid(plan, 1)
    update_session_status(tue, "Completed", actual_distance_km=8.0, db_path=db)
    assert next(x for x in _rows(db) if x["id"] == tue)["status"] == "Completed"
    comp = calculate_weekly_compliance(db_path=db, today=MONDAY + timedelta(days=1))
    assert comp["prescribed_total_km"] == 46.0 and comp["completed_sessions"] == 1


def test_migration_adds_adjustment_columns(db):
    conn = get_db_connection(db)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(plan_sessions)")}
    conn.close()
    assert {"original_session_type", "original_distance_km", "original_duration_min", "adjustment_kind",
            "adjustment_reason", "adjustment_note", "adjusted_at"} <= cols
