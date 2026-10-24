"""Create, preview and refresh training plans: the running plan plus its S&C schedule, saved together.

A season plan runs from the current week to the goal race. Refreshing it keeps everything that already happened
(and every session you logged or adjusted), keeps the phase outline, and regenerates the upcoming days from your
actual training: paces, volume and S&C follow your current fitness.
"""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.data.db import get_db_connection
from app.data.queries import get_active_training_plan, get_user_profile, save_strength_workout, save_training_plan
from app.engine.planner import TrainingPlanner
from app.engine.strength import schedule_strength_for_plan

REFRESH_DUE_DAYS = 7
PROFILE_KEYS = ("race_distance_type", "race_date", "target_time_str", "weekly_hours_available", "available_days",
                "injury_history", "current_niggles")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def preview_season_plan(db_path: Optional[str] = None, today: Optional[date] = None,
                        overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The season plan that would be created now with the chosen distance / target time (nothing is saved)."""
    return TrainingPlanner(db_path=db_path).generate_plan(today=today or date.today(), season=True,
                                                          profile_overrides=overrides)


def create_training_plan(db_path: Optional[str] = None, is_deload: bool = False, today: Optional[date] = None,
                         season: bool = False) -> str:
    """Generate and save a running plan and its S&C sessions. Raises ProfileIncompleteError like the planner."""
    today = today or date.today()
    plan = TrainingPlanner(db_path=db_path).generate_plan(is_deload=is_deload, today=today, season=season)
    plan.setdefault("decisions", {})["refreshed_at"] = _now()
    plan_id = save_training_plan(plan, db_path=db_path)
    for wk in schedule_strength_for_plan(plan, today=today, db_path=db_path):
        wk["plan_id"] = plan_id
        save_strength_workout(wk, db_path=db_path)
    return plan_id


def _decisions(plan: Dict[str, Any]) -> Dict[str, Any]:
    raw = plan.get("decisions_json") or plan.get("decisions") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def plan_status(plan: Optional[Dict[str, Any]], db_path: Optional[str] = None,
                today: Optional[date] = None) -> Dict[str, Any]:
    """Banner info: what the plan was built from, whether the profile changed since, whether a refresh is due."""
    if not plan:
        return {}
    today = today or date.today()
    dec = _decisions(plan)
    built = dec.get("profile") or {}
    current = get_user_profile(db_path=db_path)
    changed = [k for k in PROFILE_KEYS if built and str(built.get(k) or "").strip() != str(current.get(k) or "").strip()]
    stamp = dec.get("refreshed_at") or str(plan.get("created_at") or "")
    try:
        last = datetime.fromisoformat(stamp.replace("Z", "+00:00").replace(" ", "T")).date()
    except ValueError:
        last = None
    age = (today - last).days if last else None
    return {"built_from": built, "profile_changed": changed, "last_refresh": last.isoformat() if last else None,
            "days_since_refresh": age, "refresh_due": bool(age is not None and age >= REFRESH_DUE_DAYS
                                                           and plan.get("plan_kind") == "season"),
            "season": plan.get("plan_kind") == "season"}


def _insert_sessions(conn, plan_id: str, sessions: List[Dict[str, Any]], tag: str) -> None:
    for idx, s in enumerate(sessions):
        conn.execute(
            "INSERT INTO plan_sessions (id, plan_id, day_of_week, session_type, distance_km, duration_min,"
            " target_pace_or_hr, stated_purpose, session_date, week_number) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"{plan_id}_{tag}_{idx}", plan_id, s.get("day_of_week"), s["session_type"], s.get("distance_km"),
             s.get("duration_min"), s.get("target_pace_or_hr"), s.get("stated_purpose"), s["session_date"],
             int(s["week_number"])))


def refresh_plan(db_path: Optional[str] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Regenerate the active plan's upcoming days from current training, in place. Past days and every session
    already logged or adjusted are kept; weeks keep their numbers so the phase outline stays the same."""
    today = today or date.today()
    plan = get_active_training_plan(db_path=db_path)
    if not plan:
        raise ValueError("No active plan to refresh.")
    season = plan.get("plan_kind") == "season"
    fresh = TrainingPlanner(db_path=db_path).generate_plan(today=today, season=season)
    old_start = date.fromisoformat(plan["start_date"])
    offset = (date.fromisoformat(fresh["start_date"]) - old_start).days // 7
    keep_dates = {s["session_date"] for s in plan["sessions"]
                  if s["session_date"] < today.isoformat() or (s.get("status") not in (None, "Pending"))
                  or s.get("original_session_type")}
    new_sessions = []
    for s in fresh["sessions"]:
        if s["session_date"] >= today.isoformat() and s["session_date"] not in keep_dates:
            new_sessions.append({**s, "week_number": int(s["week_number"]) + offset})

    dec = _decisions(plan)
    fresh_dec = fresh.get("decisions") or {}
    old_weeks = [w for w in dec.get("weeks", []) if int(w.get("week_number") or 0) <= offset]
    new_weeks = [{**w, "week_number": int(w["week_number"]) + offset} for w in fresh_dec.get("weeks", [])]
    merged = {**fresh_dec, "weeks": old_weeks + new_weeks, "refreshed_at": _now(),
              "created_at_profile": dec.get("profile")}
    total_weeks = offset + int(fresh["total_weeks"])

    conn = get_db_connection(db_path)
    removed = conn.execute(
        "DELETE FROM plan_sessions WHERE plan_id = ? AND session_date >= ? AND (status IS NULL OR status = 'Pending') "
        "AND original_session_type IS NULL", (plan["id"], today.isoformat())).rowcount
    _insert_sessions(conn, plan["id"], new_sessions, f"r{datetime.now(timezone.utc):%m%d%H%M%S}")
    conn.execute("UPDATE training_plans SET decisions_json = ?, total_weeks = ?, end_date = ?, methodology_rationale = ?,"
                 " goal_distance = ?, race_date = ? WHERE id = ?",
                 (json.dumps(merged), total_weeks, fresh["end_date"], fresh["methodology_rationale"],
                  fresh["goal_distance"], fresh["race_date"], plan["id"]))
    conn.execute("DELETE FROM strength_workouts WHERE plan_id = ? AND session_date >= ? AND status = 'Prescribed'",
                 (plan["id"], today.isoformat()))
    done_sc = {r[0] for r in conn.execute("SELECT session_date FROM strength_workouts WHERE plan_id = ?", (plan["id"],))}
    conn.commit()
    conn.close()
    for wk in schedule_strength_for_plan(fresh, today=today, db_path=db_path):
        if wk["session_date"] in done_sc:
            continue
        wk.update(plan_id=plan["id"], week_number=int(wk["week_number"]) + offset)
        save_strength_workout(wk, db_path=db_path)
    return {"plan_id": plan["id"], "replaced": removed, "added": len(new_sessions), "kept": len(keep_dates)}
