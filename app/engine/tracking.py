"""Post-Run Execution Feedback & Overtraining Risk Detection Engine.

FR-3.3, FR-3.4 & AC-5.5 compliance:
- Generates factual post-run execution feedback comparing actual vs prescribed workouts.
- Detects overtraining risk based on ACWR (>1.35), HRV score drop (>10%), and low sleep scores (<65).
"""
import sqlite3
from typing import Dict, Any, List, Optional, Tuple
from app.data.db import get_db_connection

def generate_post_run_feedback(session: Dict[str, Any], actual_metrics: Dict[str, Any]) -> str:
    """Generate constructive post-run execution feedback (FR-3.4)."""
    status = actual_metrics.get("status") or session.get("status", "Completed")
    if status == "Skipped":
        return "Session marked as skipped. Priority: restore balance, maintain hydration, and avoid doubling volume on the next run."

    prescribed_dist = float(session.get("distance_km") or 0.0)
    actual_dist = float(actual_metrics.get("actual_distance_km") or prescribed_dist)
    session_type = session.get("session_type", "Easy Aerobic")
    target_pace_hr = session.get("target_pace_or_hr", "Easy / Zone 2")

    feedback_parts = []

    # Distance check
    dist_diff = actual_dist - prescribed_dist
    if abs(dist_diff) <= 0.5:
        feedback_parts.append(f"Distance on target ({actual_dist:.1f} km vs prescribed {prescribed_dist:.1f} km).")
    elif dist_diff > 0.5:
        feedback_parts.append(f"Extended workout distance by +{dist_diff:.1f} km ({actual_dist:.1f} km vs prescribed {prescribed_dist:.1f} km).")
    else:
        feedback_parts.append(f"Shortened session by {abs(dist_diff):.1f} km ({actual_dist:.1f} km vs prescribed {prescribed_dist:.1f} km).")

    # Pace & HR feedback based on session type
    act_pace_s = actual_metrics.get("actual_avg_pace_s_km")
    act_hr = actual_metrics.get("actual_avg_hr")

    if session_type in ("Easy Aerobic", "Recovery"):
        if act_hr and act_hr > 155:
            feedback_parts.append("Heart rate was elevated for an easy run. Slow down on recovery days to keep heart rate in Zone 1-2.")
        elif act_pace_s and act_pace_s < 300:  # < 5:00/km fast easy pace
            feedback_parts.append(f"Pace was fast for an easy session ({int(act_pace_s//60)}:{int(act_pace_s%60):02d}/km). Keep easy runs truly aerobic to protect muscular recovery.")
        else:
            feedback_parts.append("Executed with disciplined easy effort, supporting recovery and mitochondrial growth.")
    elif session_type == "LTHR Test":
        feedback_parts.append("Zone test done. Open the HR Zones page and analyse this run to get your threshold heart rate and COROS zones.")
    elif session_type in ("Threshold", "VO2max"):
        feedback_parts.append(f"Quality workout executed for {session_type}. Ensure carbohydrate refueling and rest before the next session.")
    elif session_type in ("Long Run", "Vert/Time-on-Feet"):
        feedback_parts.append("Solid long endurance volume completed. Great practice for time-on-feet and glycogen management.")
    else:
        feedback_parts.append("Session logged successfully.")

    return " ".join(feedback_parts)


def calculate_workout_adherence(session: Dict[str, Any], actual_metrics: Dict[str, Any]) -> Tuple[float, str]:
    """Calculate numerical adherence score (0-100%) and rating label for a matched workout."""
    import re
    if actual_metrics.get("status") == "Skipped":
        return 0.0, "⚪ 0% Adherence (Session Skipped)"
    prescribed_dist = float(session.get("distance_km") or 0.0)
    actual_dist = float(actual_metrics.get("actual_distance_km") or actual_metrics.get("distance_km") or prescribed_dist)

    if prescribed_dist <= 0:
        return 100.0, "🌟 100% Adherence (Rest Day)"

    dist_diff = abs(actual_dist - prescribed_dist)
    dist_adherence = max(0.0, 100.0 - (dist_diff / prescribed_dist * 100.0))

    intensity_adherence = 90.0
    act_hr = actual_metrics.get("actual_avg_hr") or actual_metrics.get("avg_hr")
    act_pace_s = actual_metrics.get("actual_avg_pace_s_km") or actual_metrics.get("avg_pace_s_km")
    target_str = session.get("target_pace_or_hr", "")

    if "Heart Rate Focus" in target_str and act_hr:
        hr_match = re.search(r'(\d+)\s*–\s*(\d+)\s*bpm', target_str)
        if hr_match:
            min_hr, max_hr = int(hr_match.group(1)), int(hr_match.group(2))
            if min_hr - 5 <= act_hr <= max_hr + 5:
                intensity_adherence = 100.0
            else:
                hr_diff = min(abs(act_hr - min_hr), abs(act_hr - max_hr))
                intensity_adherence = max(50.0, 100.0 - (hr_diff * 2.5))

    elif "Pace Focus" in target_str and act_pace_s:
        pace_match = re.search(r'(\d+):(\d+)\s*–\s*(\d+):(\d+)', target_str)
        if pace_match:
            min_pace_s = int(pace_match.group(1)) * 60 + int(pace_match.group(2))
            max_pace_s = int(pace_match.group(3)) * 60 + int(pace_match.group(4))
            target_min_s = min(min_pace_s, max_pace_s)
            target_max_s = max(min_pace_s, max_pace_s)
            if target_min_s - 10 <= act_pace_s <= target_max_s + 10:
                intensity_adherence = 100.0
            else:
                pace_diff = min(abs(act_pace_s - target_min_s), abs(act_pace_s - target_max_s))
                intensity_adherence = max(50.0, 100.0 - (pace_diff * 1.5))

    total_score = round(0.6 * dist_adherence + 0.4 * intensity_adherence, 1)

    if total_score >= 90.0:
        rating_label = f"🌟 {total_score:.0f}% Adherence (Excellent Execution)"
    elif total_score >= 75.0:
        rating_label = f"👍 {total_score:.0f}% Adherence (Good Workout)"
    elif total_score >= 60.0:
        rating_label = f"⚠️ {total_score:.0f}% Adherence (Moderate - Deviated)"
    else:
        rating_label = f"🔴 {total_score:.0f}% Adherence (Low Alignment)"

    return total_score, rating_label



def detect_overtraining_risk(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Detect overtraining and fatigue signals over rolling 7-day window (FR-3.3 / AC-5.5).

    Triggers evaluated:
    1. ACWR > 1.35 (High risk) or > 1.50 (Critical).
    2. HRV Score > 10% drop below 30-day baseline.
    3. Sleep Score < 65 for 3 consecutive days.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    reasons = []
    acwr_val = None
    hrv_drop_pct = None
    low_sleep_days = 0

    # 1. ACWR Check
    cursor.execute("""
        SELECT acute_load, chronic_load
        FROM daily_physiology
        WHERE acute_load IS NOT NULL AND chronic_load IS NOT NULL AND chronic_load > 0
        ORDER BY date DESC LIMIT 1
    """)
    physio_row = cursor.fetchone()
    if physio_row:
        ac = physio_row["acute_load"]
        ch = physio_row["chronic_load"]
        acwr_val = round(ac / ch, 2)
        if acwr_val > 1.50:
            reasons.append(f"Critical Acute:Chronic Workload Ratio (ACWR = {acwr_val} > 1.50 limit).")
        elif acwr_val > 1.35:
            reasons.append(f"Elevated Acute:Chronic Workload Ratio (ACWR = {acwr_val} > 1.35 safe zone).")

    # 2. HRV Drop Check (>10% drop below 30-day baseline)
    cursor.execute("""
        SELECT hrv_score FROM daily_physiology 
        WHERE hrv_score IS NOT NULL 
        ORDER BY date DESC LIMIT 30
    """)
    hrv_rows = [r["hrv_score"] for r in cursor.fetchall()]
    if len(hrv_rows) >= 7:
        recent_hrv = sum(hrv_rows[:3]) / len(hrv_rows[:3])
        baseline_hrv = sum(hrv_rows) / len(hrv_rows)
        if baseline_hrv > 0:
            drop_pct = ((baseline_hrv - recent_hrv) / baseline_hrv) * 100.0
            hrv_drop_pct = round(drop_pct, 1)
            if drop_pct >= 10.0:
                reasons.append(f"HRV score depressed by {drop_pct:.1f}% below 30-day baseline.")

    # 3. Sleep Score Check (< 65 for 3 consecutive days)
    cursor.execute("""
        SELECT sleep_score FROM sleep_records 
        WHERE sleep_score IS NOT NULL 
        ORDER BY date DESC LIMIT 7
    """)
    sleep_scores = [r["sleep_score"] for r in cursor.fetchall()]
    consecutive_low = 0
    for s in sleep_scores:
        if s < 65:
            consecutive_low += 1
            if consecutive_low >= 3:
                break
        else:
            consecutive_low = 0

    low_sleep_days = consecutive_low
    if consecutive_low >= 3:
        reasons.append(f"Poor sleep quality recorded ({consecutive_low} consecutive days with score < 65).")

    conn.close()

    is_flagged = len(reasons) >= 2 or (acwr_val is not None and acwr_val > 1.50)
    risk_level = "NORMAL"
    adjustment_pct = 0.0

    if is_flagged:
        if (acwr_val is not None and acwr_val > 1.50) or len(reasons) >= 3:
            risk_level = "CRITICAL"
            adjustment_pct = -30.0
        else:
            risk_level = "HIGH_RISK"
            adjustment_pct = -20.0

    return {
        "is_flagged": is_flagged,
        "risk_level": risk_level,
        "reasons": reasons,
        "acwr": acwr_val,
        "hrv_drop_pct": hrv_drop_pct,
        "low_sleep_days": low_sleep_days,
        "recommended_adjustment_pct": adjustment_pct
    }
