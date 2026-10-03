"""Deterministic fixtures for the e2e database (never the real coach.db)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

FULL_ACTIVITY_ID = "e2e_full_dynamics"
SPARSE_ACTIVITY_ID = "e2e_sparse"
OLD_ACTIVITY_ID = "e2e_old_run"
ESCAPE_ACTIVITY_ID = "e2e_escape"
FULL_ACTIVITY_NAME = "Dynamics Tempo"
OLD_ACTIVITY_NAME = "Ancient Base Run"
ESCAPE_ACTIVITY_NAME = "Escape <b>bold</b> & <i>test</i>"

TABLES = [
    "activity_splits", "plan_sessions", "training_plans", "activities", "sleep_records",
    "daily_physiology", "sync_logs", "user_profile", "block_summaries", "strength_workouts",
    "daily_activity", "race_watch_status",
]
TODAY_STEPS = 8421
TODAY_CALORIES = 1850.0


def _iso(days_ago: float, hour: int = 7) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=30, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_activity(conn, **kw) -> None:
    cols = ["id", "date", "sport_type", "name", "distance_m", "duration_s", "avg_pace_s_km",
            "elevation_gain_m", "elevation_loss_m", "gap_s_km", "avg_hr", "max_hr", "avg_cadence",
            "stride_length_cm", "ground_contact_time_ms", "vertical_oscillation_mm", "avg_power_w",
            "calories", "raw_payload"]
    row = {c: kw.get(c) for c in cols}
    row["raw_payload"] = json.dumps({k: v for k, v in kw.items() if k != "splits"})
    conn.execute(f"INSERT INTO activities ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [row[c] for c in cols])
    for i, s in enumerate(kw.get("splits", []), 1):
        conn.execute(
            "INSERT INTO activity_splits (id, activity_id, split_index, distance_m, duration_s, avg_pace_s_km,"
            " avg_hr, avg_cadence, elevation_gain_m) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{kw['id']}_s{i}", kw["id"], i, s["distance_m"], s["duration_s"], s["pace"], s["hr"], s["cad"], s["elev"]))


def wipe(db_path: str) -> None:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for t in TABLES:
            try:
                conn.execute(f"DELETE FROM {t}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()


def seed(db_path: str, with_plan: bool = True, with_strength: bool = True) -> None:
    """Wipe and re-seed activities, sleep, physiology, sync log, profile, plan and strength workout."""
    from app.data.db import init_db
    init_db(db_path)
    wipe(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        # Regular easy/tempo runs every 2 days for 60 days
        for n, days_ago in enumerate(range(1, 61, 2)):
            dist = 6000 + (n % 5) * 1500
            pace = 340 + (n % 4) * 12
            _insert_activity(
                conn, id=f"e2e_run_{days_ago}", date=_iso(days_ago), sport_type="Run",
                name=f"Easy Run {days_ago}d", distance_m=dist, duration_s=dist / 1000 * pace,
                avg_pace_s_km=pace, elevation_gain_m=30 + n, avg_hr=142 + n % 6, max_hr=165, calories=450.0,
            )
        # One activity with full running dynamics + splits
        _insert_activity(
            conn, id=FULL_ACTIVITY_ID, date=_iso(0.2), sport_type="Run", name=FULL_ACTIVITY_NAME,
            distance_m=10000, duration_s=2950, avg_pace_s_km=295, elevation_gain_m=85, elevation_loss_m=80,
            gap_s_km=290, avg_hr=158, max_hr=176, avg_cadence=178, stride_length_cm=112.0,
            ground_contact_time_ms=231, vertical_oscillation_mm=8.4, avg_power_w=262, calories=720.0,
            splits=[dict(distance_m=1000, duration_s=300 - i, pace=300 - i, hr=150 + i, cad=176 + i % 3, elev=8 + i)
                    for i in range(10)],
        )
        # Sparse activity: everything optional missing -> N/A badges
        _insert_activity(conn, id=SPARSE_ACTIVITY_ID, date=_iso(0.5), sport_type="Run", name="Sparse Shuffle",
                         distance_m=3000, duration_s=1200)
        _insert_activity(conn, id=ESCAPE_ACTIVITY_ID, date=_iso(3), sport_type="Run", name=ESCAPE_ACTIVITY_NAME,
                         distance_m=5000, duration_s=1700, avg_pace_s_km=340, avg_hr=150)
        # Older than 90 days: only visible under "All Time"
        _insert_activity(conn, id=OLD_ACTIVITY_ID, date=_iso(200), sport_type="Run", name=OLD_ACTIVITY_NAME,
                         distance_m=8000, duration_s=2800, avg_pace_s_km=350, avg_hr=145)

        for d in range(0, 14):
            day = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO sleep_records (id, date, total_sleep_minutes, sleep_score, deep_sleep_minutes,"
                " light_sleep_minutes, rem_sleep_minutes, awake_minutes) VALUES (?,?,?,?,?,?,?,?)",
                (f"sleep_{day}", day, 420 + (d % 4) * 15, 78 + d % 9, 80, 250, 90, 20))
        for d in range(0, 35):
            day = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO daily_physiology (id, date, resting_hr, hrv_score, rmssd_ms, vo2max, acute_load,"
                " chronic_load, fatigue_index, recovery_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"physio_{day}", day, 48 + d % 3, 62 + d % 7, 62 + d % 7, 54.0, 310 + d % 20, 300, 1.03, 85))
        # Today's steps / calories (home dials): server-local date and UTC date (they may differ)
        from datetime import date as _date
        for day in {_date.today().isoformat(), datetime.now(timezone.utc).strftime("%Y-%m-%d")}:
            conn.execute("INSERT OR REPLACE INTO daily_activity (date, steps, calories_kcal, exercise_minutes,"
                         " stress_avg, raw_payload, synced_at) VALUES (?,?,?,?,?,?,datetime('now'))",
                         (day, TODAY_STEPS, TODAY_CALORIES, 42.0, 30.0, "e2e fixture"))
            conn.execute("INSERT OR IGNORE INTO sleep_records (id, date, total_sleep_minutes, sleep_score,"
                         " deep_sleep_minutes, light_sleep_minutes, rem_sleep_minutes, awake_minutes)"
                         " VALUES (?,?,?,?,?,?,?,?)", (f"sleep_{day}", day, 420, 80, 80, 250, 90, 20))
        conn.execute("INSERT INTO sync_logs (timestamp, sync_type, status, records_fetched, duration_ms)"
                     " VALUES (datetime('now','-1 day'), 'INCREMENTAL', 'SUCCESS', 12, 900)")
        conn.commit()
    finally:
        conn.close()

    from app.data.queries import save_user_profile, save_training_plan, save_strength_workout
    race = (datetime.now(timezone.utc) + timedelta(days=100)).strftime("%Y-%m-%d")
    save_user_profile({
        "race_distance_type": "Marathon", "race_date": race, "target_time_str": "3:30:00",
        "weekly_hours_available": 7.0, "available_days": "Mon,Tue,Thu,Sat,Sun",
        "injury_history": "None", "current_niggles": "None",
    }, db_path=db_path)
    if with_plan:
        from app.engine.planner import TrainingPlanner
        save_training_plan(TrainingPlanner(db_path=db_path).generate_plan(), db_path=db_path)
    if with_strength:
        from app.engine.strength import StrengthEngine
        save_strength_workout(StrengthEngine(db_path=db_path).generate_workout(), db_path=db_path)
