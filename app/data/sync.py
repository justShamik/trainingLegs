"""COROS Data Ingestion & Synchronization Engine.

Handles full and incremental data ingestion from COROS MCP server to local SQLite.
Ensures idempotency, transactional integrity, missing field NULL preservation, and audit logging.
"""
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from app.data.db import get_db_connection, init_db
from app.mcp_client.coros_client import CorosMCPClient

def get_last_successful_sync_timestamp(db_path: Optional[str] = None) -> Optional[str]:
    """Retrieve the timestamp of the last successful sync operation."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp FROM sync_logs WHERE status = 'SUCCESS' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row["timestamp"] if row else None
    finally:
        conn.close()

def log_sync_attempt(
    sync_type: str,
    status: str,
    records_fetched: int,
    error_message: Optional[str] = None,
    duration_ms: int = 0,
    db_path: Optional[str] = None
) -> None:
    """Record sync operation status into sync_logs table."""
    conn = get_db_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sync_logs (sync_type, status, records_fetched, error_message, duration_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sync_type, status, records_fetched, error_message, duration_ms)
        )
        conn.commit()
    finally:
        conn.close()

def save_activity(activity_data: Dict[str, Any], conn) -> None:
    """Save or update an activity record preserving missing fields as NULL."""
    sql = """
    INSERT INTO activities (
        id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km,
        elevation_gain_m, elevation_loss_m, gap_s_km, avg_hr, max_hr,
        avg_cadence, stride_length_cm, ground_contact_time_ms, vertical_oscillation_mm,
        avg_power_w, calories, raw_payload
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        date=excluded.date,
        sport_type=excluded.sport_type,
        name=excluded.name,
        distance_m=excluded.distance_m,
        duration_s=excluded.duration_s,
        avg_pace_s_km=excluded.avg_pace_s_km,
        elevation_gain_m=excluded.elevation_gain_m,
        elevation_loss_m=excluded.elevation_loss_m,
        gap_s_km=excluded.gap_s_km,
        avg_hr=excluded.avg_hr,
        max_hr=excluded.max_hr,
        avg_cadence=excluded.avg_cadence,
        stride_length_cm=excluded.stride_length_cm,
        ground_contact_time_ms=excluded.ground_contact_time_ms,
        vertical_oscillation_mm=excluded.vertical_oscillation_mm,
        avg_power_w=excluded.avg_power_w,
        calories=excluded.calories,
        raw_payload=excluded.raw_payload;
    """
    
    conn.execute(sql, (
        activity_data.get("id"),
        activity_data.get("date"),
        activity_data.get("sport_type", "Run"),
        activity_data.get("name"),
        activity_data.get("distance_m", 0.0),
        activity_data.get("duration_s", 0.0),
        activity_data.get("avg_pace_s_km"),
        activity_data.get("elevation_gain_m"),
        activity_data.get("elevation_loss_m"),
        activity_data.get("gap_s_km"),
        activity_data.get("avg_hr"),
        activity_data.get("max_hr"),
        activity_data.get("avg_cadence"),
        activity_data.get("stride_length_cm"),
        activity_data.get("ground_contact_time_ms"),
        activity_data.get("vertical_oscillation_mm"),
        activity_data.get("avg_power_w"),
        activity_data.get("calories"),
        json.dumps(activity_data)
    ))

    # Save splits if present
    splits = activity_data.get("splits", [])
    for split in splits:
        split_sql = """
        INSERT INTO activity_splits (
            id, activity_id, split_index, distance_m, duration_s,
            avg_pace_s_km, avg_hr, avg_cadence, elevation_gain_m
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            distance_m=excluded.distance_m,
            duration_s=excluded.duration_s,
            avg_pace_s_km=excluded.avg_pace_s_km,
            avg_hr=excluded.avg_hr,
            avg_cadence=excluded.avg_cadence,
            elevation_gain_m=excluded.elevation_gain_m;
        """
        conn.execute(split_sql, (
            split.get("id", f"{activity_data.get('id')}_split_{split.get('split_index', 0)}"),
            activity_data.get("id"),
            split.get("split_index", 0),
            split.get("distance_m", 0.0),
            split.get("duration_s", 0.0),
            split.get("avg_pace_s_km"),
            split.get("avg_hr"),
            split.get("avg_cadence"),
            split.get("elevation_gain_m")
        ))

def save_sleep_record(sleep_data: Dict[str, Any], conn) -> None:
    """Save or update a sleep record preserving missing fields as NULL."""
    sql = """
    INSERT INTO sleep_records (
        id, date, total_sleep_minutes, sleep_score,
        deep_sleep_minutes, light_sleep_minutes, rem_sleep_minutes, awake_minutes, raw_payload
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        total_sleep_minutes=excluded.total_sleep_minutes,
        sleep_score=excluded.sleep_score,
        deep_sleep_minutes=excluded.deep_sleep_minutes,
        light_sleep_minutes=excluded.light_sleep_minutes,
        rem_sleep_minutes=excluded.rem_sleep_minutes,
        awake_minutes=excluded.awake_minutes,
        raw_payload=excluded.raw_payload;
    """
    conn.execute(sql, (
        sleep_data.get("id", f"sleep_{sleep_data.get('date')}"),
        sleep_data.get("date"),
        sleep_data.get("total_sleep_minutes", 0),
        sleep_data.get("sleep_score"),
        sleep_data.get("deep_sleep_minutes"),
        sleep_data.get("light_sleep_minutes"),
        sleep_data.get("rem_sleep_minutes"),
        sleep_data.get("awake_minutes"),
        json.dumps(sleep_data)
    ))

def save_daily_physiology(physio_data: Dict[str, Any], conn) -> None:
    """Save or update daily physiology preserving missing fields as NULL."""
    sql = """
    INSERT INTO daily_physiology (
        id, date, resting_hr, avg_hr, hrv_score, rmssd_ms, vo2max,
        acute_load, chronic_load, fatigue_index, recovery_score, weight_kg, raw_payload
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        resting_hr=excluded.resting_hr,
        avg_hr=excluded.avg_hr,
        hrv_score=excluded.hrv_score,
        rmssd_ms=excluded.rmssd_ms,
        vo2max=excluded.vo2max,
        acute_load=excluded.acute_load,
        chronic_load=excluded.chronic_load,
        fatigue_index=excluded.fatigue_index,
        recovery_score=excluded.recovery_score,
        weight_kg=excluded.weight_kg,
        raw_payload=excluded.raw_payload;
    """
    conn.execute(sql, (
        physio_data.get("id", f"physio_{physio_data.get('date')}"),
        physio_data.get("date"),
        physio_data.get("resting_hr"),
        physio_data.get("avg_hr"),
        physio_data.get("hrv_score"),
        physio_data.get("rmssd_ms"),
        physio_data.get("vo2max"),
        physio_data.get("acute_load"),
        physio_data.get("chronic_load"),
        physio_data.get("fatigue_index"),
        physio_data.get("recovery_score"),
        physio_data.get("weight_kg"),
        json.dumps(physio_data)
    ))

def perform_sync(
    client: Optional[CorosMCPClient] = None,
    full: bool = False,
    db_path: Optional[str] = None
) -> Tuple[bool, int, str, int]:
    """Execute data sync operation (full or incremental).

    Returns: (success: bool, records_fetched: int, message: str, duration_ms: int)
    """
    init_db(db_path)
    client = client or CorosMCPClient()
    sync_type = "FULL" if full else "INCREMENTAL"
    start_time = time.time()
    
    if not client.is_authenticated():
        launched = client.trigger_login_flow()
        msg = "🔑 COROS login required. Browser login window launched... Please authenticate in the opened browser, then click Sync again." if launched else "🔑 COROS authentication required. Please run 'npx coros-mcp login'."
        return False, 0, msg, 0

    since_date = None
    if not full:
        since_date = get_last_successful_sync_timestamp(db_path)
        if not since_date:
            since_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")


    try:
        workouts = client.fetch_workouts(since_date=since_date)
        sleep_records = client.fetch_sleep_records(since_date=since_date)
        physiology_records = client.fetch_daily_physiology(since_date=since_date)
        
        total_records = len(workouts) + len(sleep_records) + len(physiology_records)

        conn = get_db_connection(db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            for w in workouts:
                save_activity(w, conn)
            for s in sleep_records:
                save_sleep_record(s, conn)
            for p in physiology_records:
                save_daily_physiology(p, conn)
            conn.commit()
        except Exception as err:
            conn.rollback()
            raise err
        finally:
            conn.close()

        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Sync {sync_type} completed successfully: {total_records} records in {duration_ms}ms"
        log_sync_attempt(sync_type, "SUCCESS", total_records, duration_ms=duration_ms, db_path=db_path)
        return True, total_records, msg, duration_ms

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)
        log_sync_attempt(sync_type, "FAILED", 0, error_message=error_msg, duration_ms=duration_ms, db_path=db_path)
        return False, 0, f"Sync {sync_type} failed: {error_msg}", duration_ms
