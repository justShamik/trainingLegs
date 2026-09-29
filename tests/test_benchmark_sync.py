"""Performance benchmark test for 1-year data ingestion (NFR-5.2 / AC-1.8)."""
import os
import time
from unittest.mock import MagicMock
import pytest
from app.data.db import init_db
from app.data.sync import perform_sync

BENCHMARK_DB = "benchmark_coach.db"

def test_12_month_sync_under_60_seconds():
    if os.path.exists(BENCHMARK_DB):
        os.remove(BENCHMARK_DB)
    init_db(BENCHMARK_DB)

    # Generate 1 year of realistic training payload (365 activities, splits, sleep, physiology)
    mock_workouts = []
    mock_sleep = []
    mock_physio = []
    
    for i in range(365):
        date_str = f"2025-09-{i%30+1:02d}T07:00:00Z"
        mock_workouts.append({
            "id": f"act-bench-{i}",
            "date": date_str,
            "sport_type": "Run",
            "name": f"Workout #{i}",
            "distance_m": 10000.0,
            "duration_s": 3000.0,
            "avg_pace_s_km": 300.0,
            "elevation_gain_m": 150.0,
            "avg_hr": 150,
            "avg_cadence": 172,
            "splits": [
                {"id": f"act-bench-{i}_split_{j}", "split_index": j, "distance_m": 1000.0, "duration_s": 300.0}
                for j in range(5)
            ]
        })
        mock_sleep.append({
            "id": f"sleep-bench-{i}",
            "date": f"2025-09-{i%30+1:02d}",
            "total_sleep_minutes": 450,
            "sleep_score": 80
        })
        mock_physio.append({
            "id": f"physio-bench-{i}",
            "date": f"2025-09-{i%30+1:02d}",
            "resting_hr": 50,
            "hrv_score": 70.0,
            "acute_load": 500.0,
            "chronic_load": 520.0
        })
        
    client = MagicMock()
    client.fetch_workouts.return_value = mock_workouts
    client.fetch_sleep_records.return_value = mock_sleep
    client.fetch_daily_physiology.return_value = mock_physio

    start_t = time.time()
    success, records_count, msg, duration_ms = perform_sync(client=client, full=True, db_path=BENCHMARK_DB)
    elapsed_seconds = time.time() - start_t

    print(f"\n[BENCHMARK RESULT] Ingested {records_count} records in {elapsed_seconds:.3f} seconds ({duration_ms}ms).")

    if os.path.exists(BENCHMARK_DB):
        os.remove(BENCHMARK_DB)

    assert success is True
    assert records_count == 365 * 3
    assert elapsed_seconds < 60.0, f"Sync took {elapsed_seconds:.2f}s, exceeding 60s limit!"
