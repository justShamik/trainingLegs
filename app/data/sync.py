"""COROS Data Ingestion & Synchronization Engine.

Handles full and incremental data ingestion from COROS MCP server to local SQLite.
Ensures idempotency, transactional integrity, missing field NULL preservation, and audit logging.
"""
import json
import time
from datetime import datetime, timedelta, timezone
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
        elevation_gain_m=COALESCE(excluded.elevation_gain_m, activities.elevation_gain_m),
        elevation_loss_m=COALESCE(excluded.elevation_loss_m, activities.elevation_loss_m),
        gap_s_km=COALESCE(excluded.gap_s_km, activities.gap_s_km),
        avg_hr=COALESCE(excluded.avg_hr, activities.avg_hr),
        max_hr=COALESCE(excluded.max_hr, activities.max_hr),
        avg_cadence=COALESCE(excluded.avg_cadence, activities.avg_cadence),
        stride_length_cm=COALESCE(excluded.stride_length_cm, activities.stride_length_cm),
        ground_contact_time_ms=COALESCE(excluded.ground_contact_time_ms, activities.ground_contact_time_ms),
        vertical_oscillation_mm=COALESCE(excluded.vertical_oscillation_mm, activities.vertical_oscillation_mm),
        avg_power_w=COALESCE(excluded.avg_power_w, activities.avg_power_w),
        calories=COALESCE(excluded.calories, activities.calories),
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

MAX_ENRICH_PER_SYNC = 15
MAX_DETAIL_ATTEMPTS = 3

def enrich_running_activities(client, db_path: Optional[str] = None, limit: int = MAX_ENRICH_PER_SYNC) -> int:
    """Fetch per-activity detail (cadence, stride, GCT, VO, power, GAP, max HR, elevation, laps)
    for running activities not yet enriched, newest first, capped at `limit` per sync.

    Never raises: a failing tool call is recorded in client.call_failures and the activity is
    retried on the next sync. Returns the number of activities enriched."""
    fetch = getattr(client, "fetch_activity_details", None)
    sport_code_of = getattr(client, "running_sport_code", None)
    if fetch is None or sport_code_of is None:
        return 0
    enriched = 0
    try:
        conn = get_db_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT id, sport_type FROM activities WHERE details_synced_at IS NULL "
                "AND COALESCE(details_attempts, 0) < ? "
                "ORDER BY COALESCE(details_attempts, 0) ASC, date DESC, id DESC",
                (MAX_DETAIL_ATTEMPTS,),
            ).fetchall()
        finally:
            conn.close()
        todo = [(r["id"], sport_code_of(r["sport_type"])) for r in rows]
        todo = [(i, c) for i, c in todo if c is not None and str(i).isdigit()][:limit]
        for act_id, code in todo:
            n_fail_before = len(client.call_failures)
            try:
                details = fetch(act_id, code)
                error = None
            except Exception as err:
                details = None
                error = f"{type(err).__name__}: {str(err)[:100]}"
                client.call_failures.append(f"activityDetail: {type(err).__name__}")
            if not details:
                if error is None:
                    new = client.call_failures[n_fail_before:]
                    error = new[-1][:150] if new else "COROS returned no detail data"
                record_detail_failure(act_id, error, db_path)
                continue
            conn = get_db_connection(db_path)
            try:
                apply_activity_details(act_id, details, conn)
                conn.commit()
                enriched += 1
            except Exception:
                conn.rollback()
                client.call_failures.append("activityDetail: save failed")
            finally:
                conn.close()
    except Exception as err:
        client.call_failures.append(f"activityDetail: {type(err).__name__}")
    return enriched

def record_detail_failure(activity_id: str, error: str, db_path: Optional[str] = None) -> None:
    """Count a failed detail fetch (max MAX_DETAIL_ATTEMPTS, then skipped until a full sync resets it)."""
    conn = get_db_connection(db_path)
    try:
        conn.execute(
            "UPDATE activities SET details_attempts=COALESCE(details_attempts, 0)+1, "
            "details_last_error=?, details_last_attempt_at=CURRENT_TIMESTAMP WHERE id=?",
            (error, activity_id),
        )
        conn.commit()
    finally:
        conn.close()

def reset_detail_attempts(db_path: Optional[str] = None) -> None:
    """Manual retry: give activities that exhausted their attempts another chance."""
    conn = get_db_connection(db_path)
    try:
        conn.execute("UPDATE activities SET details_attempts=0, details_last_error=NULL "
                     "WHERE details_synced_at IS NULL")
        conn.commit()
    finally:
        conn.close()

def count_exhausted_details(db_path: Optional[str] = None) -> int:
    """Running activities whose detail fetch failed MAX_DETAIL_ATTEMPTS times."""
    conn = get_db_connection(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM activities WHERE details_synced_at IS NULL AND COALESCE(details_attempts, 0) >= ?",
            (MAX_DETAIL_ATTEMPTS,),
        ).fetchone()[0]
    finally:
        conn.close()

def apply_activity_details(activity_id: str, details: Dict[str, Any], conn) -> None:
    """Merge enrichment values into an activity (COALESCE: never overwrite good data with NULL)."""
    cols = ["elevation_gain_m", "elevation_loss_m", "gap_s_km", "max_hr", "avg_cadence",
            "stride_length_cm", "ground_contact_time_ms", "vertical_oscillation_mm", "avg_power_w"]
    sets = ", ".join(f"{c}=COALESCE(?, {c})" for c in cols)
    # avg_hr from the summary list stays authoritative; detail only fills a gap
    conn.execute(
        f"UPDATE activities SET {sets}, avg_hr=COALESCE(avg_hr, ?), details_synced_at=CURRENT_TIMESTAMP, details_attempts=0, details_last_error=NULL WHERE id=?",
        [details.get(c) for c in cols] + [details.get("avg_hr"), activity_id],
    )
    for split in details.get("splits", []):
        conn.execute(
            """
            INSERT INTO activity_splits (id, activity_id, split_index, distance_m, duration_s,
                avg_pace_s_km, avg_hr, avg_cadence, elevation_gain_m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                distance_m=excluded.distance_m, duration_s=excluded.duration_s,
                avg_pace_s_km=excluded.avg_pace_s_km,
                avg_hr=COALESCE(excluded.avg_hr, activity_splits.avg_hr),
                avg_cadence=COALESCE(excluded.avg_cadence, activity_splits.avg_cadence),
                elevation_gain_m=COALESCE(excluded.elevation_gain_m, activity_splits.elevation_gain_m)
            """,
            (f"{activity_id}_split_{split['split_index']}", activity_id, split["split_index"],
             split["distance_m"], split["duration_s"], split.get("avg_pace_s_km"),
             split.get("avg_hr"), split.get("avg_cadence"), split.get("elevation_gain_m")),
        )

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
        resting_hr=COALESCE(excluded.resting_hr, daily_physiology.resting_hr),
        avg_hr=COALESCE(excluded.avg_hr, daily_physiology.avg_hr),
        hrv_score=COALESCE(excluded.hrv_score, daily_physiology.hrv_score),
        rmssd_ms=COALESCE(excluded.rmssd_ms, daily_physiology.rmssd_ms),
        vo2max=COALESCE(excluded.vo2max, daily_physiology.vo2max),
        acute_load=COALESCE(excluded.acute_load, daily_physiology.acute_load),
        chronic_load=COALESCE(excluded.chronic_load, daily_physiology.chronic_load),
        fatigue_index=COALESCE(excluded.fatigue_index, daily_physiology.fatigue_index),
        recovery_score=COALESCE(excluded.recovery_score, daily_physiology.recovery_score),
        weight_kg=COALESCE(excluded.weight_kg, daily_physiology.weight_kg),
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

def save_daily_activity(data: Dict[str, Any], conn) -> None:
    """Upsert one day's steps/calories/exercise/stress (COALESCE: never overwrite good data with NULL)."""
    conn.execute(
        """
        INSERT INTO daily_activity (date, steps, calories_kcal, exercise_minutes, stress_avg, raw_payload, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            steps=COALESCE(excluded.steps, daily_activity.steps),
            calories_kcal=COALESCE(excluded.calories_kcal, daily_activity.calories_kcal),
            exercise_minutes=COALESCE(excluded.exercise_minutes, daily_activity.exercise_minutes),
            stress_avg=COALESCE(excluded.stress_avg, daily_activity.stress_avg),
            raw_payload=COALESCE(excluded.raw_payload, daily_activity.raw_payload),
            synced_at=excluded.synced_at
        """,
        (data.get("date"), data.get("steps"), data.get("calories_kcal"), data.get("exercise_minutes"),
         data.get("stress_avg"), data.get("raw_payload"),
         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )

def _fetch_health(client, since_date: Optional[str]) -> Tuple[list, list]:
    """Sleep + daily activity from one queryDailyHealthData call; older clients only give sleep."""
    fetch = getattr(client, "fetch_daily_health", None)
    if callable(fetch):
        res = fetch(since_date=since_date)
        if isinstance(res, tuple) and len(res) == 2 and all(isinstance(x, list) for x in res):
            return res
    return client.fetch_sleep_records(since_date=since_date), []

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

    if full:
        since_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since_date = get_last_successful_sync_timestamp(db_path)
        if not since_date:
            since_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")


    try:
        workouts = client.fetch_workouts(since_date=since_date)
        sleep_records, activity_days = _fetch_health(client, since_date)
        physiology_records = client.fetch_daily_physiology(since_date=since_date)

        total_records = len(workouts) + len(sleep_records) + len(physiology_records) + len(activity_days)

        failures = getattr(client, "call_failures", None) or []
        if total_records == 0 and failures:
            raise RuntimeError("COROS MCP calls failed (" + "; ".join(failures[:3]) + "). Nothing was synced.")

        conn = get_db_connection(db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            for w in workouts:
                save_activity(w, conn)
            for s in sleep_records:
                save_sleep_record(s, conn)
            for p in physiology_records:
                save_daily_physiology(p, conn)
            for a in activity_days:
                save_daily_activity(a, conn)
            conn.commit()
        except Exception as err:
            conn.rollback()
            raise err
        finally:
            conn.close()

        if full:
            reset_detail_attempts(db_path)
        enriched = enrich_running_activities(client, db_path)
        exhausted = count_exhausted_details(db_path)

        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Sync {sync_type} completed successfully: {len(workouts)} activities ({enriched} run details enriched),{len(physiology_records)} daily health records, {len(sleep_records)} sleep records, {len(activity_days)} daily activity days in {duration_ms}ms"
        if exhausted:
            msg += f" ({exhausted} activities could not be enriched after {MAX_DETAIL_ATTEMPTS} attempts; use 'Sync 365 Days History' to retry)"
        if failures:
            msg += f" (partial: {'; '.join(sorted(set(f.split(':')[0] for f in failures)))} unavailable)"
        log_sync_attempt(sync_type, "SUCCESS", total_records, duration_ms=duration_ms, db_path=db_path)
        return True, total_records, msg, duration_ms

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)
        log_sync_attempt(sync_type, "FAILED", 0, error_message=error_msg, duration_ms=duration_ms, db_path=db_path)
        return False, 0, f"Sync {sync_type} failed: {error_msg}", duration_ms
