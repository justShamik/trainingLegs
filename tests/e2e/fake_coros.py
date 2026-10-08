"""Test-only stand-ins for COROS and Gemini so e2e runs are deterministic and offline.

Installed by ``tests/e2e/server_main.py`` (production code is untouched).  Behaviour is
controlled at runtime through a mode file (``COACH_E2E_MODE_FILE``) containing one of:

    ok        authenticated, sync succeeds (default)
    fail      authenticated, every COROS call fails -> sync error banner
    unauth    no COROS token -> login required flow
    expired   token file present but expired -> "Token expired - reconnect"

Race-website checks (POST /races/refresh) never touch the network: ``fake_race_fetch`` serves a
canned page for every URL.

``COACH_E2E_SYNC_DELAY`` (seconds, default 1.0) keeps the sync in flight long enough for
the loading overlay to be observed.  ``COACH_E2E_FAKE_COROS=0`` disables the whole shim.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone


def _mode() -> str:
    path = os.environ.get("COACH_E2E_MODE_FILE")
    if path and os.path.exists(path):
        try:
            return open(path, encoding="utf-8").read().strip() or "ok"
        except OSError:
            pass
    return "ok"


def _day(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


class FakeCorosMCPClient:
    """Duck-typed replacement for CorosMCPClient."""

    def __init__(self, *args, **kwargs) -> None:
        self.call_failures = []
        self._full = False

    def is_authenticated(self) -> bool:
        return _mode() not in ("unauth", "expired")

    def validate_token_status(self) -> dict:
        if _mode() == "expired":
            return {"is_authenticated": False, "token_exists": True, "status_code": "TOKEN_EXPIRED",
                    "message": "COROS Token expired or invalid. Please re-authenticate.", "expires_at": None}
        if _mode() == "unauth":
            return {"is_authenticated": False, "token_exists": False, "status_code": "NOT_CONNECTED",
                    "message": "COROS token missing. Browser authentication required."}
        return {"is_authenticated": True, "token_exists": True, "status_code": "CONNECTED",
                "message": "COROS Account Authenticated & Token Valid"}

    def trigger_login_flow(self) -> bool:
        return True

    def _delay(self) -> None:
        time.sleep(float(os.environ.get("COACH_E2E_SYNC_DELAY", "1.0")))

    def _maybe_fail(self, tool: str) -> bool:
        if _mode() == "fail":
            self.call_failures.append(f"{tool}: simulated COROS outage")
            return True
        return False

    def fetch_workouts(self, since_date=None):
        self._delay()
        if self._maybe_fail("querySportRecords"):
            return []
        full = since_date is not None and since_date[:4].isdigit() and \
            (datetime.now(timezone.utc) - datetime.strptime(since_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days >= 300
        items = [{
            "id": "fake_sync_new", "date": f"{_day(0)}T09:00:00Z", "sport_type": "Run", "name": "Freshly Synced Run",
            "distance_m": 7000.0, "duration_s": 2300.0, "avg_pace_s_km": 328, "avg_hr": 147, "calories": 500.0,
            "splits": [{"split_index": 1, "distance_m": 1000, "duration_s": 330, "avg_pace_s_km": 330, "avg_hr": 145}],
        }]
        if full:
            for k in (120, 150):
                items.append({"id": f"fake_hist_{k}", "date": f"{_day(k)}T09:00:00Z", "sport_type": "Run",
                              "name": f"Historic Run {k}d", "distance_m": 9000.0, "duration_s": 3100.0,
                              "avg_pace_s_km": 344, "avg_hr": 149})
        return items

    def fetch_sleep_records(self, since_date=None):
        return self.fetch_daily_health(since_date)[0]

    def fetch_daily_health(self, since_date=None):
        if self._maybe_fail("queryDailyHealthData"):
            return [], []
        sleep = [{"id": f"sleep_{_day(0)}", "date": _day(0), "total_sleep_minutes": 455, "sleep_score": 84}]
        activity = [{"date": _day(0), "steps": 8421, "calories_kcal": 1850.0, "exercise_minutes": 42.0,
                     "stress_avg": 30.0, "raw_payload": "Steps: 8,421 | Calories: 1,850 kcal | Exercise: 42 min"}]
        return sleep, activity

    def fetch_daily_physiology(self, since_date=None):
        if self._maybe_fail("queryTrainingLoadAssessment"):
            return []
        return [{"id": f"physio_{_day(0)}", "date": _day(0), "acute_load": 320.0, "chronic_load": 300.0,
                 "fatigue_index": 1.07, "resting_hr": 49, "hrv_score": 65.0}]


    # ---- fake COROS calendar, kept in a JSON file next to the mode file (reset before every test)
    @staticmethod
    def _cal_path():
        return (os.environ.get("COACH_E2E_MODE_FILE") or "e2e_mode") + ".calendar.json"

    def _cal(self):
        import json
        try:
            with open(self._cal_path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"next_id": 1000, "days": {}, "writes": 0}

    def _save_cal(self, cal):
        import json
        with open(self._cal_path(), "w", encoding="utf-8") as f:
            json.dump(cal, f)

    def query_training_schedule(self, start, end):
        if self._maybe_fail("queryTrainingSchedule"):
            return None
        days = self._cal()["days"]
        return [{"date": d, "title": w["title"], "id_in_plan": w["id"], "in_plan": False, "standalone": True}
                for d in sorted(days) if start.isoformat() <= d <= end.isoformat() for w in days[d]]

    def create_scheduled_workout(self, day, course):
        if self._maybe_fail("createScheduledWorkout"):
            return False, None
        cal = self._cal()
        cal["next_id"] += 1
        cal["writes"] += 1
        cal["days"].setdefault(day.isoformat(), []).append({"id": str(cal["next_id"]), "title": course["courseName"]})
        self._save_cal(cal)
        return True, f"Workout created. idInPlan: {cal['next_id']}"

    def query_scheduled_workout(self, day, id_in_plan):
        return True, "editable: true"

    def update_scheduled_workout(self, day, id_in_plan, course):
        cal = self._cal()
        cal["writes"] += 1
        for w in cal["days"].get(day.isoformat(), []):
            if w["id"] == id_in_plan:
                w["title"] = course["courseName"]
        self._save_cal(cal)
        return True, f"Updated. idInPlan: {id_in_plan}"

    @staticmethod
    def running_sport_code(sport_name=None):
        return 100 if "run" in (sport_name or "").lower() else None

    def fetch_lap_list(self, label_id, sport_code=100):
        if self._maybe_fail("queryActivityLapData"):
            return []
        total, laps = 0.0, []
        for t, hr in ((900, 135), (600, 162), (1200, 168), (600, 140)):
            total += t
            laps.append({"time": t, "totalLength": total, "avgHr": hr})
        return laps

    def fetch_fit_bytes(self, label_id, sport_code=100):
        if self._maybe_fail("queryActivityFitFileDownloadUrls"):
            return None
        from tests.fit_builder import build_fit, synthetic_test_run
        return build_fit(synthetic_test_run(test_hr=168))


def _fake_ask_coach(self, question, runner_context, template_name="coach_chat_v1.txt", db_path=None):
    """Deterministic coach: echoes the question (to exercise HTML escaping) + data-driven fallback."""
    return f"E2E COACH ECHO: {question}\n\n" + self._generate_intelligent_fallback(question, runner_context)


FAKE_RACE_PAGE = ("<html><head><title>E2E race</title></head><body><h1>E2E race page</h1>"
                  "<p>Offline fixture served by tests/e2e/fake_coros.py</p></body></html>")


def fake_race_fetch(url):
    """Offline stand-in for the race scanner's HTTP fetch: (status, html)."""
    time.sleep(float(os.environ.get("COACH_E2E_RACE_DELAY", "0.05")))
    return 200, FAKE_RACE_PAGE


def install() -> None:
    """Patch every module that holds a reference to CorosMCPClient, plus Gemini's ask_coach."""
    if os.environ.get("COACH_E2E_FAKE_COROS", "1") == "0":
        return
    import app.web.routes  # noqa: F401  (make sure all consumers are imported first)
    import app.data.sync  # noqa: F401
    from app.mcp_client import coros_client
    from app.llm import gemini_cli

    original = coros_client.CorosMCPClient
    for mod in list(sys.modules.values()):
        if mod is not None and getattr(mod, "CorosMCPClient", None) is original:
            setattr(mod, "CorosMCPClient", FakeCorosMCPClient)
    gemini_cli.GeminiCLIWrapper.ask_coach = _fake_ask_coach

    from app.races import service as race_service
    real_refresh, real_discover = race_service.refresh_races, race_service.discover_candidates

    def refresh_races(*args, **kwargs):
        kwargs["fetch"] = fake_race_fetch
        return real_refresh(*args, **kwargs)

    def discover_candidates(*args, **kwargs):
        kwargs["fetch"] = fake_race_fetch
        return real_discover(*args, **kwargs)

    race_service.refresh_races = refresh_races
    race_service.discover_candidates = discover_candidates
