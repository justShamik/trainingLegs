"""Send planned runs to the COROS calendar: preview first, write only after explicit confirmation.

COROS MCP cannot move or delete scheduled workouts (COROS app only), so this app:
- reads the COROS calendar before every preview and every push (duplicate check),
- owns at most one COROS workout per date and remembers its idInPlan (coros_pushes),
- updates that workout in place when the plan changes instead of creating a second one,
- refuses to push when the preview the user confirmed no longer matches (token check).
"""
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.coros_push.workouts import build_course, course_hash, describe_sections
from app.data.db import get_db_connection
from app.data.queries import get_active_training_plan

logger = logging.getLogger("coach.coros_push")

MAX_AHEAD_DAYS = 90          # COROS accepts today .. today + 90
DONE_STATUSES = {"Completed", "Modified", "Skipped"}
WRITE_STATES = ("new", "missing", "update")


class PushError(Exception):
    pass


class StalePreview(PushError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pushes(db_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM coros_pushes").fetchall()
    except Exception:
        rows = []
    conn.close()
    return {r["session_date"]: dict(r) for r in rows}


def push_status_by_date(plan: Optional[Dict[str, Any]], db_path: Optional[str] = None) -> Dict[str, str]:
    """'synced' when COROS has the current version of that day's run, 'outdated' when the plan changed since."""
    if not plan:
        return {}
    pushes = _pushes(db_path)
    out = {}
    for s in plan.get("sessions", []):
        p = pushes.get(s.get("session_date"))
        if not p:
            continue
        course, _ = build_course(s)
        out[s["session_date"]] = "synced" if course and course_hash(course) == p["course_hash"] else "outdated"
    return out


def build_preview(db_path: Optional[str] = None, today: Optional[date] = None, days: int = 14,
                  client=None, window_start: Optional[date] = None,
                  window_end: Optional[date] = None) -> Dict[str, Any]:
    """What would be sent for the next `days` days, compared with what COROS already has. Writes nothing."""
    from app.mcp_client.coros_client import CorosMCPClient

    today = today or date.today()
    plan = get_active_training_plan(db_path=db_path)
    if not plan:
        return {"plan": None, "items": [], "error": "No active training plan. Generate one first."}
    days = max(1, min(int(days), MAX_AHEAD_DAYS + 1))
    first = max(today, window_start or today)
    last = window_end or (today + timedelta(days=days - 1))
    end = min(last, today + timedelta(days=MAX_AHEAD_DAYS),
              date.fromisoformat(plan["end_date"]) if plan.get("end_date") else last)
    sessions = [s for s in plan["sessions"] if first.isoformat() <= s["session_date"] <= end.isoformat()]

    client = client or CorosMCPClient()
    calendar = client.query_training_schedule(first, end) if sessions else []
    coros_error = None
    if calendar is None:
        failures = "; ".join(getattr(client, "call_failures", [])[-2:])
        coros_error = ("Couldn't read your COROS calendar" + (f" ({failures})" if failures else "")
                       + ". Nothing can be sent until it can be checked for duplicates.")
        calendar = []
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for c in calendar:
        by_day.setdefault(c["date"], []).append(c)
    pushes = _pushes(db_path)

    items = []
    for s in sessions:
        d = s["session_date"]
        ours = pushes.get(d)
        on_day = by_day.get(d, [])
        ours_on_coros = bool(ours and any(c.get("id_in_plan") == ours.get("id_in_plan") for c in on_day))
        others = [c["title"] for c in on_day if not (ours and c.get("id_in_plan") == ours.get("id_in_plan"))]
        course, reason = build_course(s)
        if s.get("status") in DONE_STATUSES:
            course, reason = None, f"Already {s['status'].lower()}."
        item = {"session_id": s["id"], "date": d, "day": date.fromisoformat(d).strftime("%a %d %b"),
                "session_type": s["session_type"], "distance_km": s.get("distance_km"), "others": others,
                "course": course, "steps": describe_sections(course) if course else [], "reason": reason,
                "hash": course_hash(course) if course else None, "notes": []}
        if course is None:
            item["state"] = "orphan" if (ours and ours_on_coros) else "skip"
            if item["state"] == "orphan":
                item["notes"].append(f"COROS still has your earlier \"{ours['course_name']}\" on this day. "
                                     "COROS doesn't let apps remove workouts: delete it in the COROS app.")
        elif ours and ours_on_coros:
            item["state"] = "unchanged" if ours["course_hash"] == item["hash"] else "update"
        elif ours and not coros_error:
            item["state"] = "missing"
            item["notes"].append("The workout this app sent earlier is no longer on COROS (removed in the app?). "
                                 "It will be sent again.")
        else:
            item["state"] = "new"
        if item["state"] == "new" and course and course["courseName"] in others:
            item["state"] = "duplicate"
            item["notes"].append(f"COROS already has \"{course['courseName']}\" on this day, so it isn't sent again.")
        elif item["state"] in ("new", "missing") and others:
            item["notes"].append("Also on COROS that day: " + ", ".join(f"\"{o}\"" for o in others)
                                 + ". Yours is added alongside; COROS keeps both.")
        items.append(item)

    token_src = [(i["session_id"], i["date"], i["state"], i["hash"]) for i in items]
    return {"plan": plan, "items": items, "start": first.isoformat(), "end": end.isoformat(), "days": days,
            "coros_error": coros_error, "error": None,
            "token": hashlib.sha256(json.dumps(token_src).encode("utf-8")).hexdigest()[:20],
            "writable": [i for i in items if i["state"] in WRITE_STATES]}


def _find_new_id(client, day: date, name: str, known: set) -> Optional[str]:
    cal = client.query_training_schedule(day, day) or []
    ids = [c["id_in_plan"] for c in cal if c.get("title") == name and c.get("id_in_plan") and c["id_in_plan"] not in known]
    return ids[-1] if ids else None


def _id_from(text: Optional[str]) -> Optional[str]:
    m = re.search(r"idInPlan\D{0,12}(\d+)", text or "")
    return m.group(1) if m else None


def _save(db_path, item, plan_id, id_in_plan, created: bool) -> None:
    conn = get_db_connection(db_path)
    now = _now()
    conn.execute(
        "INSERT INTO coros_pushes (session_date, session_id, plan_id, id_in_plan, course_name, course_hash, course_json,"
        " pushed_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(session_date) DO UPDATE SET"
        " session_id=excluded.session_id, plan_id=excluded.plan_id, id_in_plan=excluded.id_in_plan,"
        " course_name=excluded.course_name, course_hash=excluded.course_hash, course_json=excluded.course_json,"
        " updated_at=excluded.updated_at" + (", pushed_at=excluded.pushed_at" if created else ""),
        (item["date"], item["session_id"], plan_id, id_in_plan, item["course"]["courseName"], item["hash"],
         json.dumps(item["course"]), now, now))
    conn.commit()
    conn.close()


def push(selected: List[str], token: str, db_path: Optional[str] = None, today: Optional[date] = None,
         days: int = 14, client=None, window_start: Optional[date] = None,
         window_end: Optional[date] = None) -> List[Dict[str, Any]]:
    """Send the selected sessions exactly as previewed. Raises StalePreview if anything changed since."""
    from app.mcp_client.coros_client import CorosMCPClient

    client = client or CorosMCPClient()
    preview = build_preview(db_path=db_path, today=today, days=days, client=client,
                            window_start=window_start, window_end=window_end)
    if preview.get("error") or preview.get("coros_error"):
        raise PushError(preview.get("error") or preview["coros_error"])
    if token != preview["token"]:
        raise StalePreview("Your plan or COROS calendar changed since the preview. Check the new preview and confirm again.")
    chosen = set(selected)
    pushes = _pushes(db_path)
    known = {p["id_in_plan"] for p in pushes.values() if p.get("id_in_plan")}
    results = []
    for item in preview["writable"]:
        if item["session_id"] not in chosen:
            continue
        day = date.fromisoformat(item["date"])
        name = item["course"]["courseName"]
        res = {"date": item["date"], "day": item["day"], "name": name, "action": item["state"], "ok": False, "message": ""}
        if item["state"] in ("new", "missing"):
            ok, text = client.create_scheduled_workout(day, item["course"])
            new_id = _id_from(text) if ok else None
            if ok and not new_id:
                new_id = _find_new_id(client, day, name, known)
            if ok:
                _save(db_path, item, preview["plan"]["id"], new_id, created=True)
                known.add(new_id)
                res.update(ok=True, message="Added to your COROS calendar.")
            else:
                res["message"] = "COROS refused it: " + (text or "no reason given")[:200]
        else:
            ours = pushes[item["date"]]
            ok, details = client.query_scheduled_workout(day, ours["id_in_plan"])
            editable = re.search(r"editable\W{0,4}(true|false|yes|no)", details or "", re.I)
            if not ok or (editable and editable.group(1).lower() in ("false", "no")):
                res["message"] = ("COROS won't let this workout be changed (completed, in the past or edited in the app). "
                                  "Change it in the COROS app.")
            else:
                ok, text = client.update_scheduled_workout(day, ours["id_in_plan"], item["course"])
                if ok:
                    _save(db_path, item, preview["plan"]["id"], _id_from(text) or ours["id_in_plan"], created=False)
                    res.update(ok=True, message="Updated on your COROS calendar.")
                else:
                    res["message"] = "COROS refused the update: " + (text or "no reason given")[:200]
        logger.info('action_result action=coros_push date=%s state=%s ok=%s', item["date"], item["state"], res["ok"])
        results.append(res)
    return results
