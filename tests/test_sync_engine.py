"""Unit test suite for Sync Engine functionality.

Tests full sync, incremental sync, idempotency (zero duplicate records on re-run),
missing field NULL preservation, and failure logging / transaction safety.
"""
import os
import sqlite3
from unittest.mock import MagicMock
import pytest
from app.data.db import init_db, get_db_connection
from app.data.sync import perform_sync, get_last_successful_sync_timestamp

TEST_DB_PATH = "test_sync_engine.db"

@pytest.fixture(autouse=True)
def setup_teardown():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    init_db(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

def create_mock_client():
    client = MagicMock()
    client.fetch_workouts.return_value = [
        {
            "id": "act-101",
            "date": "2026-09-01T07:00:00Z",
            "sport_type": "Run",
            "name": "Morning Easy Run",
            "distance_m": 8000.0,
            "duration_s": 2400.0,
            "avg_pace_s_km": 300.0,
            "avg_hr": 145,
            # missing fields: elevation_gain_m, stride_length_cm, ground_contact_time_ms
            "splits": [
                {
                    "id": "act-101_split_1",
                    "split_index": 1,
                    "distance_m": 1000.0,
                    "duration_s": 300.0,
                    "avg_pace_s_km": 300.0,
                    "avg_hr": 140
                }
            ]
        }
    ]
    client.fetch_sleep_records.return_value = [
        {
            "id": "sleep-2026-09-01",
            "date": "2026-09-01",
            "total_sleep_minutes": 480,
            "sleep_score": 85,
            "deep_sleep_minutes": 120
            # missing fields: light, rem, awake
        }
    ]
    client.fetch_daily_physiology.return_value = [
        {
            "id": "physio-2026-09-01",
            "date": "2026-09-01",
            "resting_hr": 52,
            "hrv_score": 68.5,
            "vo2max": 54.0,
            "acute_load": 450.0,
            "chronic_load": 480.0
            # missing fields: weight_kg, rmssd_ms
        }
    ]
    return client

def test_full_sync_ingestion_and_null_preservation():
    client = create_mock_client()
    success, count, msg, duration = perform_sync(client=client, full=True, db_path=TEST_DB_PATH)
    
    assert success is True
    assert count == 3
    
    conn = get_db_connection(TEST_DB_PATH)
    cursor = conn.cursor()
    
    # Check activity & missing field NULL preservation
    cursor.execute("SELECT * FROM activities WHERE id = 'act-101'")
    act = cursor.fetchone()
    assert act is not None
    assert act["distance_m"] == 8000.0
    assert act["elevation_gain_m"] is None  # Preserved as NULL, not fabricated
    assert act["stride_length_cm"] is None  # Preserved as NULL
    
    # Check split
    cursor.execute("SELECT * FROM activity_splits WHERE activity_id = 'act-101'")
    split = cursor.fetchone()
    assert split is not None
    assert split["distance_m"] == 1000.0
    
    # Check sync_logs
    cursor.execute("SELECT * FROM sync_logs WHERE status = 'SUCCESS'")
    log = cursor.fetchone()
    assert log is not None
    assert log["sync_type"] == "FULL"
    assert log["records_fetched"] == 3
    
    conn.close()

def test_idempotency_zero_duplicates_on_rerun():
    client = create_mock_client()
    
    # First sync
    perform_sync(client=client, full=True, db_path=TEST_DB_PATH)
    
    conn = get_db_connection(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM activities")
    initial_act_count = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM sleep_records")
    initial_sleep_count = cursor.fetchone()["count"]
    conn.close()
    
    # Second sync (re-running identical payload)
    perform_sync(client=client, full=False, db_path=TEST_DB_PATH)
    
    conn = get_db_connection(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM activities")
    second_act_count = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM sleep_records")
    second_sleep_count = cursor.fetchone()["count"]
    conn.close()
    
    assert initial_act_count == second_act_count == 1
    assert initial_sleep_count == second_sleep_count == 1

def test_sync_failure_logging_and_transaction_safety():
    client = MagicMock()
    client.fetch_workouts.side_effect = Exception("COROS Server 503 Service Unavailable")
    
    success, count, msg, duration = perform_sync(client=client, full=True, db_path=TEST_DB_PATH)
    
    assert success is False
    assert count == 0
    assert "COROS Server 503" in msg
    
    conn = get_db_connection(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM activities")
    assert cursor.fetchone()["count"] == 0
    
    cursor.execute("SELECT * FROM sync_logs WHERE status = 'FAILED'")
    failed_log = cursor.fetchone()
    assert failed_log is not None
    assert "COROS Server 503" in failed_log["error_message"]
    conn.close()
