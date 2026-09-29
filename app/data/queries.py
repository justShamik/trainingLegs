"""Database aggregation and retrieval queries for Dashboard, Activity, Profile, and Training Plans."""
import sqlite3
import uuid
from typing import Dict, Any, List, Optional
from app.data.db import get_db_connection

def save_training_plan(plan_data: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """Save generated training plan and session breakdown."""
    conn = get_db_connection(db_path)
    plan_id = plan_data.get("id") or f"plan_{uuid.uuid4().hex[:8]}"
    
    conn.execute(
        """
        INSERT INTO training_plans (
            id, version, goal_distance, race_date, total_volume_km,
            methodology_name, methodology_rationale, is_deload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            plan_data.get("version", 1),
            plan_data.get("goal_distance", "Marathon"),
            plan_data.get("race_date"),
            float(plan_data.get("total_volume_km", 0.0)),
            plan_data.get("methodology_name", "Daniels' VDOT Periodisation"),
            plan_data.get("methodology_rationale", "Base building phase"),
            1 if plan_data.get("is_deload") else 0
        )
    )
    
    sessions = plan_data.get("sessions", [])
    for idx, s in enumerate(sessions):
        conn.execute(
            """
            INSERT INTO plan_sessions (
                id, plan_id, day_of_week, session_type, distance_km,
                duration_min, target_pace_or_hr, stated_purpose
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{plan_id}_sess_{idx}",
                plan_id,
                s.get("day_of_week", "Mon"),
                s.get("session_type", "Rest"),
                float(s["distance_km"]) if s.get("distance_km") is not None else None,
                float(s["duration_min"]) if s.get("duration_min") is not None else None,
                s.get("target_pace_or_hr", "Aerobic / Zone 2"),
                s.get("stated_purpose", "Recovery")
            )
        )

    conn.commit()
    conn.close()
    return plan_id

def get_active_training_plan(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve most recent training plan and its sessions."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM training_plans ORDER BY created_at DESC LIMIT 1")
    plan_row = cursor.fetchone()
    if not plan_row:
        conn.close()
        return None
        
    plan = dict(plan_row)
    cursor.execute("SELECT * FROM plan_sessions WHERE plan_id = ? ORDER BY rowid ASC", (plan["id"],))
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
        WHERE date >= date('now', 'weekday 1 -7 days')
    """)
    week_stats = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT date, total_sleep_minutes, sleep_score, deep_sleep_minutes
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
        ORDER BY week ASC
        LIMIT 12
    """)
    weekly_rows = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("""
        SELECT date, total_sleep_minutes / 60.0 as sleep_hours, sleep_score
        FROM sleep_records
        ORDER BY date ASC
        LIMIT 30
    """)
    sleep_rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT date, hrv_score, resting_hr, acute_load, chronic_load
        FROM daily_physiology
        ORDER BY date ASC
        LIMIT 30
    """)
    physio_rows = [dict(r) for r in cursor.fetchall()]
    
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
            "sleep_score": [r["sleep_score"] for r in sleep_rows]
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
        "actual_avg_hr": actual_avg_hr
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

def calculate_weekly_compliance(plan_id: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculate compliance metrics for the active or specified plan."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    if not plan_id:
        cursor.execute("SELECT id FROM training_plans ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {
                "prescribed_total_km": 0.0,
                "completed_total_km": 0.0,
                "volume_compliance_pct": 0.0,
                "total_sessions": 0,
                "completed_sessions": 0,
                "modified_sessions": 0,
                "skipped_sessions": 0,
                "pending_sessions": 0,
                "session_compliance_pct": 0.0
            }
        plan_id = row["id"]

    cursor.execute("SELECT * FROM plan_sessions WHERE plan_id = ?", (plan_id,))
    sessions = [dict(r) for r in cursor.fetchall()]
    conn.close()

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
        "plan_id": plan_id,
        "prescribed_total_km": round(prescribed_total_km, 1),
        "completed_total_km": round(completed_total_km, 1),
        "volume_compliance_pct": volume_compliance_pct,
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "modified_sessions": modified_sessions,
        "skipped_sessions": skipped_sessions,
        "pending_sessions": pending_sessions,
        "session_compliance_pct": session_compliance_pct
    }

def auto_match_activities_to_sessions(plan_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """Automatically match completed COROS activities to plan sessions based on day/distance heuristic."""
    from app.engine.tracking import generate_post_run_feedback, calculate_workout_adherence

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    if not plan_id:
        cursor.execute("SELECT id FROM training_plans ORDER BY created_at DESC LIMIT 1")
        plan_row = cursor.fetchone()
        if not plan_row:
            conn.close()
            return 0
        plan_id = plan_row["id"]

    cursor.execute("SELECT * FROM plan_sessions WHERE plan_id = ? AND (status IS NULL OR status = 'Pending')", (plan_id,))
    pending_sessions = [dict(s) for s in cursor.fetchall()]

    cursor.execute("""
        SELECT * FROM activities 
        WHERE id NOT IN (SELECT matched_activity_id FROM plan_sessions WHERE matched_activity_id IS NOT NULL)
        ORDER BY date DESC
    """)
    unmatched_activities = [dict(a) for a in cursor.fetchall()]

    matched_count = 0
    day_map = {
        "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6, "Sun": 0
    }

    used_activity_ids = set()

    for sess in pending_sessions:
        if sess.get("session_type") == "Rest" or not sess.get("distance_km"):
            continue

        target_dist = float(sess["distance_km"])
        best_match = None
        best_diff = 999.0

        for act in unmatched_activities:
            if act["id"] in used_activity_ids:
                continue
            act_dist = act["distance_m"] / 1000.0
            dist_diff = abs(act_dist - target_dist)
            
            # Check if distance match is reasonable (within 35% or 3km)
            if dist_diff <= max(3.0, target_dist * 0.35):
                if dist_diff < best_diff:
                    best_diff = dist_diff
                    best_match = act

        if best_match:
            used_activity_ids.add(best_match["id"])
            act_dist_km = round(best_match["distance_m"] / 1000.0, 2)
            act_dur_min = round(best_match["duration_s"] / 60.0, 1)
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


