"""Goal-profile-driven, evidence-based planning: every profile field changes the plan, decisions are stored and
shown, and missing profile fields are reported instead of being replaced by invented defaults (NFR-4.1)."""
import json
from datetime import date, timedelta

import pytest

from app.data.db import init_db, get_db_connection
from app.data.queries import get_user_profile, save_user_profile, save_training_plan, get_active_training_plan
from app.engine.guardrails import (
    validate_multiweek_plan, validate_evidence_rules, training_volumes, easy_share_by_week, validate_acwr,
    validate_recovery_weeks,
)
from app.engine.planner import TrainingPlanner, ProfileIncompleteError, profile_gaps, vdot_from_performance
from app.web.routes import create_app

TODAY = date(2026, 9, 30)          # Wednesday
MONDAY = date(2026, 9, 28)
FULL = {"race_distance_type": "Marathon", "race_date": "2027-03-07", "target_time_str": "3:45:00",
        "weekly_hours_available": 8.0, "available_days": "Mon,Tue,Thu,Sat,Sun",
        "injury_history": "None", "current_niggles": "None"}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "goal_profile.db")
    init_db(path)
    return path


def _plan(db, **kw):
    save_user_profile({**FULL, **kw}, db_path=db)
    return TrainingPlanner(db_path=db).generate_plan(today=TODAY)


def _history(db, km_per_week=50.0, weeks=4, max_hr=None):
    """Four complete weeks of runs before MONDAY (3 runs per week)."""
    conn = get_db_connection(db)
    for w in range(1, weeks + 1):
        for i, offset in enumerate((0, 2, 5)):
            day = MONDAY - timedelta(days=7 * w) + timedelta(days=offset)
            conn.execute("INSERT INTO activities (id, date, sport_type, name, distance_m, duration_s, max_hr)"
                         " VALUES (?, ?, 'Run', 'Run', ?, ?, ?)",
                         (f"h{w}_{i}", day.isoformat() + "T07:00:00Z", km_per_week / 3 * 1000, km_per_week / 3 * 330,
                          max_hr))
    conn.commit()
    conn.close()


def _run_days(plan, week=1):
    return {s["day_of_week"] for s in plan["sessions"] if s["week_number"] == week and s["session_type"] != "Rest"}


def _ok(plan):
    ok, violations = validate_multiweek_plan(plan, plan["prior_volume_km"])
    assert ok, violations
    assert "Guardrail warning" not in plan["methodology_rationale"]


# ------------------------------------------------------------------ missing profile: never invent defaults
def test_no_saved_profile_returns_unknown_fields_not_a_fabricated_goal(db):
    prof = get_user_profile(db_path=db)
    for key in ("race_distance_type", "race_date", "target_time_str", "weekly_hours_available", "available_days"):
        assert prof[key] is None
    with pytest.raises(ProfileIncompleteError) as exc:
        TrainingPlanner(db_path=db).generate_plan(today=TODAY)
    assert [g["field"] for g in exc.value.gaps] == [
        "race_distance_type", "race_date", "target_time_str", "weekly_hours_available", "available_days"]


def test_each_missing_or_unreadable_field_is_named(db):
    save_user_profile({**FULL, "target_time_str": "", "weekly_hours_available": None}, db_path=db)
    gaps = profile_gaps(get_user_profile(db_path=db))
    assert {g["field"] for g in gaps} == {"target_time_str", "weekly_hours_available"}
    bad = profile_gaps({**FULL, "available_days": "Mon,Funday", "target_time_str": "fast", "race_date": "soon"})
    assert {g["field"] for g in bad} == {"available_days", "target_time_str", "race_date"}
    assert "Funday" in next(g["problem"] for g in bad if g["field"] == "available_days")
    assert profile_gaps({**FULL, "injury_history": "", "current_niggles": None}) == []   # optional fields


def test_generate_route_reports_missing_fields_and_links_profile(db):
    save_user_profile({**FULL, "target_time_str": None}, db_path=db)
    client = create_app(db_path=db).test_client()
    res = client.post("/plan/generate", data={"is_deload": "0"})
    assert res.status_code == 302 and "profile_incomplete=1" in res.headers["Location"]
    assert get_active_training_plan(db_path=db) is None
    html = client.get("/plan?profile_incomplete=1").data.decode("utf-8")
    assert "PLAN NOT GENERATED: GOAL PROFILE INCOMPLETE" in html
    assert 'data-field="target_time_str"' in html and "Target time" in html
    assert 'href="/profile"' in html
    profile_html = client.get("/profile").data.decode("utf-8")
    assert "Needed before a training plan can be generated" in profile_html and "Target time" in profile_html
    assert profile_html.split('name="target_time_str"')[1].startswith(' value=""')   # no fabricated value


def test_profile_post_keeps_blank_fields_blank(db):
    client = create_app(db_path=db).test_client()
    client.post("/profile", data={"race_distance_type": "10K", "race_date": "2027-01-10", "target_time_str": "",
                                  "weekly_hours_available": "", "available_days": "", "injury_history": "",
                                  "current_niggles": ""})
    prof = get_user_profile(db_path=db)
    assert prof["race_distance_type"] == "10K"
    assert prof["target_time_str"] is None and prof["weekly_hours_available"] is None and prof["available_days"] is None


# ------------------------------------------------------------------ each field materially changes the plan
def test_race_date_drives_phases_taper_and_race_day(db):
    far = _plan(db, race_date="2027-06-06")
    assert [w["phase"] for w in far["week_summaries"]] == ["base"] * 5
    assert not any(s["session_type"] in ("Race", "Marathon Pace") for s in far["sessions"])

    race = MONDAY + timedelta(days=27)          # Sunday of week 4
    near = _plan(db, race_date=race.isoformat())
    assert [w["phase"] for w in near["week_summaries"]] == ["peak", "taper", "taper", "race", "recovery"]
    races = [s for s in near["sessions"] if s["session_type"] == "Race"]
    assert len(races) == 1 and races[0]["session_date"] == race.isoformat() and races[0]["distance_km"] == 42.2
    by_date = {s["session_date"]: s for s in near["sessions"]}
    assert by_date[(race - timedelta(days=1)).isoformat()]["session_type"] == "Rest"
    assert by_date[(race + timedelta(days=1)).isoformat()]["session_type"] == "Rest"
    tv = list(training_volumes(near["sessions"]).values())
    assert tv[1] < tv[0] and tv[2] < tv[1] and tv[3] < tv[2]           # progressive taper (Mujika & Padilla)
    assert tv[3] <= tv[0] * 0.5                                          # race week >= ~50% reduction (Bosquet)
    assert any(s["session_type"] == "Marathon Pace" for s in near["sessions"] if s["week_number"] == 1)  # peak
    assert all(s["session_type"] in ("Rest", "Easy Aerobic") for s in near["sessions"] if s["week_number"] == 5)
    _ok(near)
    _ok(far)


def test_weekly_hours_cap_volume(db):
    _history(db, km_per_week=50.0)
    roomy = _plan(db, weekly_hours_available=10.0)
    tight = _plan(db, weekly_hours_available=4.0)
    assert roomy["prior_volume_km"] == tight["prior_volume_km"] == 50.0
    assert training_volumes(roomy["sessions"])[1] == pytest.approx(54.0, abs=0.3)   # 4-week average +8%
    for week, vol in training_volumes(tight["sessions"]).items():
        minutes = sum(s["duration_min"] for s in tight["sessions"] if s["week_number"] == week)
        assert minutes <= 4.0 * 60 + 1
        assert vol < training_volumes(roomy["sessions"])[week]
    assert any("capped by 4 h/week" in n for w in tight["decisions"]["weeks"] for n in w["notes"])
    assert "Volume was reduced to fit" in next(i["summary"] for i in tight["decisions"]["items"]
                                                if i["topic"] == "Weekly hours ceiling")


def test_available_days_place_every_run(db):
    a = _plan(db, available_days="Tue,Thu,Sat")
    b = _plan(db, available_days="Mon,Wed,Fri,Sun")
    for week in range(1, 6):
        assert _run_days(a, week) == {"Tue", "Thu", "Sat"}
        assert _run_days(b, week) == {"Mon", "Wed", "Fri", "Sun"}
    assert {s["day_of_week"] for s in a["sessions"] if s["session_type"] == "Long Run"} == {"Sat"}
    assert {s["day_of_week"] for s in b["sessions"] if s["session_type"] == "Long Run"} == {"Sun"}
    _ok(a)
    _ok(b)


def test_target_time_sets_daniels_paces(db):
    fast = _plan(db, target_time_str="3:00:00")
    slow = _plan(db, target_time_str="4:30:00")

    def t_pace(plan):
        target = next(s["target_pace_or_hr"] for s in plan["sessions"] if s["session_type"] == "Threshold")
        lo = target.split("Pace Focus: ")[1].split(" ")[0]
        m, s = lo.split(":")
        return int(m) * 60 + int(s)
    assert t_pace(fast) < t_pace(slow) - 60
    assert vdot_from_performance(42195, 180) == pytest.approx(53.5, abs=0.5)     # Daniels table VDOT for 3:00
    paces = next(i for i in fast["decisions"]["items"] if i["topic"] == "Training paces")
    assert "VDOT 53" in paces["summary"] and "daniels_gilbert" in paces["sources"]


def test_hr_zones_only_from_observed_max_hr(db):
    no_hr = _plan(db)
    assert not any("bpm" in s["target_pace_or_hr"] for s in no_hr["sessions"])
    _history(db, km_per_week=30.0, max_hr=190)
    with_hr = _plan(db)
    easy = next(s for s in with_hr["sessions"] if s["session_type"] == "Easy Aerobic")
    assert easy["target_pace_or_hr"].startswith("Heart Rate Focus: 124 – 150 bpm")       # 65-79% of 190


def test_injury_history_and_niggles_make_plan_conservative(db):
    base = _plan(db, available_days="Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    injured = _plan(db, available_days="Mon,Tue,Wed,Thu,Fri,Sat,Sun", injury_history="Achilles tendinopathy 2025")
    gb, gi = training_volumes(base["sessions"]), training_volumes(injured["sessions"])
    assert gi[3] < gb[3]                                           # +5%/week instead of +8%
    assert validate_multiweek_plan(injured, injured["prior_volume_km"], max_consecutive=3)[0]
    assert not validate_multiweek_plan(base, base["prior_volume_km"], max_consecutive=3)[0]
    assert "van_gent" in next(i for i in injured["decisions"]["items"] if i["topic"] == "Injury history")["sources"]

    niggle = _plan(db, current_niggles="sore left calf")
    assert not any(s["session_type"] in ("Threshold", "VO2max", "Marathon Pace") for s in niggle["sessions"])
    assert training_volumes(niggle["sessions"])[1] == pytest.approx(niggle["prior_volume_km"], abs=0.3)  # held


def test_distance_routes_quality_type(db):
    race = (MONDAY + timedelta(days=8 * 7)).isoformat()          # build phase inside the window
    ten = _plan(db, race_distance_type="10K", target_time_str="45:00", race_date=race)
    assert any(s["session_type"] == "VO2max" for s in ten["sessions"])
    ultra = _plan(db, race_distance_type="50K Ultra", target_time_str="6:00:00", race_date=race)
    assert any(s["session_type"] == "Vert/Time-on-Feet" for s in ultra["sessions"])
    assert "Uphill Athlete" in ultra["methodology_name"]


def test_every_profile_combination_passes_all_guardrails(db):
    _history(db, km_per_week=40.0, max_hr=185)
    for dist, target in (("5K", "22:00"), ("10K", "45:00"), ("Half Marathon", "1:45:00"), ("Marathon", "3:30:00"),
                         ("50K Ultra", "5:30:00"), ("100K Ultra", "12:00:00")):
        for weeks_out in (1, 2, 3, 4, 6, 10, 20, -2):
            for days in ("Mon,Tue,Thu,Sat,Sun", "Tue,Thu,Sat", "Mon,Tue,Wed,Thu,Fri,Sat,Sun", "Sat,Sun"):
                for injury in ("None", "ITB 2024"):
                    race = MONDAY + timedelta(days=7 * weeks_out + 5)
                    plan = _plan(db, race_distance_type=dist, target_time_str=target, race_date=race.isoformat(),
                                 available_days=days, injury_history=injury, weekly_hours_available=6.0)
                    ctx = (dist, weeks_out, days, injury)
                    assert len(plan["sessions"]) == 35, ctx
                    ok, v = validate_evidence_rules(plan, plan["prior_volume_km"], [40.0] * 4,
                                                    max_consecutive=3 if injury != "None" else 4)
                    assert ok, (ctx, v)
                    assert all(p >= 80.0 for p in easy_share_by_week(plan["sessions"]).values()), ctx


def test_evidence_guardrail_helpers():
    assert validate_acwr([52.0], [40.0] * 4) == []
    assert validate_acwr([60.0], [40.0] * 4)                       # 1.5 > 1.3
    assert validate_recovery_weeks(["build"] * 4 + ["taper"]) == []
    assert validate_recovery_weeks(["build"] * 5)


# ------------------------------------------------------------------ decisions persisted and rendered
def test_decisions_saved_and_rendered_after_methodology_card(db):
    _history(db, km_per_week=39.0)
    plan = _plan(db, race_date=(MONDAY + timedelta(days=27)).isoformat(), weekly_hours_available=6.5)
    topics = [i["topic"] for i in plan["decisions"]["items"]]
    for t in ("Goal race & phases", "Training paces", "Week 1 volume", "Weekly hours ceiling",
              "Progression & recovery weeks", "Injury history", "Current niggles", "Run days",
              "Intensity distribution", "Long run", "Taper & race", "Guardrail check"):
        assert t in topics
    w1 = next(i for i in plan["decisions"]["items"] if i["topic"] == "Week 1 volume")
    assert "prior 4-week average 39.0 km" in w1["summary"]
    save_training_plan(plan, db_path=db)
    stored = json.loads(get_active_training_plan(db_path=db)["decisions_json"])
    assert stored["items"] == plan["decisions"]["items"]
    assert {s["key"] for s in stored["sources"]} >= {"daniels", "bosquet", "mujika", "seiler", "gabbett"}

    html = create_app(db_path=db).test_client().get("/plan").data.decode("utf-8")
    assert html.index("<!-- Methodology & Overview Card -->") < html.index('id="plan-decisions"') < html.index("5 weeks, day by day")
    assert "Decisions &amp; evidence" in html and "Bosquet et al. (2007)" in html
    assert "Med Sci Sports Exerc, 39(8), 1358-1365" in html
    assert "Rationale:" in html and plan["methodology_rationale"][:40] in html
