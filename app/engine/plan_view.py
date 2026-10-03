"""View-model for the dated multi-week Training Plan page (pure functions, no DB access)."""
from datetime import date, timedelta
from typing import Any, Dict, Optional


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
        if n == 1 and plan.get("is_deload"):
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

    return {
        "start": start, "end": end, "total_weeks": total_weeks, "current_week": current_week, "ended": ended,
        "period_text": f"Plan period: {fmt_long(start)} – {fmt_long(end)} "
                       f"({total_weeks} week{'s' if total_weeks != 1 else ''}"
                       f"{': current week + next 4' if total_weeks == 5 else ''})",
        "weeks": weeks, "notice": notice, "today": today,
    }
