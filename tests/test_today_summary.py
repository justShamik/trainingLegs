"""Tests for daily activity totals (queryDailyHealthData), get_today_summary and get_sync_status."""
from datetime import date, timedelta, timezone

import pytest

from app.data.db import get_db_connection, init_db
from app.data.queries import (BASELINE_DAYS, _pct, get_sync_status, get_today_summary, local_date_of)
from app.data.sync import perform_sync, save_activity, save_daily_activity, save_sleep_record
from app.mcp_client import coros_client
from app.mcp_client.coros_client import CorosMCPClient

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 10, 3)

SAMPLE = """Daily Health Data — Last 3 days | Resting HR: 53 bpm
Note: sleep entries are dated by their wake-up day.

--- 20261001 ---
Steps: 12,345 | Calories: 1,027 kcal | Exercise: 1h 5min | Floors: 6
Stress: Avg 31
Sleep Summary:
  Total: 7h 4min | Deep: 1h 19min | Light: 4h 21min | REM: 54 min | Awake: 30 min

--- 20261002 ---
Steps: 830
Sleep Summary:
  Total: 46 min | Deep: 6 min | Light: 34 min | REM: 0 min | Awake: 6 min

--- 20261003 ---
Steps: 6,235 | Calories: 427 kcal | Exercise: 1 min
Stress: Avg 28
Sleep Summary:
  Total: 8h 3min | Deep: 1h 33min | Light: 4h 19min | REM: 1h 56min | Awake: 15 min
"""


def _db(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    return db


# ---- parsing --------------------------------------------------------------------------------

def test_parse_daily_activity_commas_missing_and_multiple_days():
    recs = {r["date"]: r for r in CorosMCPClient()._parse_daily_activity(SAMPLE)}
    assert list(recs) == ["2026-10-01", "2026-10-02", "2026-10-03"]
    d1 = recs["2026-10-01"]
    assert (d1["steps"], d1["calories_kcal"], d1["exercise_minutes"], d1["stress_avg"]) == (12345, 1027.0, 65.0, 31.0)
    d2 = recs["2026-10-02"]  # only steps reported -> the rest stays None, never 0
    assert d2["steps"] == 830 and d2["calories_kcal"] is None and d2["exercise_minutes"] is None
    assert d2["stress_avg"] is None
    assert "Sleep Summary" not in d1["raw_payload"]


def test_parse_daily_activity_skips_days_without_values():
    text = "--- 20261001 ---\nSleep Summary:\n  Total: 7h 0min\n"
    assert CorosMCPClient()._parse_daily_activity(text) == []


def test_parse_daily_activity_real_fixture():
    import os
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "coros_daily_health_365.txt"), encoding="utf-8") as f:
        recs = CorosMCPClient()._parse_daily_activity(f.read())
    by = {r["date"]: r for r in recs}
    assert len(recs) > 300
    assert by["2025-10-02"]["steps"] == 25731 and by["2025-10-02"]["calories_kcal"] == 1709.0
    assert by["2025-10-02"]["exercise_minutes"] == 89.0


def test_one_call_yields_sleep_and_activity():
    class C(CorosMCPClient):
        calls = 0
        def _call_cli_tool(self, tool, args):
            C.calls += 1
            return SAMPLE
    sleep, activity = C().fetch_daily_health()
    assert C.calls == 1 and len(sleep) == 3 and len(activity) == 3
    assert C().fetch_sleep_records()[-1]["total_sleep_minutes"] == 483


# ---- persistence ----------------------------------------------------------------------------

def test_upsert_idempotent_and_coalesce(tmp_path):
    db = _db(tmp_path)
    conn = get_db_connection(db)
    rec = {"date": "2026-10-03", "steps": 6235, "calories_kcal": 427.0, "exercise_minutes": 1.0,
           "stress_avg": 28.0, "raw_payload": "x"}
    save_daily_activity(rec, conn)
    save_daily_activity(rec, conn)
    save_daily_activity({"date": "2026-10-03", "steps": 7000}, conn)  # partial: keeps calories
    conn.commit()
    rows = conn.execute("SELECT * FROM daily_activity").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["steps"] == 7000 and rows[0]["calories_kcal"] == 427.0 and rows[0]["synced_at"]


def test_perform_sync_stores_daily_activity(tmp_path):
    db = _db(tmp_path)

    class Client(CorosMCPClient):
        def is_authenticated(self): return True
        def fetch_workouts(self, since_date=None): return []
        def fetch_daily_physiology(self, since_date=None): return []
        def _call_cli_tool(self, tool, args):
            assert tool == "queryDailyHealthData"
            return SAMPLE
    ok, n, msg, _ = perform_sync(Client(), db_path=db)
    assert ok and n == 6 and "3 daily activity days" in msg
    s = get_today_summary(db, today=TODAY, tz=IST)
    assert s["steps"] == 6235 and s["calories_kcal"] == 427.0 and s["sleep"]["total_minutes"] == 483


def test_daily_activity_migration_on_existing_db(tmp_path):
    db = str(tmp_path / "old.db")
    init_db(db)
    conn = get_db_connection(db)
    conn.execute("DROP TABLE daily_activity")
    conn.commit()
    conn.close()
    init_db(db)
    conn = get_db_connection(db)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(daily_activity)")}
    conn.close()
    assert cols == {"date", "steps", "calories_kcal", "exercise_minutes", "stress_avg", "raw_payload", "synced_at"}


# ---- today summary --------------------------------------------------------------------------

def test_today_summary_empty(tmp_path):
    s = get_today_summary(_db(tmp_path), today=TODAY, tz=IST)
    assert s["date"] == "2026-10-03"
    assert s["sleep"] is None and s["sleep_reason"] == "Not synced yet today"
    assert s["steps"] is None and s["calories_kcal"] is None and s["exercise_minutes"] is None
    assert s["daily_activity_reason"] == "Not synced yet today"
    assert s["activity_time_minutes"] == 0 and s["activity_count"] == 0
    assert s["pct"] == {"sleep": None, "activity": None, "steps": None, "calories": None}  # no history, no goal


def test_today_summary_with_data_and_date_boundaries(tmp_path):
    db = _db(tmp_path)
    conn = get_db_connection(db)
    save_sleep_record({"date": "2026-10-03", "total_sleep_minutes": 420, "deep_sleep_minutes": 90,
                       "light_sleep_minutes": 250, "rem_sleep_minutes": 60, "awake_minutes": 20}, conn)
    save_sleep_record({"date": "2026-10-02", "total_sleep_minutes": 300}, conn)
    save_daily_activity({"date": "2026-10-03", "steps": 15000, "calories_kcal": 1250.0, "exercise_minutes": 50.0}, conn)
    for i, (ts, dur) in enumerate([
        ("2026-10-02T20:00:00Z", 1800),   # 2026-10-03 01:30 IST -> counts as today
        ("2026-10-03T08:00:00Z", 2400),   # COROS placeholder time -> today
        ("2026-10-03T19:00:00Z", 999),    # 2026-10-04 00:30 IST -> tomorrow, excluded
        ("2026-10-02T08:00:00Z", 999),    # yesterday
        ("2026-10-03", 600),              # date-only -> today
    ]):
        save_activity({"id": f"a{i}", "date": ts, "distance_m": 1000.0, "duration_s": dur}, conn)
    conn.commit()
    conn.close()

    s = get_today_summary(db, today=TODAY, tz=IST)
    assert s["sleep"] == {"total_minutes": 420, "deep_minutes": 90, "light_minutes": 250,
                          "rem_minutes": 60, "awake_minutes": 20}
    assert s["activity_count"] == 3 and s["activity_time_minutes"] == 80.0
    assert s["exercise_minutes"] == 50.0 and s["steps"] == 15000
    # vs the previous 7 days: sleep 420 vs 300 avg, 80 min vs 16.6 min avg; no earlier steps/calories
    assert s["baseline"] == {"sleep_minutes": 300, "activity_minutes": 16.6, "steps": None, "calories_kcal": None}
    assert s["pct"] == {"sleep": 100, "activity": 100, "steps": None, "calories": None}

    # Same data seen from UTC: the 20:00Z activity belongs to 2026-10-02
    s_utc = get_today_summary(db, today=TODAY, tz=timezone.utc)
    assert s_utc["activity_count"] == 3 and s_utc["activity_time_minutes"] == round((2400 + 999 + 600) / 60, 1)


def test_today_summary_sleep_missing_but_synced(tmp_path):
    db = _db(tmp_path)
    conn = get_db_connection(db)
    save_daily_activity({"date": "2026-10-03", "steps": 100}, conn)
    conn.commit()
    conn.close()
    s = get_today_summary(db, today="2026-10-03", tz=IST)
    assert s["sleep"] is None and s["sleep_reason"] == "No sleep recorded last night"
    assert s["calories_kcal"] is None and s["pct"]["calories"] is None and s["pct"]["steps"] is None


def test_local_date_of():
    assert local_date_of("2026-10-02T20:00:00Z", IST) == date(2026, 10, 3)
    assert local_date_of("2026-10-02T20:00:00+05:30", IST) == date(2026, 10, 2)
    assert local_date_of("2026-10-02T23:00:00", IST) == date(2026, 10, 2)  # naive: date part
    assert local_date_of("2026-10-02", IST) == date(2026, 10, 2)
    assert local_date_of(None) is None and local_date_of("garbage") is None


def test_pct_capping():
    assert _pct(None, 480) is None
    assert _pct(480, None) is None                 # no baseline -> no fill, never an invented goal
    assert _pct(960, 480) == 100
    assert _pct(-5, 60) == 0
    assert _pct(30, 60) == 50
    assert _pct(0, 60) == 0


def test_dials_compare_with_own_7_day_average_not_goals(tmp_path):
    db = _db(tmp_path)
    conn = get_db_connection(db)
    for i in range(1, BASELINE_DAYS + 1):                       # previous 7 days
        d = (TODAY - timedelta(days=i)).isoformat()
        save_sleep_record({"id": f"s{i}", "date": d, "total_sleep_minutes": 400}, conn)
        save_daily_activity({"date": d, "steps": 8000, "calories_kcal": 2000.0}, conn)
    save_activity({"id": "r1", "date": (TODAY - timedelta(days=2)).isoformat() + "T08:00:00", "sport_type": "Run",
                   "name": "Run", "distance_m": 10000.0, "duration_s": 7 * 600.0}, conn)   # 70 min over 7 days
    d8 = (TODAY - timedelta(days=BASELINE_DAYS + 1)).isoformat()                           # outside the window
    save_daily_activity({"date": d8, "steps": 90000, "calories_kcal": 9000.0}, conn)
    save_sleep_record({"id": "s_today", "date": TODAY.isoformat(), "total_sleep_minutes": 200}, conn)
    save_daily_activity({"date": TODAY.isoformat(), "steps": 4000, "calories_kcal": 1000.0}, conn)
    conn.commit()
    conn.close()
    t = get_today_summary(db_path=db, today=TODAY)
    assert "goals" not in t
    assert t["baseline"] == {"sleep_minutes": 400, "activity_minutes": 10.0, "steps": 8000, "calories_kcal": 2000}
    assert t["pct"] == {"sleep": 50, "activity": 0, "steps": 50, "calories": 50}


def test_no_history_means_no_baseline(tmp_path):
    db = _db(tmp_path)
    conn = get_db_connection(db)
    save_daily_activity({"date": TODAY.isoformat(), "steps": 4000, "calories_kcal": 1000.0}, conn)
    conn.commit()
    conn.close()
    t = get_today_summary(db_path=db, today=TODAY)
    assert t["baseline"] == {"sleep_minutes": None, "activity_minutes": None, "steps": None, "calories_kcal": None}
    assert t["pct"]["steps"] is None and t["steps"] == 4000


# ---- sync status ----------------------------------------------------------------------------

def _patch_token(monkeypatch, result=None, exc=None):
    class Fake:
        def validate_token_status(self):
            if exc:
                raise exc
            return result
    monkeypatch.setattr(coros_client, "CorosMCPClient", Fake)


@pytest.mark.parametrize("token,state", [
    ({"is_authenticated": True, "token_exists": True, "status_code": "CONNECTED", "message": "ok",
      "expires_at": "2026-11-01T00:00:00Z"}, "connected"),
    ({"is_authenticated": False, "token_exists": True, "status_code": "TOKEN_EXPIRED", "message": "exp"}, "expired"),
    ({"is_authenticated": False, "token_exists": False, "status_code": "NOT_CONNECTED", "message": "no"}, "disconnected"),
])
def test_sync_status_states(tmp_path, monkeypatch, token, state):
    _patch_token(monkeypatch, token)
    s = get_sync_status(_db(tmp_path))
    assert s["state"] == state and s["status_code"] == token["status_code"]
    assert s["token_expires_at"] == token.get("expires_at")
    assert s["last_sync_iso"] is None and s["last_sync_status"] is None


def test_sync_status_last_sync_and_failure(tmp_path, monkeypatch):
    _patch_token(monkeypatch, exc=RuntimeError("boom"))
    db = _db(tmp_path)
    conn = get_db_connection(db)
    conn.execute("INSERT INTO sync_logs (sync_type, status, records_fetched, timestamp) "
                 "VALUES ('INCREMENTAL','SUCCESS',3,'2026-10-02 10:00:00')")
    conn.execute("INSERT INTO sync_logs (sync_type, status, records_fetched, error_message, timestamp) "
                 "VALUES ('INCREMENTAL','FAILED',0,'COROS down','2026-10-03 01:00:00')")
    conn.commit()
    conn.close()
    s = get_sync_status(db)
    assert s["last_sync_iso"] == "2026-10-02T10:00:00Z"
    assert s["last_sync_status"] == "FAILED" and s["last_sync_message"] == "COROS down"
    assert s["state"] == "disconnected" and "RuntimeError" in s["token_message"]


def test_validate_token_status_is_file_based(tmp_path, monkeypatch):
    import json
    import subprocess
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "x", "expires_at": 1e10}))
    monkeypatch.setattr(coros_client, "CACHE_TOKEN_PATH", str(token))
    monkeypatch.delenv("COROS_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess spawned"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess spawned"))
    db = _db(tmp_path)
    s = get_sync_status(db)
    assert s["state"] == "connected" and s["token_expires_at"] == "2286-11-20T17:46:40Z"
    token.write_text(json.dumps({"access_token": "x", "expires_at": 1000}))
    assert get_sync_status(db)["state"] == "expired"
    token.unlink()
    assert get_sync_status(db)["state"] == "disconnected"
