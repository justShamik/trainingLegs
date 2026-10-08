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
        total_hrs = f"{((s.get('total_sleep_minutes') or 0)/60.0):.1f} hrs"
        if s.get('sleep_score') is not None:
            sleep_text = f"Score: {s['sleep_score']}/100, Total: {total_hrs}"
        else:
            sleep_text = f"Total: {total_hrs} (sleep score not provided by COROS)"
            if s.get('deep_sleep_minutes') is not None:
                sleep_text += (f", Deep {s['deep_sleep_minutes']} / Light {s.get('light_sleep_minutes')} / "
                               f"REM {s.get('rem_sleep_minutes')} / Awake {s.get('awake_minutes')} min")

    physio_text = "N/A"
    if summary.get("latest_physio"):
        p = summary["latest_physio"]
        physio_text = f"Resting HR: {p.get('resting_hr', 'N/A')} bpm, HRV Score: {p.get('hrv_score', 'N/A')}, VO2max: {p.get('vo2max', 'N/A')}"

    def pf(key):
        v = profile.get(key)
        return "Not set" if v is None or str(v).strip() == "" else v

    context = f"""
=== RUNNER GOALS & CONSTRAINTS ===
- Target Race: {pf('race_distance_type')} (Target Date: {pf('race_date')})
- Target Time: {pf('target_time_str')}
- Max Weekly Hours: {pf('weekly_hours_available')} hours
- Available Days: {pf('available_days')}
- Injury History: {pf('injury_history')}
- Current Niggles: {pf('current_niggles')}

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
