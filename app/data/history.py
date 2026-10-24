"""Training history for the plan page: week-by-week planned vs done, and every plan generated so far.

Actual running comes from synced activities (all runs, planned or not). Planned figures come from the plan of
record for that week: the newest plan covering the week that has any logged/matched session there, else the
newest non-discarded plan covering it. Compliance uses the same original-prescription rules as the plan page.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.data.db import get_db_connection
from app.data.queries import _compliance_for, _prescribed, local_date_of

LOGGED = ("Completed", "Modified", "Skipped")


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start.day} {start:%b} – {end.day} {end:%b}" if start.month != end.month else f"{start.day}–{end.day} {start:%b}"


def get_training_history(db_path: Optional[str] = None, today: Optional[date] = None, weeks: int = 12) -> Dict[str, Any]:
    today = today or date.today()
    current = _monday(today)
    first = current - timedelta(weeks=weeks - 1)
    conn = get_db_connection(db_path)
    acts = conn.execute(
        "SELECT date, distance_m, duration_s FROM activities WHERE LOWER(COALESCE(sport_type, '')) LIKE '%run%' "
        "AND substr(date, 1, 10) BETWEEN ? AND ?",
        ((first - timedelta(days=1)).isoformat(), (current + timedelta(days=7)).isoformat())).fetchall()
    plans = [dict(r) for r in conn.execute(
        "SELECT * FROM training_plans WHERE start_date IS NOT NULL ORDER BY created_at DESC, rowid DESC")]
    sessions: Dict[str, List[Dict[str, Any]]] = {}
    for r in conn.execute("SELECT * FROM plan_sessions WHERE session_date IS NOT NULL ORDER BY session_date, rowid"):
        sessions.setdefault(r["plan_id"], []).append(dict(r))
    conn.close()

    runs_by_week: Dict[date, List[Dict[str, Any]]] = {}
    for a in acts:
        d = local_date_of(a["date"])
        if d and first <= d <= current + timedelta(days=6):
            runs_by_week.setdefault(_monday(d), []).append({"km": (a["distance_m"] or 0) / 1000.0,
                                                           "min": (a["duration_s"] or 0) / 60.0})

    def plan_week(p, ws):
        we = (ws + timedelta(days=6)).isoformat()
        return [s for s in sessions.get(p["id"], []) if ws.isoformat() <= s["session_date"] <= we]

    out_weeks = []
    for i in range(weeks):
        ws = current - timedelta(weeks=i)
        covering = [p for p in plans if p["start_date"] <= ws.isoformat() and (p.get("end_date") or "") >= ws.isoformat()]
        record = next((p for p in covering if any(s.get("status") in LOGGED for s in plan_week(p, ws))), None) \
            or next((p for p in covering if p.get("status") != "discarded"), None)
        runs = runs_by_week.get(ws, [])
        week = {
            "start": ws.isoformat(), "label": _label(ws), "is_current": ws == current,
            "actual_km": round(sum(r["km"] for r in runs), 1), "runs": len(runs),
            "longest_km": round(max((r["km"] for r in runs), default=0.0), 1),
            "actual_min": round(sum(r["min"] for r in runs)),
            "plan_id": record["id"] if record else None,
        }
        if record:
            ps = plan_week(record, ws)
            past = [s for s in ps if s["session_date"] <= today.isoformat()]
            comp = _compliance_for(past) if past else None
            longs = [s for s in ps if _prescribed(s, "session_type") == "Long Run"]
            week.update({
                "planned_km": round(sum(_prescribed(s, "distance_km") or 0.0 for s in ps), 1),
                "plan_status": record.get("status"),
                "plan_created": str(record.get("created_at") or "")[:10],
                "compliance": comp,
                "long_run": ({"planned_km": _prescribed(longs[0], "distance_km"),
                              "actual_km": longs[0].get("actual_distance_km"),
                              "status": longs[0].get("status") or "Pending"} if longs else None),
                "skipped": sum(1 for s in past if s.get("status") == "Skipped"),
            })
        else:
            week.update({"planned_km": None, "compliance": None, "long_run": None, "skipped": 0})
        out_weeks.append(week)

    plan_rows = []
    for p in plans:
        ss = sessions.get(p["id"], [])
        past = [s for s in ss if s["session_date"] <= today.isoformat()]
        comp = _compliance_for(past) if past else None
        plan_rows.append({
            "id": p["id"], "created": str(p.get("created_at") or "")[:10], "start": p["start_date"],
            "end": p.get("end_date"), "status": p.get("status") or "active", "weeks": p.get("total_weeks"),
            "methodology": p.get("methodology_name"), "goal": p.get("goal_distance"),
            "planned_km": round(sum(_prescribed(s, "distance_km") or 0.0 for s in ss), 1),
            "compliance": comp,
        })

    with_plan = [w for w in out_weeks if w["compliance"] and not w["is_current"]]
    chrono = list(reversed(out_weeks))
    return {
        "weeks": out_weeks,
        "plans": plan_rows,
        "totals": {
            "actual_km": round(sum(w["actual_km"] for w in out_weeks), 1),
            "runs": sum(w["runs"] for w in out_weeks),
            "avg_week_km": round(sum(w["actual_km"] for w in out_weeks if not w["is_current"]) / max(weeks - 1, 1), 1),
            "avg_compliance_pct": (round(sum(w["compliance"]["volume_compliance_pct"] for w in with_plan) / len(with_plan), 1)
                                   if with_plan else None),
        },
        "chart": {"labels": [w["label"] for w in chrono],
                  "planned": [w["planned_km"] for w in chrono],
                  "actual": [w["actual_km"] for w in chrono]},
    }
