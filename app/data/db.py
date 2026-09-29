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
            ("adherence_rating", "TEXT")
        ]
        for col_name, col_def in new_cols:
            if col_name not in cols:
                cursor.execute(f"ALTER TABLE plan_sessions ADD COLUMN {col_name} {col_def}")

        cursor.execute("PRAGMA table_info(user_profile)")
        profile_cols = {row["name"] for row in cursor.fetchall()}
        if "gemini_api_key" not in profile_cols:
            cursor.execute("ALTER TABLE user_profile ADD COLUMN gemini_api_key TEXT")

        conn.commit()
    finally:
        conn.close()

    from app.data.queries import seed_strength_exercises_if_empty
    seed_strength_exercises_if_empty(db_path)


