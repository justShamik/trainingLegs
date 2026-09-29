"""Unit tests for SQLite database schema initialization and table structures."""
import os
import sqlite3
import pytest
from app.data.db import init_db, get_db_connection

TEST_DB_PATH = "test_coach.db"

@pytest.fixture(autouse=True)
def setup_teardown_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    init_db(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

def test_tables_created():
    conn = get_db_connection(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()
    
    expected_tables = ["activities", "activity_splits", "sleep_records", "daily_physiology", "sync_logs"]
    for t in expected_tables:
        assert t in tables

def test_activity_insert_and_query():
    conn = get_db_connection(TEST_DB_PATH)
    conn.execute(
        """
        INSERT INTO activities (id, date, sport_type, distance_m, duration_s, avg_pace_s_km)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("act-001", "2026-09-20T08:00:00Z", "Run", 10000.0, 3000.0, 300.0)
    )
    conn.commit()
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activities WHERE id = ?", ("act-001",))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["distance_m"] == 10000.0
    assert row["stride_length_cm"] is None  # Missing field persists as NULL
