"""Send to COROS: course building against the MCP rules, preview-only reads, confirmed writes, no duplicates."""
from datetime import date, timedelta

import pytest

from app.coros_push import service as ps
from app.coros_push.workouts import build_course, parse_target
from app.data.db import init_db, get_db_connection
from app.data.queries import save_training_plan, get_active_training_plan, save_user_profile
from app.engine.planner import TrainingPlanner

TODAY = date.today()


# ------------------------------------------------------------------------------- course rules
def _check_section(sec, in_set=False):
    assert sec["sectionType"] in ((2, 3) if in_set else (1, 2, 3, 4))
    assert sec["targetType"] in (1, 2) and isinstance(sec["targetValue"], int) and sec["targetValue"] > 0
    formats = [k for k in ("sectionIntensity", "intensityPercentStart", "intensityValueStart") if k in sec]
    assert len(formats) == 1 and sec["intensityType"] in (1, 2)
    if "intensityValueStart" in sec:
        lo, hi = (30, 240) if sec["intensityType"] == 1 else (120, 1499)
        assert lo <= sec["intensityValueStart"] <= hi and lo <= sec["intensityValueEnd"] <= hi
    if "sectionIntensity" in sec:
        assert 1 <= sec["sectionIntensity"] <= 6


def check_course(course):
    assert course["sportType"] == 1 and 0 < len(course["courseName"]) <= 100 and course["courseDescription"]
    assert course["sections"] and "dayNo" not in course
    for sec in course["sections"]:
        if sec.get("intervalGroup"):
            assert 1 <= sec["repeats"] <= 20 and sec["sets"]
            assert not any(k in sec for k in ("targetType", "targetValue", "intensityType"))
            for m in sec["sets"]:
                assert not m.get("intervalGroup")
                _check_section(m, in_set=True)
        else:
            _check_section(sec)
    text = course["courseName"] + course["courseDescription"]
    assert "sectionType" not in text and "intensityType" not in text


SESSIONS = [
    {"session_type": "Easy Aerobic", "distance_km": 7.4, "duration_min": 44,
     "target_pace_or_hr": "Heart Rate Focus: 135 – 151 bpm (Zone 2 Easy, 5:37 – 6:11 /km)", "stated_purpose": "Easy."},
    {"session_type": "Easy Aerobic", "distance_km": 6.0, "duration_min": 36,
     "target_pace_or_hr": "Pace Focus: 5:37 – 6:11 /km (Zone 2 Easy, conversational)", "stated_purpose": "Easy."},
    {"session_type": "Threshold", "distance_km": 8.2, "duration_min": 46,
     "target_pace_or_hr": "Pace Focus: 4:37 – 4:43 /km (Zone 4 Daniels T pace / LT, 160 – 171 bpm)", "stated_purpose": "LT."},
    {"session_type": "Threshold", "distance_km": 3.0, "duration_min": 17,
     "target_pace_or_hr": "Pace Focus: 4:37 – 4:43 /km", "stated_purpose": "Short."},
    {"session_type": "VO2max", "distance_km": 9.0, "duration_min": 50,
     "target_pace_or_hr": "Pace Focus: 4:10 – 4:16 /km (Zone 5 Daniels I pace)", "stated_purpose": "V."},
    {"session_type": "Marathon Pace", "distance_km": 14.0, "duration_min": 80,
     "target_pace_or_hr": "Pace Focus: 4:55 – 5:05 /km (Zone 3 goal marathon pace)", "stated_purpose": "M."},
    {"session_type": "Long Run", "distance_km": 21.0, "duration_min": 125,
     "target_pace_or_hr": "Pace Focus: 5:37 – 6:11 /km (Zone 2 Long Run at Daniels E pace)", "stated_purpose": "L."},
    {"session_type": "Vert/Time-on-Feet", "distance_km": 10.0, "duration_min": 75,
     "target_pace_or_hr": "Pace Focus: 7:30 /km average incl. climbs (Zone 3 uphill effort, RPE 6-7/10)", "stated_purpose": "V."},
    {"session_type": "LTHR Test", "distance_km": 10.3, "duration_min": 55,
     "target_pace_or_hr": "Pace Focus: best even 30-min effort (start about 4:50 /km, RPE 7-8/10, press LAP at 10:00)",
     "stated_purpose": "Test."},
    {"session_type": "Race", "distance_km": 42.2, "duration_min": 210,
     "target_pace_or_hr": "Pace Focus: 4:59 /km (Goal race pace for 3:30:00)", "stated_purpose": "Race."},
    {"session_type": "Easy Aerobic", "distance_km": 5.0, "duration_min": 30, "target_pace_or_hr": "",
     "stated_purpose": "No target text."},
]


@pytest.mark.parametrize("session", SESSIONS, ids=lambda s: s["session_type"] + str(s["distance_km"]))
def test_every_session_type_builds_a_valid_course(session):
    course, why = build_course(session)
    assert why is None
    check_course(course)


def test_targets_follow_the_plan_text():
    easy, _ = build_course(SESSIONS[0])
    assert easy["sections"][0] == {"sectionType": 2, "targetType": 1, "targetValue": 7400, "intensityType": 1,
                                   "intensityValueStart": 135, "intensityValueEnd": 151}
    thr, _ = build_course(SESSIONS[2])
    work = thr["sections"][1]["sets"][0]
    assert work["intensityType"] == 2 and (work["intensityValueStart"], work["intensityValueEnd"]) == (277, 283)
    test, _ = build_course(SESSIONS[8])
    assert [s["targetValue"] for s in test["sections"]] == [900, 600, 1200, 600]


@pytest.mark.parametrize("stype", ["Rest", "Cross-Training", "S&C"])
def test_non_running_sessions_are_not_pushable(stype):
    course, why = build_course({"session_type": stype, "distance_km": 0, "duration_min": 40})
    assert course is None and why


def test_parse_target():
    t = parse_target("Pace Focus: 4:37 – 4:43 /km (Zone 4 Daniels T pace / LT, 160 – 171 bpm)")
    assert t == {"focus": "pace", "hr": (160, 171), "pace": (277, 283)}
    assert parse_target("Rest & Recovery") == {"focus": None, "hr": None, "pace": None}


# ---------------------------------------------------------------------------- fake COROS calendar
class FakeCoros:
    def __init__(self, return_id=True, editable=True, read_fails=False):
        self.cal = {}           # date iso -> list of {"title", "id_in_plan"}
        self.writes = []
        self.next_id = 500
        self.return_id, self.editable, self.read_fails = return_id, editable, read_fails
        self.call_failures = []

    def query_training_schedule(self, start, end):
        if self.read_fails:
            self.call_failures.append("queryTrainingSchedule: simulated outage")
            return None
        return [{"date": d, "title": w["title"], "id_in_plan": w["id_in_plan"]}
                for d, ws in sorted(self.cal.items()) if start.isoformat() <= d <= end.isoformat() for w in ws]

    def create_scheduled_workout(self, day, course):
        self.writes.append(("create", day.isoformat(), course["courseName"]))
        self.next_id += 1
        self.cal.setdefault(day.isoformat(), []).append({"title": course["courseName"], "id_in_plan": str(self.next_id)})
        return True, (f"Workout created on {day:%Y-%m-%d}. idInPlan: {self.next_id}" if self.return_id else "Workout created.")

    def query_scheduled_workout(self, day, id_in_plan):
        return True, f"Scheduled workout ... editable: {'true' if self.editable else 'false'}"

    def update_scheduled_workout(self, day, id_in_plan, course):
        self.writes.append(("update", day.isoformat(), course["courseName"]))
        for w in self.cal.get(day.isoformat(), []):
            if w["id_in_plan"] == id_in_plan:
                w["title"] = course["courseName"]
        return True, f"Updated. idInPlan: {id_in_plan}"


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "push.db")
    init_db(path)
    save_user_profile({"race_distance_type": "Marathon", "race_date": (TODAY + timedelta(days=150)).isoformat(),
                       "target_time_str": "3:30:00", "weekly_hours_available": 7.0,
                       "available_days": "Mon,Tue,Thu,Sat,Sun", "injury_history": "None",
                       "current_niggles": "None"}, db_path=path)
    save_training_plan(TrainingPlanner(db_path=path).generate_plan(), db_path=path)
    return path


def _preview(db, client, days=14):
    return ps.build_preview(db_path=db, today=TODAY, days=days, client=client)


def _push_all(db, client, days=14):
    p = _preview(db, client, days)
    return ps.push([i["session_id"] for i in p["writable"]], p["token"], db_path=db, today=TODAY, days=days, client=client)


def test_preview_reads_only_and_lists_runs(db):
    coros = FakeCoros()
    coros.cal[TODAY.isoformat()] = [{"title": "Morning Ride", "id_in_plan": "9"}]
    p = _preview(db, coros)
    assert coros.writes == []
    assert p["items"] and all(TODAY.isoformat() <= i["date"] <= (TODAY + timedelta(days=13)).isoformat() for i in p["items"])
    runs = [i for i in p["items"] if i["course"]]
    assert runs and all(i["state"] == "new" for i in runs)
    assert all(i["state"] == "skip" for i in p["items"] if i["session_type"] == "Rest")
    today_item = next((i for i in p["items"] if i["date"] == TODAY.isoformat() and i["course"]), None)
    if today_item:
        assert "Morning Ride" in " ".join(today_item["notes"])


def test_push_creates_once_and_second_preview_is_unchanged(db):
    coros = FakeCoros()
    results = _push_all(db, coros)
    assert results and all(r["ok"] for r in results)
    assert len(coros.writes) == len(results) and all(w[0] == "create" for w in coros.writes)
    p = _preview(db, coros)
    assert p["writable"] == [] and {i["state"] for i in p["items"] if i["course"]} == {"unchanged"}
    status = ps.push_status_by_date(get_active_training_plan(db_path=db), db_path=db)
    assert set(status.values()) == {"synced"}
    with pytest.raises(ps.StalePreview):     # the old token no longer matches after the push
        ps.push(["x"], "stale", db_path=db, today=TODAY, client=coros)


def test_changed_plan_updates_in_place_never_duplicates(db):
    coros = FakeCoros()
    _push_all(db, coros)
    created = len(coros.writes)
    conn = get_db_connection(db)
    sid, d = conn.execute("SELECT id, session_date FROM plan_sessions WHERE session_type = 'Easy Aerobic' AND "
                          "session_date >= ? ORDER BY session_date LIMIT 1", (TODAY.isoformat(),)).fetchone()
    conn.execute("UPDATE plan_sessions SET distance_km = distance_km + 1 WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    p = _preview(db, coros)
    assert [i["date"] for i in p["writable"]] == [d] and p["writable"][0]["state"] == "update"
    assert ps.push_status_by_date(get_active_training_plan(db_path=db), db_path=db)[d] == "outdated"
    results = ps.push([sid], p["token"], db_path=db, today=TODAY, client=coros)
    assert results[0]["ok"] and coros.writes[created:] == [("update", d, p["writable"][0]["course"]["courseName"])]
    assert len(coros.cal[d]) == 1


def test_regenerated_plan_updates_same_dates(db):
    coros = FakeCoros()
    _push_all(db, coros)
    created = len(coros.writes)
    save_training_plan(TrainingPlanner(db_path=db).generate_plan(), db_path=db)
    p = _preview(db, coros)
    assert all(i["state"] in ("unchanged", "update", "skip", "orphan") for i in p["items"])
    _push_all(db, coros)
    assert all(w[0] == "update" for w in coros.writes[created:])
    assert all(len(ws) == 1 for ws in coros.cal.values())


def test_only_selected_sessions_are_sent(db):
    coros = FakeCoros()
    p = _preview(db, coros)
    first = p["writable"][0]
    results = ps.push([first["session_id"]], p["token"], db_path=db, today=TODAY, client=coros)
    assert len(results) == 1 and coros.writes == [("create", first["date"], first["course"]["courseName"])]


def test_coros_read_failure_blocks_sending(db):
    coros = FakeCoros(read_fails=True)
    p = _preview(db, coros)
    assert p["coros_error"] and "duplicates" in p["coros_error"]
    with pytest.raises(ps.PushError):
        ps.push([i["session_id"] for i in p["items"]], p["token"], db_path=db, today=TODAY, client=coros)
    assert coros.writes == []


def test_missing_id_in_reply_is_recovered_from_calendar(db):
    coros = FakeCoros(return_id=False)
    _push_all(db, coros)
    conn = get_db_connection(db)
    ids = [r[0] for r in conn.execute("SELECT id_in_plan FROM coros_pushes")]
    conn.close()
    assert ids and all(ids)
    assert _preview(db, coros)["writable"] == []


def test_not_editable_workout_is_reported_not_overwritten(db):
    coros = FakeCoros()
    _push_all(db, coros)
    coros.editable = False
    conn = get_db_connection(db)
    sid = conn.execute("SELECT session_id FROM coros_pushes ORDER BY session_date LIMIT 1").fetchone()[0]
    conn.execute("UPDATE plan_sessions SET distance_km = distance_km + 1 WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    before = len(coros.writes)
    p = _preview(db, coros)
    results = ps.push([sid], p["token"], db_path=db, today=TODAY, client=coros)
    assert not results[0]["ok"] and "COROS app" in results[0]["message"] and len(coros.writes) == before


def test_removed_in_app_is_sent_again_and_rest_day_orphan_is_flagged(db):
    coros = FakeCoros()
    _push_all(db, coros)
    gone = sorted(coros.cal)[0]
    coros.cal[gone] = []                                       # user deleted it in the COROS app
    p = _preview(db, coros)
    assert next(i for i in p["items"] if i["date"] == gone)["state"] == "missing"
    other = sorted(coros.cal)[1]
    conn = get_db_connection(db)
    conn.execute("UPDATE plan_sessions SET session_type = 'Rest', distance_km = 0, duration_min = 0 "
                 "WHERE session_date = ? AND plan_id = (SELECT id FROM training_plans WHERE status = 'active')", (other,))
    conn.commit()
    conn.close()
    orphan = next(i for i in _preview(db, coros)["items"] if i["date"] == other)
    assert orphan["state"] == "orphan" and "delete it in the COROS app" in orphan["notes"][0]


def test_same_named_workout_already_on_coros_is_not_duplicated(db):
    coros = FakeCoros()
    first = next(i for i in _preview(db, coros)["items"] if i["course"])
    coros.cal[first["date"]] = [{"title": first["course"]["courseName"], "id_in_plan": "77"}]
    item = next(i for i in _preview(db, coros)["items"] if i["date"] == first["date"])
    assert item["state"] == "duplicate" and item not in _preview(db, coros)["writable"]


# ---------------------------------------------------------------------------------------- routes
@pytest.fixture
def web(db, monkeypatch):
    from app.mcp_client import coros_client
    from app.web.routes import create_app
    fake = FakeCoros()
    monkeypatch.setattr(coros_client, "CorosMCPClient", lambda *a, **k: fake)
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client(), fake


def test_preview_page_then_confirm(web):
    client, fake = web
    html = client.get("/plan/push").get_data(as_text=True)
    assert "Put your plan on the watch" in html and 'name="token"' in html and "Send to COROS" in html
    assert fake.writes == []
    import re
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    ids = re.findall(r'name="session" value="([^"]+)"', html)
    r = client.post("/plan/push", data={"token": token, "days": "14", "session": ids})
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and f"{len(ids)} of {len(ids)} sent" in body
    assert len(fake.writes) == len(ids)
    plan_html = client.get("/plan").get_data(as_text=True)
    assert "On COROS" in plan_html and 'id="sendToCorosBtn"' in plan_html
    again = client.post("/plan/push", data={"token": token, "days": "14", "session": ids}).get_data(as_text=True)
    assert "changed since the preview" in again and len(fake.writes) == len(ids)


def test_confirm_without_selection_sends_nothing(web):
    client, fake = web
    body = client.post("/plan/push", data={"token": "x", "days": "14"}).get_data(as_text=True)
    assert "Tick at least one workout" in body and fake.writes == []
