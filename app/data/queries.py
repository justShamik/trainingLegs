"""Database aggregation and retrieval queries for Dashboard, Activity, Profile, and Training Plans."""
import sqlite3
import uuid
from datetime import date, datetime, timedelta, tzinfo
from typing import Dict, Any, List, Optional
from app.data.db import get_db_connection

def save_training_plan(plan_data: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """Save generated training plan and its dated session breakdown.

    Plans without start_date/session_date (legacy single-week callers) are dated from the Monday of the current week.
    Session ids are deterministic: <plan_id>_sess_<index in date order>.
    """
    from datetime import date, timedelta
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    conn = get_db_connection(db_path)
    plan_id = plan_data.get("id") or f"plan_{uuid.uuid4().hex[:8]}"
    sessions = plan_data.get("sessions", [])

    start_date = plan_data.get("start_date")
    if not start_date:
        today = date.today()
        start_date = (today - timedelta(days=today.weekday())).isoformat()
    total_weeks = plan_data.get("total_weeks") or max([int(s.get("week_number") or 1) for s in sessions] or [1])
    end_date = plan_data.get("end_date") or (date.fromisoformat(start_date) + timedelta(days=7 * total_weeks - 1)).isoformat()

    conn.execute(
        """
        INSERT INTO training_plans (
            id, version, goal_distance, race_date, total_volume_km,
            methodology_name, methodology_rationale, is_deload,
            start_date, end_date, total_weeks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            plan_data.get("version", 1),
            plan_data.get("goal_distance", "Marathon"),
            plan_data.get("race_date"),
            float(plan_data.get("total_volume_km", 0.0)),
            plan_data.get("methodology_name", "Daniels' VDOT Periodisation"),
            plan_data.get("methodology_rationale", "Base building phase"),
            1 if plan_data.get("is_deload") else 0,
            start_date, end_date, total_weeks
        )
    )

    for idx, s in enumerate(sessions):
        day_name = s.get("day_of_week", "Mon")
        session_date = s.get("session_date")
        if not session_date:
            offset = weekdays.index(day_name) if day_name in weekdays else 0
            session_date = (date.fromisoformat(start_date) + timedelta(days=offset)).isoformat()
        conn.execute(
            """
            INSERT INTO plan_sessions (
                id, plan_id, day_of_week, session_type, distance_km,
                duration_min, target_pace_or_hr, stated_purpose, session_date, week_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{plan_id}_sess_{idx}",
                plan_id,
                day_name,
                s.get("session_type", "Rest"),
                float(s["distance_km"]) if s.get("distance_km") is not None else None,
                float(s["duration_min"]) if s.get("duration_min") is not None else None,
                s.get("target_pace_or_hr", "Aerobic / Zone 2"),
                s.get("stated_purpose", "Recovery"),
                session_date,
                int(s.get("week_number") or 1)
            )
        )

    conn.commit()
    conn.close()
    return plan_id

def get_active_training_plan(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve most recent training plan and its sessions."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM training_plans ORDER BY created_at DESC, rowid DESC LIMIT 1")
    plan_row = cursor.fetchone()
    if not plan_row:
        conn.close()
        return None
        
    plan = dict(plan_row)
    cursor.execute("SELECT * FROM plan_sessions WHERE plan_id = ? ORDER BY session_date ASC, rowid ASC", (plan["id"],))
    plan["sessions"] = [dict(s) for s in cursor.fetchall()]
    conn.close()
    return plan

def delete_active_training_plan(db_path: Optional[str] = None) -> bool:
    """Delete current active training plan and its sessions."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM training_plans ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    plan_id = row["id"]
    cursor.execute("DELETE FROM plan_sessions WHERE plan_id = ?", (plan_id,))
    cursor.execute("DELETE FROM training_plans WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()
    return True

def get_user_profile(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve user profile and training goal constraints."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profile WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
        
    # Default initial profile
    return {
        "id": 1,
        "race_distance_type": "Marathon",
        "race_date": "2026-11-15",
        "target_time_str": "3:45:00",
        "weekly_hours_available": 8.0,
        "available_days": "Mon,Tue,Thu,Sat,Sun",
        "injury_history": "None",
        "current_niggles": "None",
        "gemini_api_key": None
    }

def save_user_profile(profile_data: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Save or update user goal race profile and constraints."""
    conn = get_db_connection(db_path)
    sql = """
    INSERT INTO user_profile (
        id, race_distance_type, race_date, target_time_str,
        weekly_hours_available, available_days, injury_history, current_niggles, gemini_api_key
    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        race_distance_type=excluded.race_distance_type,
        race_date=excluded.race_date,
        target_time_str=excluded.target_time_str,
        weekly_hours_available=excluded.weekly_hours_available,
        available_days=excluded.available_days,
        injury_history=excluded.injury_history,
        current_niggles=excluded.current_niggles,
        gemini_api_key=COALESCE(excluded.gemini_api_key, user_profile.gemini_api_key),
        updated_at=CURRENT_TIMESTAMP;
    """
    conn.execute(sql, (
        profile_data.get("race_distance_type", "Marathon"),
        profile_data.get("race_date"),
        profile_data.get("target_time_str"),
        float(profile_data.get("weekly_hours_available", 8.0)),
        profile_data.get("available_days", "Mon,Tue,Thu,Sat,Sun"),
        profile_data.get("injury_history"),
        profile_data.get("current_niggles"),
        profile_data.get("gemini_api_key")
    ))
    conn.commit()
    conn.close()

def save_gemini_api_key(api_key: str, db_path: Optional[str] = None) -> None:
    """Store only the Gemini API key, creating a default profile row if none exists."""
    if not get_user_profile_row_exists(db_path):
        save_user_profile(get_user_profile(db_path=db_path), db_path=db_path)
    conn = get_db_connection(db_path)
    conn.execute("UPDATE user_profile SET gemini_api_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (api_key or None,))
    conn.commit()
    conn.close()

def get_user_profile_row_exists(db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT 1 FROM user_profile WHERE id = 1").fetchone()
    conn.close()
    return row is not None

def _sync_ts_to_iso(ts: Optional[str]) -> Optional[str]:
    """sync_logs.timestamp is stored in UTC; expose it as ISO-8601 so the browser can localise it."""
    if not ts:
        return None
    iso = str(ts).replace(" ", "T")
    return iso if iso.endswith("Z") else iso + "Z"

def get_dashboard_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve top-level KPI metrics for current week and latest recovery status."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COALESCE(SUM(distance_m) / 1000.0, 0.0) as weekly_volume_km,
            COALESCE(SUM(duration_s) / 3600.0, 0.0) as weekly_duration_hrs,
            COALESCE(SUM(elevation_gain_m), 0.0) as weekly_elevation_m,
            COUNT(id) as weekly_runs_count
        FROM activities
        WHERE date >= date('now', '-7 days')
    """)
    week_stats = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT date, total_sleep_minutes, sleep_score, deep_sleep_minutes,
               light_sleep_minutes, rem_sleep_minutes, awake_minutes
        FROM sleep_records
        ORDER BY date DESC LIMIT 1
    """)
    sleep_row = cursor.fetchone()
    latest_sleep = dict(sleep_row) if sleep_row else None
    
    cursor.execute("""
        SELECT date, resting_hr, hrv_score, vo2max, acute_load, chronic_load, recovery_score
        FROM daily_physiology
        ORDER BY date DESC LIMIT 1
    """)
    physio_row = cursor.fetchone()
    latest_physio = dict(physio_row) if physio_row else None

    cursor.execute("""
        SELECT timestamp FROM sync_logs WHERE status = 'SUCCESS' ORDER BY id DESC LIMIT 1
    """)
    sync_row = cursor.fetchone()
    last_sync_timestamp = sync_row["timestamp"] if sync_row else None
    last_sync_iso = _sync_ts_to_iso(last_sync_timestamp)
    if last_sync_timestamp and len(last_sync_timestamp) >= 16:
        last_sync_display = last_sync_timestamp[:16].replace("T", " ")
    elif last_sync_timestamp:
        last_sync_display = str(last_sync_timestamp)
    else:
        last_sync_display = "Never Synced"

    acwr = None
    if latest_physio and latest_physio.get("acute_load") and latest_physio.get("chronic_load") and latest_physio["chronic_load"] > 0:
        acwr = round(latest_physio["acute_load"] / latest_physio["chronic_load"], 2)

    conn.close()

    return {
        "weekly_volume_km": round(week_stats["weekly_volume_km"], 1) if week_stats["weekly_volume_km"] is not None else 0.0,
        "weekly_duration_hrs": round(week_stats["weekly_duration_hrs"], 1) if week_stats["weekly_duration_hrs"] is not None else 0.0,
        "weekly_elevation_m": round(week_stats["weekly_elevation_m"], 0) if week_stats["weekly_elevation_m"] is not None else 0.0,
        "weekly_runs_count": week_stats["weekly_runs_count"],
        "latest_sleep": latest_sleep,
        "latest_physio": latest_physio,
        "acwr": acwr,
        "last_sync_timestamp": last_sync_timestamp,
        "last_sync_iso": last_sync_iso,
        "last_sync_display": last_sync_display
    }

def get_recent_activities(days: Optional[int] = 30, limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent running activities for dashboard list with window filtering."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    rows = []
    if days and days > 0:
        cursor.execute("""
            SELECT id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, elevation_gain_m, avg_hr, avg_power_w
            FROM activities
            WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY date DESC
            LIMIT ?
        """, (days, limit))
        rows = [dict(r) for r in cursor.fetchall()]

    # Fallback if no activities found in the requested window but database contains activities
    if not rows:
        cursor.execute("""
            SELECT id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, elevation_gain_m, avg_hr, avg_power_w
            FROM activities
            ORDER BY date DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cursor.fetchall()]

    conn.close()
    
    for r in rows:
        r["distance_km"] = round(r["distance_m"] / 1000.0, 2) if r.get("distance_m") is not None else 0.0
        r["duration_min"] = round(r["duration_s"] / 60.0, 1) if r.get("duration_s") is not None else 0.0
        if r.get("avg_pace_s_km"):
            mins = int(r["avg_pace_s_km"] // 60)
            secs = int(r["avg_pace_s_km"] % 60)
            r["pace_str"] = f"{mins}:{secs:02d} /km"
        else:
            r["pace_str"] = "N/A"
    return rows


def get_trend_charts_data(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve time-series datasets for trend charts."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            strftime('%Y-W%W', date) as week,
            COALESCE(SUM(distance_m) / 1000.0, 0.0) as volume_km,
            COALESCE(SUM(elevation_gain_m), 0.0) as elevation_m
        FROM activities
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """)
    weekly_rows = [dict(r) for r in cursor.fetchall()][::-1]

    cursor.execute("""
        SELECT date, total_sleep_minutes / 60.0 as sleep_hours, sleep_score,
               deep_sleep_minutes / 60.0 as deep_hours, light_sleep_minutes / 60.0 as light_hours,
               rem_sleep_minutes / 60.0 as rem_hours, awake_minutes / 60.0 as awake_hours
        FROM sleep_records
        ORDER BY date DESC
        LIMIT 30
    """)
    sleep_rows = [dict(r) for r in cursor.fetchall()][::-1]

    cursor.execute("""
        SELECT date, hrv_score, resting_hr, acute_load, chronic_load
        FROM daily_physiology
        ORDER BY date DESC
        LIMIT 30
    """)
    physio_rows = [dict(r) for r in cursor.fetchall()][::-1]
    
    conn.close()
    
    return {
        "weekly_volume": {
            "labels": [r["week"] for r in weekly_rows],
            "volume_km": [round(r["volume_km"], 1) if r.get("volume_km") is not None else 0.0 for r in weekly_rows],
            "elevation_m": [round(r["elevation_m"], 0) if r.get("elevation_m") is not None else 0.0 for r in weekly_rows]
        },
        "sleep_trend": {
            "labels": [r["date"] for r in sleep_rows],
            "sleep_hours": [round(r["sleep_hours"], 1) if r.get("sleep_hours") is not None else 0.0 for r in sleep_rows],
            "sleep_score": [r["sleep_score"] for r in sleep_rows],
            # Stages are NULL (None) when COROS gave no split; never zero-filled
            "deep_hours": [round(r["deep_hours"], 2) if r.get("deep_hours") is not None else None for r in sleep_rows],
            "light_hours": [round(r["light_hours"], 2) if r.get("light_hours") is not None else None for r in sleep_rows],
            "rem_hours": [round(r["rem_hours"], 2) if r.get("rem_hours") is not None else None for r in sleep_rows],
            "awake_hours": [round(r["awake_hours"], 2) if r.get("awake_hours") is not None else None for r in sleep_rows],
            "has_score": any(r["sleep_score"] is not None for r in sleep_rows)
        },
        "physio_trend": {
            "labels": [r["date"] for r in physio_rows],
            "hrv": [r["hrv_score"] for r in physio_rows],
            "resting_hr": [r["resting_hr"] for r in physio_rows],
            "acute_load": [r["acute_load"] for r in physio_rows],
            "chronic_load": [r["chronic_load"] for r in physio_rows]
        }
    }

def get_activity_detail(activity_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve full activity details including lap splits."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activities WHERE id = ?", (activity_id,))
    act_row = cursor.fetchone()
    if not act_row:
        conn.close()
        return None
        
    activity = dict(act_row)
    activity["distance_km"] = round(activity["distance_m"] / 1000.0, 2) if activity.get("distance_m") is not None else 0.0
    activity["duration_min"] = round(activity["duration_s"] / 60.0, 1) if activity.get("duration_s") is not None else 0.0
    if activity.get("avg_pace_s_km"):
        mins = int(activity["avg_pace_s_km"] // 60)
        secs = int(activity["avg_pace_s_km"] % 60)
        activity["pace_str"] = f"{mins}:{secs:02d} /km"
    else:
        activity["pace_str"] = "N/A"

    cursor.execute("""
        SELECT * FROM activity_splits WHERE activity_id = ? ORDER BY split_index ASC
    """, (activity_id,))
    splits = [dict(s) for s in cursor.fetchall()]
    for s in splits:
        s["distance_km"] = round(s["distance_m"] / 1000.0, 2) if s.get("distance_m") is not None else 0.0
        s["duration_min"] = round(s["duration_s"] / 60.0, 1) if s.get("duration_s") is not None else 0.0
        if s.get("avg_pace_s_km"):
            mins = int(s["avg_pace_s_km"] // 60)
            secs = int(s["avg_pace_s_km"] % 60)
            s["pace_str"] = f"{mins}:{secs:02d} /km"
        else:
            s["pace_str"] = "N/A"

    activity["splits"] = splits
    if activity.get("gap_s_km"):
        activity["gap_str"] = f"{int(activity['gap_s_km'] // 60)}:{int(activity['gap_s_km'] % 60):02d} /km"
    # Explain WHY a form metric is missing (never fabricate a value)
    if activity.get("details_synced_at"):
        activity["na_reason"] = "Not recorded for this activity"
    elif "run" in (activity.get("sport_type") or "").lower():
        attempts = activity.get("details_attempts") or 0
        if attempts >= 3:
            activity["na_reason"] = (f"Detail fetch failed {attempts} times ({activity.get('details_last_error') or 'unknown error'}) "
                                     "- use 'Sync 365 Days History' to retry")
        elif attempts:
            activity["na_reason"] = (f"Detail fetch failed ({attempts} of 3 attempts: "
                                     f"{activity.get('details_last_error') or 'unknown error'}) - will retry on next sync")
        else:
            activity["na_reason"] = "Detail data not synced yet - click Sync on the dashboard"
    else:
        activity["na_reason"] = "Not applicable for this sport type"
    conn.close()
    return activity

def update_session_status(
    session_id: str,
    status: str,
    user_notes: Optional[str] = None,
    actual_distance_km: Optional[float] = None,
    actual_duration_min: Optional[float] = None,
    actual_avg_pace_s_km: Optional[float] = None,
    actual_avg_hr: Optional[int] = None,
    post_run_feedback: Optional[str] = None,
    db_path: Optional[str] = None
) -> None:
    """Update execution status, actual figures, feedback, and adherence rating for a plan session."""
    from app.engine.tracking import calculate_workout_adherence
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM plan_sessions WHERE id = ?", (session_id,))
    sess_row = cursor.fetchone()
    sess_dict = dict(sess_row) if sess_row else {}

    actual_metrics = {
        "actual_distance_km": actual_distance_km,
        "actual_duration_min": actual_duration_min,
        "actual_avg_pace_s_km": actual_avg_pace_s_km,
        "actual_avg_hr": actual_avg_hr,
        "status": status
    }
    score, rating = calculate_workout_adherence(sess_dict, actual_metrics)

    conn.execute(
        """
        UPDATE plan_sessions
        SET status = ?,
            user_notes = COALESCE(?, user_notes),
            actual_distance_km = COALESCE(?, actual_distance_km),
            actual_duration_min = COALESCE(?, actual_duration_min),
            actual_avg_pace_s_km = COALESCE(?, actual_avg_pace_s_km),
            actual_avg_hr = COALESCE(?, actual_avg_hr),
            post_run_feedback = COALESCE(?, post_run_feedback),
            adherence_score = ?,
            adherence_rating = ?
        WHERE id = ?
        """,
        (status, user_notes, actual_distance_km, actual_duration_min, actual_avg_pace_s_km, actual_avg_hr, post_run_feedback, score, rating, session_id)
    )
    conn.commit()
    conn.close()

def get_plan_session(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single plan session row."""
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM plan_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def _empty_compliance() -> Dict[str, Any]:
    return {
        "scope": "week", "week_number": None, "week_start": None, "week_end": None,
        "prescribed_total_km": 0.0, "completed_total_km": 0.0, "volume_compliance_pct": 0.0,
        "total_sessions": 0, "completed_sessions": 0, "modified_sessions": 0,
        "skipped_sessions": 0, "pending_sessions": 0, "session_compliance_pct": 0.0,
        "plan_prescribed_total_km": 0.0, "plan_completed_total_km": 0.0, "plan_volume_compliance_pct": 0.0,
        "plan_total_sessions": 0, "plan_completed_sessions": 0, "plan_session_compliance_pct": 0.0,
    }

def _compliance_for(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    prescribed_total_km = sum(s["distance_km"] or 0.0 for s in sessions)
    completed_total_km = sum(
        s["actual_distance_km"] if s.get("actual_distance_km") is not None else (s["distance_km"] or 0.0)
        for s in sessions
        if s.get("status") in ("Completed", "Modified")
    )
    volume_compliance_pct = round((completed_total_km / prescribed_total_km * 100.0), 1) if prescribed_total_km > 0 else 100.0

    non_rest_sessions = [s for s in sessions if s.get("session_type") != "Rest"]
    total_sessions = len(non_rest_sessions)
    completed_sessions = sum(1 for s in non_rest_sessions if s.get("status") == "Completed")
    modified_sessions = sum(1 for s in non_rest_sessions if s.get("status") == "Modified")
    skipped_sessions = sum(1 for s in non_rest_sessions if s.get("status") == "Skipped")
    pending_sessions = sum(1 for s in non_rest_sessions if s.get("status") in ("Pending", None))
    executed_count = completed_sessions + modified_sessions
    session_compliance_pct = round((executed_count / total_sessions * 100.0), 1) if total_sessions > 0 else 100.0
    return {
        "prescribed_total_km": round(prescribed_total_km, 1),
        "completed_total_km": round(completed_total_km, 1),
        "volume_compliance_pct": volume_compliance_pct,
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "modified_sessions": modified_sessions,
        "skipped_sessions": skipped_sessions,
        "pending_sessions": pending_sessions,
        "session_compliance_pct": session_compliance_pct,
    }

def calculate_weekly_compliance(plan_id: Optional[str] = None, db_path: Optional[str] = None, today=None) -> Dict[str, Any]:
    """Compliance for the active or specified plan.

    The top-level keys (prescribed_total_km, volume_compliance_pct, ...) cover the CURRENT WEEK of the plan
    (the week containing `today`, clamped to the plan's first/last week). The whole-plan figures are returned
    under the plan_* keys (plan_prescribed_total_km, plan_completed_total_km, plan_volume_compliance_pct,
    plan_total_sessions, plan_completed_sessions, plan_session_compliance_pct).
    """
    from datetime import date as _date, timedelta
    today = today or _date.today()
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    if not plan_id:
        cursor.execute("SELECT id FROM training_plans ORDER BY created_at DESC, rowid DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return _empty_compliance()
        plan_id = row["id"]

    plan_row = cursor.execute("SELECT start_date, total_weeks FROM training_plans WHERE id = ?", (plan_id,)).fetchone()
    cursor.execute("SELECT * FROM plan_sessions WHERE plan_id = ? ORDER BY session_date, rowid", (plan_id,))
    sessions = [dict(r) for r in cursor.fetchall()]
    conn.close()

    week_number, week_start = 1, None
    if plan_row and plan_row["start_date"]:
        start = _date.fromisoformat(plan_row["start_date"])
        total_weeks = plan_row["total_weeks"] or 1
        week_number = min(max((today - start).days // 7 + 1, 1), total_weeks)
        week_start = start + timedelta(days=7 * (week_number - 1))
    week_sessions = [s for s in sessions if int(s.get("week_number") or 1) == week_number]

    result = _compliance_for(week_sessions)
    whole = _compliance_for(sessions)
    result.update({
        "plan_id": plan_id,
        "scope": "week",
        "week_number": week_number,
        "week_start": week_start.isoformat() if week_start else None,
        "week_end": (week_start + timedelta(days=6)).isoformat() if week_start else None,
        "plan_prescribed_total_km": whole["prescribed_total_km"],
        "plan_completed_total_km": whole["completed_total_km"],
        "plan_volume_compliance_pct": whole["volume_compliance_pct"],
        "plan_total_sessions": whole["total_sessions"],
        "plan_completed_sessions": whole["completed_sessions"] + whole["modified_sessions"],
        "plan_session_compliance_pct": whole["session_compliance_pct"],
    })
    return result

def auto_match_activities_to_sessions(plan_id: Optional[str] = None, db_path: Optional[str] = None, today=None) -> int:
    """Match COROS run activities to plan sessions by calendar date.

    Only past/today sessions (session_date <= today) are candidates - future sessions are never matched.
    Pass 1 matches an activity on the SAME date as the session; pass 2 falls back to +-1 day. In both passes the
    distance must be within max(3 km, 35%) of the prescription and the closest distance wins.
    """
    from datetime import date as _date, timedelta
    from app.engine.tracking import generate_post_run_feedback, calculate_workout_adherence
    today = today or _date.today()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    if not plan_id:
        cursor.execute("SELECT id FROM training_plans ORDER BY created_at DESC, rowid DESC LIMIT 1")
        plan_row = cursor.fetchone()
        if not plan_row:
            conn.close()
            return 0
        plan_id = plan_row["id"]

    cursor.execute(
        "SELECT * FROM plan_sessions WHERE plan_id = ? AND (status IS NULL OR status = 'Pending') "
        "AND session_date IS NOT NULL AND session_date <= ? ORDER BY session_date, rowid",
        (plan_id, today.isoformat()))
    pending_sessions = [dict(s) for s in cursor.fetchall()
                        if s["session_type"] != "Rest" and s["distance_km"]]
    if not pending_sessions:
        conn.close()
        return 0

    first_day = (_date.fromisoformat(pending_sessions[0]["session_date"]) - timedelta(days=1)).isoformat()
    cursor.execute("""
        SELECT * FROM activities
        WHERE id NOT IN (SELECT matched_activity_id FROM plan_sessions WHERE matched_activity_id IS NOT NULL)
          AND LOWER(sport_type) LIKE '%run%'
          AND substr(date, 1, 10) >= ? AND substr(date, 1, 10) <= ?
        ORDER BY date DESC
    """, (first_day, today.isoformat()))
    unmatched_activities = [dict(a) for a in cursor.fetchall() if a["distance_m"] is not None]

    def _day(value: str) -> Optional[_date]:
        try:
            return _date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    used_activity_ids = set()
    assignments: Dict[str, Dict[str, Any]] = {}

    for max_gap in (0, 1):  # pass 1: same date, pass 2: +-1 day
        for sess in pending_sessions:
            if sess["id"] in assignments:
                continue
            sdate = _day(sess["session_date"])
            target_dist = float(sess["distance_km"])
            best, best_diff = None, 999.0
            for act in unmatched_activities:
                if act["id"] in used_activity_ids:
                    continue
                adate = _day(act["date"])
                if sdate is None or adate is None or abs((adate - sdate).days) > max_gap:
                    continue
                if max_gap == 1 and adate == sdate:
                    continue  # same-date candidates were handled in pass 1
                dist_diff = abs(act["distance_m"] / 1000.0 - target_dist)
                if dist_diff <= max(3.0, target_dist * 0.35) and dist_diff < best_diff:
                    best, best_diff = act, dist_diff
            if best:
                used_activity_ids.add(best["id"])
                assignments[sess["id"]] = best

    matched_count = 0
    for sess in pending_sessions:
        best_match = assignments.get(sess["id"])
        if not best_match:
            continue
        act_dist_km = round(best_match["distance_m"] / 1000.0, 2)
        act_dur_min = round((best_match.get("duration_s") or 0.0) / 60.0, 1)
        act_pace = best_match.get("avg_pace_s_km")
        act_hr = best_match.get("avg_hr")

        actual_metrics = {
            "actual_distance_km": act_dist_km,
            "actual_duration_min": act_dur_min,
            "actual_avg_pace_s_km": act_pace,
            "actual_avg_hr": act_hr
        }

        feedback = generate_post_run_feedback(sess, actual_metrics)
        score, rating = calculate_workout_adherence(sess, actual_metrics)

        cursor.execute("""
            UPDATE plan_sessions
            SET matched_activity_id = ?,
                status = 'Completed',
                actual_distance_km = ?,
                actual_duration_min = ?,
                actual_avg_pace_s_km = ?,
                actual_avg_hr = ?,
                post_run_feedback = ?,
                adherence_score = ?,
                adherence_rating = ?
            WHERE id = ?
        """, (best_match["id"], act_dist_km, act_dur_min, act_pace, act_hr, feedback, score, rating, sess["id"]))
        matched_count += 1

    conn.commit()
    conn.close()
    return matched_count

def save_block_summary(block_data: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """Save 4-week block summary performance report."""
    conn = get_db_connection(db_path)
    block_id = block_data.get("id") or f"block_{uuid.uuid4().hex[:8]}"
    
    conn.execute(
        """
        INSERT INTO block_summaries (
            id, block_number, start_date, end_date, total_prescribed_km,
            total_completed_km, compliance_pct, key_achievements,
            areas_for_improvement, fatigue_signals_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            block_id,
            block_data.get("block_number", 1),
            block_data.get("start_date", "2026-09-01"),
            block_data.get("end_date", "2026-09-28"),
            float(block_data.get("total_prescribed_km", 0.0)),
            float(block_data.get("total_completed_km", 0.0)),
            float(block_data.get("compliance_pct", 0.0)),
            block_data.get("key_achievements", "Consistent aerobic base building."),
            block_data.get("areas_for_improvement", "Maintain slower recovery pace."),
            block_data.get("fatigue_signals_summary", "ACWR stable within safe 0.8-1.2 zone.")
        )
    )
    conn.commit()
    conn.close()
    return block_id

def get_block_summaries(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve history of 4-week block performance summaries."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM block_summaries ORDER BY block_number DESC, created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

DEFAULT_STRENGTH_EXERCISES = [
    {
        "id": "ex_bulgarian_split_squat",
        "name": "Bulgarian Split Squat",
        "category": "Single-Leg",
        "movement_pattern": "Squat / Single-Leg",
        "equipment_needed": "Dumbbells / Bench",
        "contraindicated_niggles": "Knee, Patellar",
        "default_sets": 3,
        "default_reps": "8 per leg",
        "default_rpe": 7,
        "safety_cues": "Keep front knee aligned over second toe, torso slightly hinged to target glute stability."
    },
    {
        "id": "ex_rdl",
        "name": "Romanian Deadlift (RDL)",
        "category": "Hinge",
        "movement_pattern": "Posterior Hinge",
        "equipment_needed": "Barbell / Dumbbells",
        "contraindicated_niggles": "Lower Back, Hamstring",
        "default_sets": 3,
        "default_reps": "10",
        "default_rpe": 7,
        "safety_cues": "Hinge at hips, soft knee bend, maintain neutral lumbar spine throughout lowering."
    },
    {
        "id": "ex_single_leg_bridge",
        "name": "Single-Leg Glute Bridge",
        "category": "Hinge",
        "movement_pattern": "Single-Leg Hinge",
        "equipment_needed": "Bodyweight / Mat",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "12 per leg",
        "default_rpe": 7,
        "safety_cues": "Squeeze glute hard at top lockout, avoid over-arching lower back."
    },
    {
        "id": "ex_eccentric_calf_raise",
        "name": "Weighted Eccentric Calf Raise",
        "category": "Calf/Ankle",
        "movement_pattern": "Plantar Flexion / Ankle",
        "equipment_needed": "Step + Dumbbell",
        "contraindicated_niggles": "Achilles, Calf",
        "default_sets": 3,
        "default_reps": "15 per leg",
        "default_rpe": 7,
        "safety_cues": "Lower slowly for 3 seconds below step level before lifting back up."
    },
    {
        "id": "ex_seated_soleus_raise",
        "name": "Seated Soleus Calf Raise",
        "category": "Calf/Ankle",
        "movement_pattern": "Soleus Endurance",
        "equipment_needed": "Chair + Dumbbell on thighs",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "15",
        "default_rpe": 7,
        "safety_cues": "Knees bent at 90 degrees isolates soleus muscle crucial for endurance distance running."
    },
    {
        "id": "ex_pallof_press",
        "name": "Pallof Press",
        "category": "Core",
        "movement_pattern": "Anti-Rotation Core",
        "equipment_needed": "Resistance Band / Cable",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "10 per side",
        "default_rpe": 7,
        "safety_cues": "Brace core tight, press band straight out without allowing torso to rotate."
    },
    {
        "id": "ex_spanish_squat",
        "name": "Spanish Squat (Isometric Hold)",
        "category": "Squat",
        "movement_pattern": "Knee Stability / Quad",
        "equipment_needed": "Heavy Resistance Band",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "30 sec hold",
        "default_rpe": 7,
        "safety_cues": "Loop heavy band behind knees, sit back upright. Excellent patellar tendon rehabilitation."
    },
    {
        "id": "ex_chest_supported_row",
        "name": "Chest-Supported Dumbbell Row",
        "category": "Upper Body",
        "movement_pattern": "Horizontal Pull",
        "equipment_needed": "Incline Bench + Dumbbells",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "10",
        "default_rpe": 7,
        "safety_cues": "Retract shoulder blades together, strengthening upper back for upright running posture."
    },
    {
        "id": "ex_step_ups",
        "name": "Single-Leg Box Step-Ups",
        "category": "Single-Leg",
        "movement_pattern": "Single-Leg Step",
        "equipment_needed": "Box / Bench",
        "contraindicated_niggles": "Knee",
        "default_sets": 3,
        "default_reps": "10 per leg",
        "default_rpe": 7,
        "safety_cues": "Drive through front heel, minimise pushing off trailing toe."
    },
    {
        "id": "ex_pogo_hops",
        "name": "Pogo Hops (Ankle Stiffness)",
        "category": "Plyo",
        "movement_pattern": "Reactive Elasticity",
        "equipment_needed": "Bodyweight",
        "contraindicated_niggles": "Achilles, Calf, Plantar, Shin Splints, Knee",
        "default_sets": 3,
        "default_reps": "20 sec bounce",
        "default_rpe": 8,
        "safety_cues": "Stiff ankles, quick elastic ground contact, minimal knee bend."
    },
    {
        "id": "ex_deadbug",
        "name": "Deadbug with Isometric Press",
        "category": "Core",
        "movement_pattern": "Anti-Extension Core",
        "equipment_needed": "Bodyweight / Mat",
        "contraindicated_niggles": "",
        "default_sets": 3,
        "default_reps": "10 per side",
        "default_rpe": 7,
        "safety_cues": "Press lower back flat against floor while lowering opposite arm and leg."
    }
]

def seed_strength_exercises_if_empty(db_path: Optional[str] = None) -> None:
    """Seed default exercise library into database if empty."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM strength_exercises")
    count = cursor.fetchone()["cnt"]
    if count == 0:
        for ex in DEFAULT_STRENGTH_EXERCISES:
            cursor.execute("""
                INSERT INTO strength_exercises (
                    id, name, category, movement_pattern, equipment_needed,
                    contraindicated_niggles, default_sets, default_reps, default_rpe, safety_cues
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ex["id"], ex["name"], ex["category"], ex["movement_pattern"],
                ex["equipment_needed"], ex["contraindicated_niggles"],
                ex["default_sets"], ex["default_reps"], ex["default_rpe"], ex["safety_cues"]
            ))
        conn.commit()
    conn.close()

def get_available_exercises(niggles_str: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve exercises safely filtered against active user niggles (FR-4.2 / FR-4.4)."""
    seed_strength_exercises_if_empty(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM strength_exercises")
    all_exercises = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not niggles_str or niggles_str.strip().lower() in ("none", "n/a", ""):
        return all_exercises

    user_niggles = [n.strip().lower() for n in niggles_str.split(",") if n.strip()]

    safe_exercises = []
    for ex in all_exercises:
        contra = (ex.get("contraindicated_niggles") or "").lower()
        contra_list = [c.strip() for c in contra.split(",") if c.strip()]
        
        is_unsafe = False
        for niggle in user_niggles:
            for c in contra_list:
                if c in niggle or niggle in c:
                    is_unsafe = True
                    break
            if is_unsafe:
                break
                
        if not is_unsafe:
            safe_exercises.append(ex)

    return safe_exercises

def save_strength_workout(workout_data: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """Save generated strength workout session."""
    import json
    conn = get_db_connection(db_path)
    workout_id = workout_data.get("id") or f"str_{uuid.uuid4().hex[:8]}"
    
    conn.execute(
        """
        INSERT INTO strength_workouts (
            id, phase, focus_area, total_duration_min, workout_data_json, status
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            workout_id,
            workout_data.get("phase", "Base"),
            workout_data.get("focus_area", "Full Body Runner Stability"),
            workout_data.get("total_duration_min", 40),
            json.dumps(workout_data),
            workout_data.get("status", "Prescribed")
        )
    )
    conn.commit()
    conn.close()
    return workout_id

def get_active_strength_workout(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve most recent prescribed strength workout."""
    import json
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM strength_workouts ORDER BY created_at DESC, rowid DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    data = dict(row)
    if data.get("workout_data_json"):
        try:
            parsed = json.loads(data["workout_data_json"])
            parsed["db_id"] = data["id"]
            parsed["status"] = data["status"]
            return parsed
        except Exception:
            pass
    return data

def update_strength_workout_status(workout_id: str, status: str, db_path: Optional[str] = None) -> None:
    """Update execution status of strength workout (Prescribed, Completed, Skipped)."""
    conn = get_db_connection(db_path)
    if status == "Completed":
        conn.execute("UPDATE strength_workouts SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?", (status, workout_id))
    else:
        conn.execute("UPDATE strength_workouts SET status = ? WHERE id = ?", (status, workout_id))
    conn.commit()
    conn.close()


# ---- Home page: today's dials + sync status ----------------------------------------------

DEFAULT_SLEEP_GOAL = 480        # minutes
DEFAULT_ACTIVITY_GOAL = 60      # minutes
DEFAULT_STEPS_GOAL = 10000
DEFAULT_CALORIES_GOAL = 2500    # kcal
NOT_SYNCED_TODAY = "Not synced yet today"

def _pct(value: Optional[float], goal: float) -> Optional[int]:
    """Dial fill 0-100 (capped); None when the value is unknown."""
    if value is None or not goal:
        return None
    return int(round(max(0.0, min(100.0, value * 100.0 / goal))))

def local_date_of(ts: Optional[str], tz: Optional[tzinfo] = None) -> Optional[date]:
    """Local calendar date of an activities.date value.

    Timestamps carrying 'Z'/an offset are converted to `tz` (default: system local zone), so
    2026-10-02T20:00:00Z is 2026-10-03 in IST. Date-only or naive values keep their date part."""
    if not ts:
        return None
    s = str(ts).strip()
    try:
        if len(s) <= 10:
            return date.fromisoformat(s[:10])
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(tz).date()

def get_today_summary(db_path: Optional[str] = None, today: Optional[date] = None,
                      tz: Optional[tzinfo] = None) -> Dict[str, Any]:
    """Today's sleep / activity time / steps / calories with goal fill % for the home dials.

    `today` defaults to the system local date. Sleep is dated by wake-up day, so last night's
    sleep is the sleep_records row dated today. Unknown values stay None with a reason (NFR-4.1)."""
    if today is None:
        today = datetime.now(tz).date() if tz else date.today()
    elif isinstance(today, str):
        today = date.fromisoformat(today[:10])
    day = today.isoformat()

    conn = get_db_connection(db_path)
    try:
        sleep_row = conn.execute(
            "SELECT total_sleep_minutes, deep_sleep_minutes, light_sleep_minutes, rem_sleep_minutes, awake_minutes "
            "FROM sleep_records WHERE date = ?", (day,)).fetchone()
        try:
            act_row = conn.execute("SELECT steps, calories_kcal, exercise_minutes, stress_avg "
                                   "FROM daily_activity WHERE date = ?", (day,)).fetchone()
        except sqlite3.OperationalError:  # table not migrated yet
            act_row = None
        # Coarse SQL window (+/- 1 day covers any UTC offset), exact local-date match in Python
        rows = conn.execute(
            "SELECT date, duration_s FROM activities WHERE substr(date, 1, 10) BETWEEN ? AND ?",
            ((today - timedelta(days=1)).isoformat(), (today + timedelta(days=1)).isoformat())).fetchall()
    finally:
        conn.close()

    todays = [r for r in rows if local_date_of(r["date"], tz) == today]
    activity_min = round(sum((r["duration_s"] or 0) for r in todays) / 60.0, 1)

    sleep = None
    sleep_reason = None
    if sleep_row:
        sleep = {
            "total_minutes": sleep_row["total_sleep_minutes"],
            "deep_minutes": sleep_row["deep_sleep_minutes"],
            "light_minutes": sleep_row["light_sleep_minutes"],
            "rem_minutes": sleep_row["rem_sleep_minutes"],
            "awake_minutes": sleep_row["awake_minutes"],
        }
    else:
        sleep_reason = NOT_SYNCED_TODAY if act_row is None else "No sleep recorded last night"

    steps = act_row["steps"] if act_row else None
    calories = act_row["calories_kcal"] if act_row else None
    return {
        "date": day,
        "sleep": sleep,
        "sleep_reason": sleep_reason,
        "activity_time_minutes": activity_min,
        "activity_count": len(todays),
        "activity_reason": None if todays else "No activities recorded today",
        "exercise_minutes": act_row["exercise_minutes"] if act_row else None,
        "stress_avg": act_row["stress_avg"] if act_row else None,
        "steps": steps,
        "calories_kcal": calories,
        "daily_activity_reason": None if act_row else NOT_SYNCED_TODAY,
        "goals": {
            "sleep_minutes": DEFAULT_SLEEP_GOAL,
            "activity_minutes": DEFAULT_ACTIVITY_GOAL,
            "steps": DEFAULT_STEPS_GOAL,
            "calories_kcal": DEFAULT_CALORIES_GOAL,
        },
        "pct": {
            "sleep": _pct(sleep["total_minutes"] if sleep else None, DEFAULT_SLEEP_GOAL),
            "activity": _pct(activity_min, DEFAULT_ACTIVITY_GOAL),
            "steps": _pct(steps, DEFAULT_STEPS_GOAL),
            "calories": _pct(calories, DEFAULT_CALORIES_GOAL),
        },
    }

def get_sync_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Last sync (from sync_logs) + COROS token state: connected / expired / disconnected.

    validate_token_status only reads the local token file (no subprocess / network)."""
    conn = get_db_connection(db_path)
    try:
        ok_row = conn.execute("SELECT timestamp FROM sync_logs WHERE status = 'SUCCESS' "
                              "ORDER BY id DESC LIMIT 1").fetchone()
        last_row = conn.execute("SELECT timestamp, sync_type, status, error_message FROM sync_logs "
                                "ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        ok_row = last_row = None
    finally:
        conn.close()

    try:
        from app.mcp_client.coros_client import CorosMCPClient
        token = CorosMCPClient().validate_token_status() or {}
    except Exception as err:
        token = {"is_authenticated": False, "token_exists": None, "status_code": "UNKNOWN",
                 "message": f"Could not check COROS token ({type(err).__name__})"}

    if token.get("is_authenticated"):
        state = "connected"
    elif token.get("token_exists"):
        state = "expired"
    else:
        state = "disconnected"
    return {
        "state": state,
        "last_sync_iso": _sync_ts_to_iso(ok_row["timestamp"] if ok_row else None),
        "last_attempt_iso": _sync_ts_to_iso(last_row["timestamp"] if last_row else None),
        "last_sync_status": last_row["status"] if last_row else None,
        "last_sync_type": last_row["sync_type"] if last_row else None,
        "last_sync_message": last_row["error_message"] if last_row else None,
        "is_authenticated": bool(token.get("is_authenticated")),
        "status_code": token.get("status_code"),
        "token_message": token.get("message"),
        "token_expires_at": token.get("expires_at"),
    }
