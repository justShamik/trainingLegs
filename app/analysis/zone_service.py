"""Zone-test workflow: pick a run, fetch its per-second file (cached), analyse it, store and read results."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.analysis import hr_zones as hz
from app.data.db import get_db_connection

RETEST_DAYS = 56
CANDIDATE_MIN_S = 40 * 60
LIKELY_NAME = re.compile(r"lthr|zone\s*test|threshold\s*test|time\s*trial|\btt\b|30\s*-?\s*min", re.I)
USABLE = ("Good", "Fair")


def _db_path(db_path: Optional[str]) -> str:
    return db_path or os.environ.get("DATABASE_PATH", "coach.db")


def _cache_dir(db_path: Optional[str]) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(_db_path(db_path))), "fit_cache")


def list_candidates(db_path: Optional[str] = None, today: Optional[date] = None, days: int = 120) -> List[Dict[str, Any]]:
    """Runs of 40+ minutes in the last `days`, newest first; `likely` when the title looks like a test."""
    today = today or date.today()
    conn = get_db_connection(db_path)
    rows = conn.execute(
        "SELECT id, date, name, sport_type, distance_m, duration_s, avg_hr FROM activities "
        "WHERE LOWER(COALESCE(sport_type, '')) LIKE '%run%' AND duration_s >= ? AND substr(date, 1, 10) >= ? "
        "ORDER BY date DESC LIMIT 40",
        (CANDIDATE_MIN_S, (today - timedelta(days=days)).isoformat())).fetchall()
    tested = {r["activity_id"] for r in conn.execute("SELECT activity_id FROM hr_zone_tests")}
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["likely"] = bool(LIKELY_NAME.search(d.get("name") or ""))
        d["tested"] = d["id"] in tested
        d["duration_min"] = round((d["duration_s"] or 0) / 60)
        d["distance_km"] = round((d["distance_m"] or 0) / 1000, 2)
        out.append(d)
    return out


def _observed_max_hr(conn) -> Optional[int]:
    row = conn.execute(
        "SELECT MAX(max_hr) AS hr FROM activities WHERE LOWER(COALESCE(sport_type, '')) LIKE '%run%' "
        "AND max_hr BETWEEN 140 AND 230 AND substr(date, 1, 10) >= ?",
        ((date.today() - timedelta(days=365)).isoformat(),)).fetchone()
    return int(row["hr"]) if row and row["hr"] else None


def _load_fit(client, activity_id: str, sport_code: int, db_path: Optional[str]) -> Optional[bytes]:
    path = os.path.join(_cache_dir(db_path), re.sub(r"[^\w-]", "_", activity_id) + ".fit")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    data = client.fetch_fit_bytes(activity_id, sport_code)
    if data:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return data


def analyse_activity(activity_id: str, sensor: Optional[str] = None, temperature_c: Optional[float] = None,
                     db_path: Optional[str] = None, client=None) -> int:
    """Analyse a synced run as a 30-min LTHR test and store the result. Raises hz.ZoneTestError with a
    plain-language reason when it can't be used. Returns the new test id."""
    from app.mcp_client.coros_client import CorosMCPClient

    conn = get_db_connection(db_path)
    act = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    conn.close()
    if not act:
        raise hz.ZoneTestError("That activity isn't in your synced data.")
    sport_code = CorosMCPClient.running_sport_code(act["sport_type"])
    if sport_code is None:
        raise hz.ZoneTestError("Only runs can be used as a zone test.")
    if (act["duration_s"] or 0) < hz.TEST_S:
        raise hz.ZoneTestError("The run is shorter than 30 minutes, so it can't contain the test.")
    sensor = sensor if sensor in hz.SENSORS else None

    client = client or CorosMCPClient()
    laps = client.fetch_lap_list(activity_id, sport_code)
    window = hz.window_from_laps(laps) if laps else None
    fit = _load_fit(client, activity_id, sport_code, db_path)

    if fit:
        parsed = hz.parse_fit(fit)
        start = window["start_s"] if window else hz.window_auto(parsed["samples"])
        if start is None:
            raise hz.ZoneTestError("Couldn't find a 30-minute test effort in this run.")
        result = hz.analyse_samples(parsed["samples"], start, sensor, temperature_c)
        result["window_source"] = window["source"] if window else "fastest 30 minutes (no 10:00 lap found)"
    elif window and window.get("lap_avg_hr"):
        result = hz.analyse_lap_window(window, sensor, temperature_c)
        result["window_source"] = window["source"]
    else:
        failures = "; ".join(getattr(client, "call_failures", [])[-3:])
        raise hz.ZoneTestError("Couldn't get per-second data or a 10:00 + 20:00 lap split from COROS"
                               + (f" ({failures})" if failures else "") + ". Check the COROS connection and try again.")

    result["stats"]["window_source"] = result.pop("window_source")
    conn = get_db_connection(db_path)
    max_hr = _observed_max_hr(conn)
    cur = conn.execute(
        "INSERT INTO hr_zone_tests (activity_id, test_date, lthr, confidence, method, sensor, temperature_c, "
        "invalid_reason, criteria_json, flags_json, stats_json, observed_max_hr) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (activity_id, str(act["date"])[:10], result["lthr"], result["confidence"], result["method"], sensor,
         temperature_c, result["invalid_reason"], json.dumps(result["criteria"]), json.dumps(result["flags"]),
         json.dumps(result["stats"]), max_hr))
    conn.commit()
    test_id = cur.lastrowid
    conn.close()
    return test_id


def _hydrate(row) -> Dict[str, Any]:
    t = dict(row)
    for key in ("criteria", "flags", "stats"):
        t[key] = json.loads(t.pop(f"{key}_json") or ("{}" if key == "stats" else "[]"))
    t["zones"] = hz.coros_lt_zones(t["lthr"])
    t["sensor_label"] = hz.SENSORS.get(t.get("sensor") or "", "Not stated")
    return t


def get_tests(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    rows = conn.execute(
        "SELECT t.*, a.name AS activity_name FROM hr_zone_tests t LEFT JOIN activities a ON a.id = t.activity_id "
        "ORDER BY t.test_date DESC, t.id DESC").fetchall()
    conn.close()
    tests = [_hydrate(r) for r in rows]
    for i, t in enumerate(tests):
        prev = next((p for p in tests[i + 1:] if p["confidence"] in USABLE), None)
        t["recommendation"] = hz.recommendation(t, prev["lthr"] if prev else None, t.get("observed_max_hr"))
    return tests


def current_lthr(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Latest test with Good or Fair confidence: the threshold HR the coach uses for targets."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM hr_zone_tests WHERE confidence IN ('Good', 'Fair') ORDER BY test_date DESC, id DESC LIMIT 1"
        ).fetchone()
    except Exception:  # table not created yet (old database opened without init_db)
        row = None
    conn.close()
    return _hydrate(row) if row else None


def test_due(db_path: Optional[str] = None, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    cur = current_lthr(db_path)
    if not cur:
        return {"due": True, "last_date": None, "reason": "No usable zone test yet."}
    last = date.fromisoformat(cur["test_date"])
    age = (today - last).days
    if age >= RETEST_DAYS:
        return {"due": True, "last_date": cur["test_date"], "reason": f"Last usable test was {age} days ago (retest every 6-8 weeks)."}
    return {"due": False, "last_date": cur["test_date"], "next_due": (last + timedelta(days=RETEST_DAYS)).isoformat(),
            "reason": f"Last usable test was {age} days ago."}


def mark_entered(test_id: int, db_path: Optional[str] = None) -> None:
    conn = get_db_connection(db_path)
    conn.execute("UPDATE hr_zone_tests SET entered_in_coros_at = ? WHERE id = ?",
                 (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), test_id))
    conn.commit()
    conn.close()


def delete_test(test_id: int, db_path: Optional[str] = None) -> None:
    conn = get_db_connection(db_path)
    conn.execute("DELETE FROM hr_zone_tests WHERE id = ?", (test_id,))
    conn.commit()
    conn.close()
