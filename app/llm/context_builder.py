"""Context Builder for LLM Prompt Grounding.

Assembles compact, factual runner context from SQLite database without fabricating values.
"""
import json
from typing import Dict, Any, Optional
from app.data.queries import get_user_profile, get_dashboard_summary, get_recent_activities

def build_runner_context(db_path: Optional[str] = None) -> str:
    """Build structured markdown context string grounded strictly in real database data."""
    profile = get_user_profile(db_path=db_path)
    summary = get_dashboard_summary(db_path=db_path)
    recent_runs = get_recent_activities(limit=5, db_path=db_path)

    runs_summary = []
    for r in recent_runs:
        runs_summary.append(
            f"- Date: {r['date'][:10]} | Name: {r['name'] or r['sport_type']} | "
            f"Distance: {r['distance_km']}km | Pace: {r['pace_str']} | HR: {r['avg_hr'] or 'N/A'} bpm"
        )
    runs_text = "\n".join(runs_summary) if runs_summary else "No recent runs synced."

    sleep_text = "N/A"
    if summary.get("latest_sleep"):
        s = summary["latest_sleep"]
        sleep_text = f"Score: {s.get('sleep_score', 'N/A')}/100, Total: {(s.get('total_sleep_minutes', 0)/60.0):.1f} hrs"

    physio_text = "N/A"
    if summary.get("latest_physio"):
        p = summary["latest_physio"]
        physio_text = f"Resting HR: {p.get('resting_hr', 'N/A')} bpm, HRV Score: {p.get('hrv_score', 'N/A')}, VO2max: {p.get('vo2max', 'N/A')}"

    context = f"""
=== RUNNER GOALS & CONSTRAINTS ===
- Target Race: {profile.get('race_distance_type')} (Target Date: {profile.get('race_date')})
- Target Time: {profile.get('target_time_str')}
- Max Weekly Hours: {profile.get('weekly_hours_available')} hours
- Available Days: {profile.get('available_days')}
- Injury History: {profile.get('injury_history')}
- Current Niggles: {profile.get('current_niggles')}

=== CURRENT TRAINING STATS & RECOVERY ===
- Current Week Volume: {summary.get('weekly_volume_km')} km ({summary.get('weekly_runs_count')} runs, {summary.get('weekly_duration_hrs')} hrs)
- Current Week Elevation: {summary.get('weekly_elevation_m')} m
- Acute:Chronic Load Ratio (ACWR): {summary.get('acwr') or 'N/A'}
- Latest Sleep: {sleep_text}
- Latest Physiology: {physio_text}

=== RECENT RUNS HISTORY ===
{runs_text}
"""
    return context.strip()
