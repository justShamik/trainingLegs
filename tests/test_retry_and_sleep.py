"""Tests for the detail-enrichment retry counter and sleep ingestion via queryDailyHealthData."""
import os
from app.mcp_client.coros_client import CorosMCPClient
from app.data.db import init_db, get_db_connection
from app.data.sync import (save_activity, save_sleep_record, enrich_running_activities, perform_sync,
                           count_exhausted_details, reset_detail_attempts, MAX_DETAIL_ATTEMPTS)
from app.data.queries import get_activity_detail, get_dashboard_summary, get_trend_charts_data
from app.engine.tracking import detect_overtraining_risk

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class BadClient(CorosMCPClient):
    """Detail fetch fails for the ids in `bad`; others succeed with the real lap fixture."""
    def __init__(self, bad):
        super().__init__()
        self.bad = set(bad)
        self.fetched = []

    def _call_cli_tool(self, tool, args):
        if tool != "queryActivityLapData":
            return None
        self.fetched.append(args["labelId"])
        if args["labelId"] in self.bad:
            self.call_failures.append("queryActivityLapData: timeout")
            return None
        return _read("coros_lap_data_run.json")


def _seed(db, n):
    init_db(db)
    conn = get_db_connection(db)
    for i in range(n):
        save_activity({"id": str(1000 + i), "date": f"2026-09-{10 + i:02d}T08:00:00Z", "sport_type": "Outdoor Run",
                       "distance_m": 8000.0, "duration_s": 2900.0}, conn)
    conn.commit()
    conn.close()


def _row(db, act_id):
    conn = get_db_connection(db)
    try:
        return dict(conn.execute("SELECT * FROM activities WHERE id=?", (act_id,)).fetchone())
    finally:
        conn.close()


def test_failures_counted_then_skipped_after_max(tmp_path):
    db = str(tmp_path / "a.db")
    _seed(db, 1)
    c = BadClient(["1000"])
    for n in range(1, MAX_DETAIL_ATTEMPTS + 1):
        assert enrich_running_activities(c, db) == 0
        r = _row(db, "1000")
        assert r["details_attempts"] == n and "timeout" in r["details_last_error"] and r["details_last_attempt_at"]
    assert count_exhausted_details(db) == 1
    c.fetched.clear()
    enrich_running_activities(c, db)
    assert c.fetched == []  # skipped, no more calls
    assert _row(db, "1000")["details_attempts"] == MAX_DETAIL_ATTEMPTS


def test_failing_activities_do_not_starve_the_cap(tmp_path):
    db = str(tmp_path / "b.db")
    _seed(db, 4)  # 1003 newest ... 1000 oldest
    c = BadClient(["1003", "1002"])
    assert enrich_running_activities(c, db, limit=2) == 0  # newest two fail, attempts=1
    c.fetched.clear()
    assert enrich_running_activities(c, db, limit=2) == 2  # never-tried run first
    assert set(c.fetched) == {"1001", "1000"}
    assert _row(db, "1001")["details_synced_at"]


def test_success_clears_error_and_reason_text(tmp_path):
    db = str(tmp_path / "c.db")
    _seed(db, 1)
    enrich_running_activities(BadClient(["1000"]), db)
    assert "1 of 3" in get_activity_detail("1000", db)["na_reason"]
    enrich_running_activities(BadClient([]), db)
    r = _row(db, "1000")
    assert r["details_synced_at"] and r["details_attempts"] == 0 and r["details_last_error"] is None


def test_exhausted_reason_and_full_sync_resets(tmp_path):
    db = str(tmp_path / "d.db")
    _seed(db, 1)
    bad = BadClient(["1000"])
    for _ in range(MAX_DETAIL_ATTEMPTS):
        enrich_running_activities(bad, db)
    assert "failed 3 times" in get_activity_detail("1000", db)["na_reason"]

    class SyncClient(BadClient):
        def is_authenticated(self): return True
        def fetch_workouts(self, since_date=None): return []
        def fetch_sleep_records(self, since_date=None): return []
        def fetch_daily_physiology(self, since_date=None):
            return [{"id": "physio_2026-09-20", "date": "2026-09-20", "resting_hr": 50}]

    ok, _, msg, _ = perform_sync(SyncClient(["1000"]), full=False, db_path=db)
    assert ok and "1 activities could not be enriched after 3 attempts" in msg
    ok, _, msg, _ = perform_sync(SyncClient([]), full=True, db_path=db)  # reset -> retried -> success
    assert ok and "1 run details enriched" in msg and "could not be enriched" not in msg
    assert _row(db, "1000")["details_synced_at"]


def test_reset_detail_attempts(tmp_path):
    db = str(tmp_path / "e.db")
    _seed(db, 1)
    for _ in range(MAX_DETAIL_ATTEMPTS):
        enrich_running_activities(BadClient(["1000"]), db)
    reset_detail_attempts(db)
    assert _row(db, "1000")["details_attempts"] == 0 and count_exhausted_details(db) == 0


# ---- sleep -------------------------------------------------------------------------------

def test_parse_daily_health_sleep_real_output():
    recs = CorosMCPClient()._parse_daily_health_sleep(_read("coros_daily_health_365.txt"))
    assert len(recs) > 300
    by = {r["date"]: r for r in recs}
    n = by["2026-09-24"]  # Total 8h 3min | Deep 1h 33 | Light 4h 19 | REM 1h 56 | Awake 15
    assert n["total_sleep_minutes"] == 483
    assert (n["deep_sleep_minutes"], n["light_sleep_minutes"], n["rem_sleep_minutes"], n["awake_minutes"]) == (93, 259, 116, 15)
    assert (n["sleep_hr_avg"], n["sleep_hr_min"], n["sleep_hr_max"]) == (51, 43, 63)
    assert all(r["sleep_score"] is None for r in recs)  # COROS gives none; never invented
    no_split = by["2026-04-21"]  # stages all zero -> unknown, not zero
    assert no_split["total_sleep_minutes"] == 226 and no_split["deep_sleep_minutes"] is None
    assert no_split["awake_minutes"] is None
    assert "2025-11-24" not in by  # day without a Sleep Summary is skipped


def test_fetch_sleep_records_uses_working_tool_and_window():
    class C(CorosMCPClient):
        def _call_cli_tool(self, tool, args):
            self.last = (tool, args)
            return _read("coros_daily_health_365.txt")
    c = C()
    assert c.fetch_sleep_records()
    assert c.last == ("queryDailyHealthData", {"days": 30})
    c.fetch_sleep_records(since_date="2020-01-01T00:00:00Z")
    assert c.last[1]["days"] == 365


def test_sleep_dashboard_degrades_without_score(tmp_path):
    db = str(tmp_path / "s.db")
    init_db(db)
    conn = get_db_connection(db)
    for r in CorosMCPClient()._parse_daily_health_sleep(_read("coros_daily_health_365.txt"))[-5:]:
        save_sleep_record(r, conn)
    conn.commit()
    conn.close()
    summary = get_dashboard_summary(db)
    assert summary["latest_sleep"]["sleep_score"] is None
    trend = get_trend_charts_data(db)["sleep_trend"]
    assert trend["has_score"] is False and len(trend["deep_hours"]) == 5
    assert detect_overtraining_risk(db)["low_sleep_days"] == 0
    from app.llm.context_builder import build_runner_context
    assert "not provided by COROS" in build_runner_context(db)
    from app.web.routes import create_app
    html = create_app(db).test_client().get("/dashboard").get_data(as_text=True)
    assert "Sleep score not provided by COROS" in html
