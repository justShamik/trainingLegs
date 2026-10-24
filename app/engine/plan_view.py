"""View-model for the dated multi-week Training Plan page (pure functions, no DB access)."""
import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

_KIND_LABELS = {"build": "Build", "deload": "Deload", "taper": "Taper", "race": "Race week", "recovery": "Post-race recovery",
                "tuneup": "Tune-up race week"}


def plan_decisions(plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Structured planner decisions stored with the plan (training_plans.decisions_json); None for older plans."""
    if not plan:
        return None
    raw = plan.get("decisions") or plan.get("decisions_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or not raw.get("items"):
        return None
    labels = {s["key"]: s["label"] for s in raw.get("sources", []) if isinstance(s, dict) and "key" in s}
    items: List[Dict[str, Any]] = []
    for it in raw["items"]:
        items.append({**it, "source_labels": [labels.get(k, k) for k in it.get("sources", [])]})
    return {**raw, "items": items}


def _d(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def fmt_long(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}"        # Mon 29 Sep 2026


def fmt_short(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"           # Tue 30 Sep


def fmt_range(a: date, b: date) -> str:
    return f"{a.day} {a.strftime('%b')} - {b.day} {b.strftime('%b')}"  # 29 Sep - 5 Oct


PHASE_INFO = {
    "base": ("Base", "Aerobic foundation: mostly easy running, steady long-run growth, one controlled quality session."),
    "build": ("Build", "Race-specific strength: threshold work and longer long runs on top of the aerobic base."),
    "peak": ("Peak", "Highest load and race-pace rehearsal: sharpest workouts and the longest runs."),
    "taper": ("Taper", "Volume comes down, intensity stays: arrive fresh (Bosquet 2007)."),
    "race": ("Race", "Race week: short sharpeners, rest and the goal race."),
    "recovery": ("Recovery", "Easy running only while the body recovers from the race."),
}


def build_phases(weeks: List[Dict[str, Any]], week_meta: Dict[int, Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """Group consecutive weeks into phases (base / build / peak / taper / race) for the season outline."""
    phases: List[Dict[str, Any]] = []
    for w in weeks:
        key = (week_meta.get(w["number"]) or {}).get("phase") or "base"
        if not phases or phases[-1]["key"] != key:
            name, purpose = PHASE_INFO.get(key, (key.title(), ""))
            phases.append({"key": key, "name": name, "purpose": purpose, "weeks": [], "sessions_by_type": {}})
        ph = phases[-1]
        ph["weeks"].append(w)
        for s in w["sessions"]:
            t = s.get("session_type")
            if t and t not in ("Rest", "Easy Aerobic"):
                ph["sessions_by_type"][t] = ph["sessions_by_type"].get(t, 0) + 1
    for ph in phases:
        vols = [w["volume_km"] for w in ph["weeks"]]
        ph.update(start=ph["weeks"][0]["start"], end=ph["weeks"][-1]["end"],
                  range_label=fmt_range(ph["weeks"][0]["start"], ph["weeks"][-1]["end"]),
                  n_weeks=len(ph["weeks"]), km_min=min(vols), km_max=max(vols),
                  is_current=any(w["is_current"] for w in ph["weeks"]),
                  is_past=ph["weeks"][-1]["end"] < today,
                  first_week=ph["weeks"][0]["number"], last_week=ph["weeks"][-1]["number"],
                  runs_done=sum(w["runs_done"] for w in ph["weeks"]), runs_total=sum(w["runs_total"] for w in ph["weeks"]))
    return phases


def build_plan_view(plan: Optional[Dict[str, Any]], today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Group a plan's sessions into dated weeks with volume, delta %, status and today/current-week flags."""
    if not plan:
        return None
    today = today or date.today()
    sessions = plan.get("sessions", [])
    start = _d(plan.get("start_date")) or _d(next((s.get("session_date") for s in sessions if s.get("session_date")), None)) or today
    total_weeks = int(plan.get("total_weeks") or max([int(s.get("week_number") or 1) for s in sessions] or [1]))
    end = _d(plan.get("end_date")) or (start + timedelta(days=7 * total_weeks - 1))

    ended = today > end
    if today < start:
        current_week = 1
    else:
        current_week = min((today - start).days // 7 + 1, total_weeks)

    decisions = plan_decisions(plan)
    week_meta = {int(w.get("week_number") or 0): w for w in (decisions or {}).get("weeks", [])}
    weeks = []
    prev_vol = None
    for n in range(1, total_weeks + 1):
        w_start = start + timedelta(days=7 * (n - 1))
        w_end = w_start + timedelta(days=6)
        w_sessions = []
        for s in sessions:
            if int(s.get("week_number") or 1) != n:
                continue
            sd = _d(s.get("session_date"))
            w_sessions.append({**s, "date_label": fmt_short(sd) if sd else s.get("day_of_week"),
                               "is_today": sd == today, "is_past": bool(sd and sd < today)})
        volume = round(sum(float(s.get("distance_km") or 0.0) for s in w_sessions), 1)
        delta = round((volume - prev_vol) / prev_vol * 100.0, 1) if prev_vol else None
        runs = [s for s in w_sessions if s.get("session_type") != "Rest"]
        done = sum(1 for s in runs if s.get("status") in ("Completed", "Modified"))
        meta = week_meta.get(n)
        if meta:
            kind = _KIND_LABELS.get(meta.get("kind"), str(meta.get("kind", "")).title())
            if meta.get("kind") == "build" and meta.get("phase"):
                kind += f" ({meta['phase']} phase)"
        elif n == 1 and plan.get("is_deload"):
            kind = "Deload"
        elif delta is not None and delta <= -10.0:
            kind = "Deload / recovery"
        else:
            kind = "Build"
        weeks.append({
            "number": n, "start": w_start, "end": w_end, "range_label": fmt_range(w_start, w_end),
            "is_current": n == current_week and not ended, "volume_km": volume, "delta_pct": delta,
            "kind": kind, "sessions": w_sessions, "runs_total": len(runs), "runs_done": done,
        })
        prev_vol = volume

    if ended:
        notice = {"level": "ended", "text": (
            f"This plan has ended (it covered {fmt_long(start)} - {fmt_long(end)}). "
            "Generate a new plan to cover the current week and the next four.")}
    elif current_week > 1:
        notice = {"level": "moved", "text": (
            f"You are now in week {current_week} of {total_weeks}. Regenerate to roll the plan forward "
            "so it again covers the current week plus the next four.")}
    else:
        notice = None

    if plan.get("plan_kind") == "season":
        notice = {"level": "ended", "text": f"This plan ended on {fmt_long(end)}. Create a plan for your next race."} if ended else None

    return {
        "phases": build_phases(weeks, week_meta, today),
        "start": start, "end": end, "total_weeks": total_weeks, "current_week": current_week, "ended": ended,
        "period_text": f"Plan period: {fmt_long(start)} – {fmt_long(end)} "
                       f"({total_weeks} week{'s' if total_weeks != 1 else ''}"
                       f"{': current week + next 4' if total_weeks == 5 else ''})",
        "weeks": weeks, "notice": notice, "today": today, "decisions": decisions,
    }
