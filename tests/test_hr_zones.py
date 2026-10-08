"""LTHR field test: FIT parsing, cleaning, confidence, COROS zones, service, routes and planner integration."""
import json
from datetime import date, timedelta

import pytest

from app.analysis import hr_zones as hz
from app.analysis import zone_service as zs
from app.data.db import init_db, get_db_connection
from app.data.queries import save_user_profile
from tests.fit_builder import build_fit, synthetic_test_run

TEST_START = 900


def _run(**kw):
    return [dict(t=t, hr=h, speed=s, cadence=c) for t, h, s, c in synthetic_test_run(**kw)]


# ------------------------------------------------------------------------------------------ zones
def test_coros_lt_zones_match_research_example():
    zones = hz.coros_lt_zones(170)
    assert [(z["low"], z["high"]) for z in zones] == [
        (None, 135), (136, 152), (153, 161), (162, 173), (174, 180), (181, None)]
    assert [z["name"] for z in zones][3] == "Threshold"


@pytest.mark.parametrize("lthr", [150, 163, 168, 171, 185])
def test_zones_are_contiguous(lthr):
    zones = hz.coros_lt_zones(lthr)
    for a, b in zip(zones, zones[1:]):
        assert b["low"] == a["high"] + 1


# ------------------------------------------------------------------------------------- FIT + clean
def test_fit_round_trip_and_clean_test_is_good():
    parsed = hz.parse_fit(build_fit(synthetic_test_run()))
    assert len(parsed["samples"]) == 3300 and parsed["samples"][0]["t"] == 0
    r = hz.analyse_samples(parsed["samples"], TEST_START, sensor="strap", temp_c=20)
    assert r["lthr"] == 168 and r["confidence"] == "Good" and r["invalid_reason"] is None
    assert all(c["ok"] for c in r["criteria"])
    assert r["stats"]["valid_s"] == 1200


def test_corrupt_fit_raises_plain_error():
    data = bytearray(build_fit(synthetic_test_run()))
    data[200] ^= 0xFF
    with pytest.raises(hz.ZoneTestError):
        hz.parse_fit(bytes(data))


def test_wrist_sensor_and_unknown_temperature_lower_confidence():
    s = _run()
    assert hz.analyse_samples(s, TEST_START, sensor="wrist", temp_c=20)["confidence"] == "Fair"
    assert hz.analyse_samples(s, TEST_START, sensor="wrist", temp_c=None)["confidence"] == "Poor"


def test_short_dropouts_interpolated_long_ones_counted():
    s = _run()
    for k in range(TEST_START + 700, TEST_START + 703):          # 3 s gap: interpolated
        s[k]["hr"] = None
    r = hz.analyse_samples(s, TEST_START, "strap", 20)
    assert r["stats"]["missing_pct"] == 0.0 and r["lthr"] == 168
    for k in range(TEST_START + 800, TEST_START + 800 + 40):     # 40 s gap: 3.3% missing -> criterion fails
        s[k]["hr"] = 0
    r = hz.analyse_samples(s, TEST_START, "strap", 20)
    assert r["stats"]["missing_pct"] == 3.3 and r["confidence"] == "Fair"


def test_spikes_are_smoothed():
    s = _run()
    for k in (TEST_START + 900, TEST_START + 1300):
        s[k]["hr"] = 199
    r = hz.analyse_samples(s, TEST_START, "strap", 20)
    assert r["lthr"] == 168 and r["stats"]["spikes"] >= 2


def test_long_stop_invalidates_test():
    s = _run()
    for k in range(TEST_START + 1000, TEST_START + 1020):        # 20 s standing still
        s[k]["speed"] = 0.2
    r = hz.analyse_samples(s, TEST_START, "strap", 20)
    assert r["confidence"] == "Poor" and "stop of 20 s" in r["invalid_reason"]


def test_paused_watch_gap_counts_as_stop():
    s = [x for x in _run() if not (TEST_START + 1000 <= x["t"] < TEST_START + 1040)]
    r = hz.analyse_samples(s, TEST_START, "strap", 20)
    assert r["confidence"] == "Poor" and r["stats"]["longest_stop_s"] == 40


def test_cadence_lock_detected():
    s = _run(test_hr=176, cadence=88)                           # HR == 2 x per-leg cadence for the whole test
    r = hz.analyse_samples(s, TEST_START, "wrist", 20)
    assert r["stats"]["lock_pct"] > 90
    assert not next(c for c in r["criteria"] if c["key"] == "cadence_lock")["ok"]


def test_run_ending_early_is_rejected():
    s = [x for x in _run() if x["t"] < TEST_START + 1200]
    with pytest.raises(hz.ZoneTestError):
        hz.analyse_samples(s, TEST_START, "strap", 20)


# ---------------------------------------------------------------------------------- test window
def _laps(times):
    out, total = [], 0.0
    for t, hr in times:
        total += t
        out.append({"time": t, "totalLength": total, "avgHr": hr})
    return out


def test_window_from_10_plus_20_laps():
    w = hz.window_from_laps(_laps([(900, 135), (600, 162), (1200, 168), (600, 140)]))
    assert w["start_s"] == 900 and w["lap_avg_hr"] == 168 and w["source"] == "10:00 + 20:00 laps"


def test_window_from_single_30_min_lap_and_none():
    assert hz.window_from_laps(_laps([(900, 135), (1805, 166), (600, 140)]))["start_s"] == 900
    assert hz.window_from_laps(_laps([(1000, 150), (1000, 150)])) is None


def test_window_auto_finds_fastest_30_minutes():
    assert abs(hz.window_auto(_run()) - TEST_START) <= 5
    assert hz.window_auto(_run()[:1500]) is None


def test_lap_fallback_is_never_good():
    r = hz.analyse_lap_window({"lap_avg_hr": 167, "lap_time_s": 1200, "source": "x"}, "strap", 20)
    assert r["method"] == "laps" and r["lthr"] == 167 and r["confidence"] == "Fair"


# ------------------------------------------------------------------------------ recommendation
def test_recommendation_rules():
    good = {"lthr": 168, "confidence": "Good"}
    assert hz.recommendation(good, None, None)["update_coros"] is True
    assert hz.recommendation(good, 166, None)["update_coros"] is False
    assert hz.recommendation(good, 163, None)["delta"] == 5
    assert hz.recommendation({"lthr": 168, "confidence": "Poor"}, None, None)["update_coros"] is False
    assert hz.recommendation(good, None, 172)["notes"]          # 168 >= 95% of 172


# ------------------------------------------------------------------------------------ service
class FakeClient:
    def __init__(self, fit=True, laps=None):
        self.fit, self.laps, self.fit_calls, self.call_failures = fit, laps, 0, []

    def fetch_lap_list(self, label_id, sport_code=100):
        return self.laps or []

    def fetch_fit_bytes(self, label_id, sport_code=100):
        self.fit_calls += 1
        return build_fit(synthetic_test_run()) if self.fit else None


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "zones.db")
    init_db(path)
    conn = get_db_connection(path)
    today = date.today()
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, max_hr) VALUES "
                 "('act_test', ?, 'Run', 'LTHR test', 11000, 3300, 181)", (today.isoformat() + "T00:30:00Z",))
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s) VALUES "
                 "('act_bike', ?, 'Bike', 'Ride', 30000, 3600)", (today.isoformat() + "T08:00:00Z",))
    conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s) VALUES "
                 "('act_short', ?, 'Run', 'Easy', 5000, 1500)", (today.isoformat() + "T08:00:00Z",))
    conn.commit()
    conn.close()
    return path


def test_candidates_are_long_runs_with_test_titles_flagged(db):
    c = zs.list_candidates(db_path=db)
    assert [x["id"] for x in c] == ["act_test"] and c[0]["likely"] and not c[0]["tested"]


def test_analyse_activity_stores_result_and_caches_fit(db):
    client = FakeClient(laps=_laps([(900, 135), (600, 162), (1200, 168), (600, 140)]))
    tid = zs.analyse_activity("act_test", sensor="strap", temperature_c=19, db_path=db, client=client)
    tests = zs.get_tests(db_path=db)
    assert tests[0]["id"] == tid and tests[0]["lthr"] == 168 and tests[0]["confidence"] == "Good"
    assert tests[0]["stats"]["window_source"] == "10:00 + 20:00 laps" and tests[0]["method"] == "fit"
    assert tests[0]["zones"][1]["low"] == 135 and tests[0]["recommendation"]["update_coros"]
    zs.analyse_activity("act_test", sensor="strap", temperature_c=19, db_path=db, client=client)
    assert client.fit_calls == 1                                  # second analysis used the cached file
    assert zs.current_lthr(db_path=db)["lthr"] == 168
    assert zs.test_due(db_path=db)["due"] is False
    zs.mark_entered(tid, db_path=db)
    assert next(t for t in zs.get_tests(db_path=db) if t["id"] == tid)["entered_in_coros_at"]


def test_analyse_falls_back_to_laps_without_fit(db):
    client = FakeClient(fit=False, laps=_laps([(900, 135), (600, 162), (1200, 167), (600, 140)]))
    zs.analyse_activity("act_test", sensor="strap", temperature_c=19, db_path=db, client=client)
    t = zs.get_tests(db_path=db)[0]
    assert t["method"] == "laps" and t["lthr"] == 167 and t["confidence"] == "Fair"


@pytest.mark.parametrize("activity_id,client,msg", [
    ("missing", FakeClient(), "isn't in your synced data"),
    ("act_bike", FakeClient(), "Only runs"),
    ("act_short", FakeClient(), "shorter than 30 minutes"),
    ("act_test", FakeClient(fit=False), "Couldn't get per-second data"),
])
def test_analyse_errors_are_plain_and_store_nothing(db, activity_id, client, msg):
    with pytest.raises(hz.ZoneTestError, match=msg):
        zs.analyse_activity(activity_id, sensor="strap", db_path=db, client=client)
    assert zs.get_tests(db_path=db) == []


def test_poor_test_is_not_used_and_retest_due(db):
    conn = get_db_connection(db)
    old = (date.today() - timedelta(days=70)).isoformat()
    conn.execute("INSERT INTO hr_zone_tests (activity_id, test_date, lthr, confidence, method) VALUES "
                 "('a', ?, 165, 'Good', 'fit'), ('b', ?, 175, 'Poor', 'fit')", (old, date.today().isoformat()))
    conn.commit()
    conn.close()
    assert zs.current_lthr(db_path=db)["lthr"] == 165
    due = zs.test_due(db_path=db)
    assert due["due"] and "70 days" in due["reason"]


# -------------------------------------------------------------------------------------- routes
@pytest.fixture
def client(db):
    from app.web.routes import create_app
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client()


def test_zones_page_empty_state(client):
    html = client.get("/zones").get_data(as_text=True)
    assert "Your training zones" in html and "Not Available" in html and "Due now" in html
    assert "30-minute threshold time trial" in html and 'value="act_test"' in html


def test_analyse_route_validates_input(client):
    r = client.post("/zones/analyse", data={"activity_id": "act_test"})
    assert r.status_code == 302 and "chest+strap" in r.headers["Location"]
    r = client.post("/zones/analyse", data={"activity_id": "act_test", "sensor": "strap", "temperature_c": "hot"})
    assert "Temperature" in r.headers["Location"] or "Temperature".lower() in r.headers["Location"].lower()


def test_analyse_route_success_then_entered_and_delete(client, db, monkeypatch):
    real = zs.analyse_activity
    monkeypatch.setattr(zs, "analyse_activity", lambda aid, **kw: real(
        aid, client=FakeClient(laps=_laps([(900, 135), (600, 162), (1200, 168), (600, 140)])), **kw))
    r = client.post("/zones/analyse", data={"activity_id": "act_test", "sensor": "strap", "temperature_c": "21"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#result"), r.headers["Location"]
    html = client.get(r.headers["Location"].split("#")[0]).get_data(as_text=True)
    assert "Threshold HR 168 bpm" in html and "160–171 bpm" in html and "Update COROS" in html
    tid = zs.get_tests(db_path=db)[0]["id"]
    html = client.post(f"/zones/{tid}/entered", follow_redirects=True).get_data(as_text=True)
    assert "Entered in COROS on" in html
    client.post(f"/zones/{tid}/delete")
    assert zs.get_tests(db_path=db) == []


def test_analyse_route_shows_plain_error(client):
    r = client.post("/zones/analyse", data={"activity_id": "act_bike", "sensor": "wrist"}, follow_redirects=True)
    assert "Only runs can be used" in r.get_data(as_text=True)


# ------------------------------------------------------------------------------------- planner
def _profile(db):
    save_user_profile({"race_distance_type": "Marathon", "race_date": "2027-03-14", "target_time_str": "3:30:00",
                       "weekly_hours_available": 7.0, "available_days": "Mon,Tue,Thu,Sat,Sun",
                       "injury_history": "None", "current_niggles": "None"}, db_path=db)


def test_plan_schedules_zone_test_when_due(db):
    from app.engine.guardrails import validate_multiweek_plan
    from app.engine.planner import TrainingPlanner
    _profile(db)
    plan = TrainingPlanner(db_path=db).generate_plan(today=date(2026, 10, 5))
    tests = [s for s in plan["sessions"] if s["session_type"] == "LTHR Test"]
    assert len(tests) == 1 and tests[0]["week_number"] <= 2 and "LAP at 10:00" in tests[0]["target_pace_or_hr"]
    assert any(i["topic"] == "Heart-rate zone test" for i in plan["decisions"]["items"])
    assert "Guardrail warning" not in plan["methodology_rationale"]


def test_plan_uses_lthr_for_hr_targets_and_skips_test_when_recent(db):
    from app.engine.planner import TrainingPlanner
    _profile(db)
    conn = get_db_connection(db)
    conn.execute("INSERT INTO hr_zone_tests (activity_id, test_date, lthr, confidence, method) VALUES "
                 "('act_test', '2026-10-01', 170, 'Good', 'fit')")
    conn.commit()
    conn.close()
    plan = TrainingPlanner(db_path=db).generate_plan(today=date(2026, 10, 5))
    assert not [s for s in plan["sessions"] if s["session_type"] == "LTHR Test"]
    easy = next(s for s in plan["sessions"] if s["session_type"] == "Easy Aerobic" and "Zone 2" in s["target_pace_or_hr"])
    assert "136 – 152 bpm" in easy["target_pace_or_hr"]
    thr = next(s for s in plan["sessions"] if s["session_type"] == "Threshold")
    assert "162 – 173 bpm" in thr["target_pace_or_hr"]
    hr_item = next(i for i in plan["decisions"]["items"] if i["topic"] == "Heart-rate zones")
    assert "Threshold HR 170 bpm" in hr_item["summary"]
