"""SQLite Database Layer.

Manages database connections, migrations, and schema initialization.
"""
import os
import sqlite3
from typing import Optional

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "coach.db")

def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a SQLite database connection with row factory configured."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def _backfill_plan_dates(conn: sqlite3.Connection) -> None:
    """Give legacy single-week plans concrete dates: start = Monday of the created_at week."""
    from datetime import date, timedelta
    for plan in conn.execute("SELECT id, created_at FROM training_plans WHERE start_date IS NULL").fetchall():
        try:
            created = date.fromisoformat(str(plan["created_at"])[:10])
        except (TypeError, ValueError):
            created = date.today()
        monday = created - timedelta(days=created.weekday())
        conn.execute(
            "UPDATE training_plans SET start_date = ?, end_date = ?, total_weeks = COALESCE(total_weeks, 1) WHERE id = ?",
            (monday.isoformat(), (monday + timedelta(days=6)).isoformat(), plan["id"]))
    for s in conn.execute(
        "SELECT s.id, s.day_of_week, p.start_date FROM plan_sessions s JOIN training_plans p ON p.id = s.plan_id "
        "WHERE s.session_date IS NULL AND p.start_date IS NOT NULL").fetchall():
        offset = _WEEKDAYS.index(s["day_of_week"]) if s["day_of_week"] in _WEEKDAYS else 0
        day = date.fromisoformat(s["start_date"]) + timedelta(days=offset)
        conn.execute("UPDATE plan_sessions SET session_date = ?, week_number = COALESCE(week_number, 1) WHERE id = ?",
                     (day.isoformat(), s["id"]))

def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database with schema tables and perform column migrations."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_db_connection(db_path)
    try:
        conn.executescript(schema_sql)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(plan_sessions)")
        cols = {row["name"] for row in cursor.fetchall()}
        new_cols = [
            ("matched_activity_id", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'Pending'"),
            ("user_notes", "TEXT"),
            ("actual_distance_km", "REAL"),
            ("actual_duration_min", "REAL"),
            ("actual_avg_pace_s_km", "REAL"),
            ("actual_avg_hr", "INTEGER"),
            ("post_run_feedback", "TEXT"),
            ("adherence_score", "REAL"),
            ("adherence_rating", "TEXT"),
            ("session_date", "TEXT"),
            ("week_number", "INTEGER"),
            # Session adjustments (swap / missed + rebalance): the original prescription is kept for honest compliance
            ("original_session_type", "TEXT"),
            ("original_distance_km", "REAL"),
            ("original_duration_min", "REAL"),
            ("adjustment_kind", "TEXT"),
            ("adjustment_reason", "TEXT"),
            ("adjustment_note", "TEXT"),
            ("adjusted_at", "TEXT")
        ]
        for col_name, col_def in new_cols:
            if col_name not in cols:
                cursor.execute(f"ALTER TABLE plan_sessions ADD COLUMN {col_name} {col_def}")

        cursor.execute("PRAGMA table_info(training_plans)")
        plan_cols = {row["name"] for row in cursor.fetchall()}
        for col_name, col_def in [("start_date", "TEXT"), ("end_date", "TEXT"), ("total_weeks", "INTEGER"),
                                 ("decisions_json", "TEXT")]:  # planner decisions + evidence (JSON)
            if col_name not in plan_cols:
                cursor.execute(f"ALTER TABLE training_plans ADD COLUMN {col_name} {col_def}")
        if "status" not in plan_cols:
            # active | superseded | discarded. Only the newest pre-existing plan stays active.
            cursor.execute("ALTER TABLE training_plans ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            cursor.execute("""
                UPDATE training_plans SET status = 'superseded'
                WHERE rowid != (SELECT rowid FROM training_plans ORDER BY created_at DESC, rowid DESC LIMIT 1)
            """)
        _backfill_plan_dates(conn)

        cursor.execute("PRAGMA table_info(user_profile)")
        profile_cols = {row["name"] for row in cursor.fetchall()}
        if "gemini_api_key" not in profile_cols:
            cursor.execute("ALTER TABLE user_profile ADD COLUMN gemini_api_key TEXT")

        cursor.execute("PRAGMA table_info(activities)")
        act_cols = {row["name"] for row in cursor.fetchall()}
        if "details_synced_at" not in act_cols:
            cursor.execute("ALTER TABLE activities ADD COLUMN details_synced_at TIMESTAMP")
        for col_name, col_def in (("details_attempts", "INTEGER DEFAULT 0"),
                                  ("details_last_error", "TEXT"),
                                  ("details_last_attempt_at", "TIMESTAMP")):
            if col_name not in act_cols:
                cursor.execute(f"ALTER TABLE activities ADD COLUMN {col_name} {col_def}")

        # Daily activity totals from queryDailyHealthData (NULL = not reported by COROS)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_activity (
                date TEXT PRIMARY KEY,
                steps INTEGER,
                calories_kcal REAL,
                exercise_minutes REAL,
                stress_avg REAL,
                raw_payload TEXT,
                synced_at TEXT
            )""")

        # Race watchlist scan state (app/races)
        from app.races.store import ensure_table as _ensure_race_table
        _ensure_race_table(conn)

        # Upgrade plans saved with the old generic targets to explicit HR/Pace focus + ranges
        from app.engine.targets import normalize_target
        for row in cursor.execute("SELECT id, target_pace_or_hr FROM plan_sessions").fetchall():
            upgraded = normalize_target(row["target_pace_or_hr"])
            if upgraded != row["target_pace_or_hr"]:
                conn.execute("UPDATE plan_sessions SET target_pace_or_hr = ? WHERE id = ?", (upgraded, row["id"]))

        conn.commit()
    finally:
        conn.close()

    from app.data.queries import seed_strength_exercises_if_empty
    seed_strength_exercises_if_empty(db_path)


