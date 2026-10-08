"""Deterministic Safety Guardrails for Training Plans.

Enforces exercise science constraints strictly in Python code (AC-4.5, AC-4.6):
1. Capped Weekly Volume Increase (<= 10% rule over prior week).
2. No Back-to-Back Hard Days (Quality sessions: Threshold, VO2max, Long Run, Vert).
3. Max Consecutive Training Days (Hard cap <= 4 active days before mandatory rest).
4. 80-20 Intensity Distribution (Easy/aerobic volume >= 80% of total volume).
Evidence-rule extensions (validate_evidence_rules): acute:chronic workload ratio <= 1.3 (Gabbett 2016),
a recovery/deload week at least every 4th loading week (3:1 step loading), long run duration cap.

A goal "Race" session is not training load to distribute: it is excluded from the 80/20 check and from the
week-over-week volume cap (training_volumes), but it counts as a hard day for back-to-back/consecutive checks.
"""
from typing import Dict, Any, List, Optional, Tuple

# Hard quality sessions for back-to-back checking
HARD_SESSION_TYPES = {"Threshold", "VO2max", "Long Run", "Vert/Time-on-Feet", "Marathon Pace", "Race"}
RACE_SESSION_TYPES = {"Race"}

# Aerobic easy volume sessions for 80-20 intensity check
EASY_SESSION_TYPES = {"Easy Aerobic", "Long Run", "Rest", "S&C", "Recovery"}

def validate_plan_volume_increase(previous_volume_km: float, proposed_volume_km: float, max_percent: float = 10.0) -> bool:
    """Enforce maximum weekly volume increase constraint (~10% rule)."""
    if previous_volume_km <= 0:
        return True
    increase_percent = ((proposed_volume_km - previous_volume_km) / previous_volume_km) * 100.0
    return increase_percent <= (max_percent + 0.1)  # small float tolerance

def validate_no_back_to_back_hard_days(sessions: List[Dict[str, Any]]) -> bool:
    """Ensure hard quality sessions do not occur on consecutive days."""
    for i in range(len(sessions) - 1):
        curr_type = sessions[i].get("session_type")
        next_type = sessions[i + 1].get("session_type")
        if curr_type in HARD_SESSION_TYPES and next_type in HARD_SESSION_TYPES:
            return False
    return True

def validate_max_consecutive_days(sessions: List[Dict[str, Any]], max_consecutive: int = 4) -> bool:
    """Ensure no more than max_consecutive active running days without a Rest day."""
    consecutive = 0
    for s in sessions:
        stype = s.get("session_type", "Rest")
        if stype != "Rest":
            consecutive += 1
            if consecutive > max_consecutive:
                return False
        else:
            consecutive = 0
    return True

def validate_80_20_intensity(sessions: List[Dict[str, Any]], min_easy_percent: float = 80.0) -> bool:
    """Ensure easy/aerobic volume constitutes at least min_easy_percent of total weekly volume."""
    sessions = [s for s in sessions if s.get("session_type") not in RACE_SESSION_TYPES]
    total_vol = sum(float(s.get("distance_km") or 0.0) for s in sessions)
    if total_vol <= 0:
        return True
        
    easy_vol = sum(
        float(s.get("distance_km") or 0.0) 
        for s in sessions 
        if s.get("session_type") in EASY_SESSION_TYPES
    )
    
    easy_percent = (easy_vol / total_vol) * 100.0
    return easy_percent >= (min_easy_percent - 0.1)

def validate_weekly_plan(plan: Dict[str, Any], prior_volume_km: float) -> Tuple[bool, List[str]]:
    """Validate a full proposed weekly training plan against all deterministic guardrails.

    Returns: (is_valid: bool, violations: List[str])
    """
    violations = []
    total_vol = float(plan.get("total_volume_km", 0.0))
    sessions = plan.get("sessions", [])

    if not validate_plan_volume_increase(prior_volume_km, total_vol):
        violations.append(f"Volume increase exceeds 10% limit (Prior: {prior_volume_km}km, Proposed: {total_vol}km)")

    if not validate_no_back_to_back_hard_days(sessions):
        violations.append("Plan contains back-to-back hard days (Threshold/VO2max/Long Run on consecutive days)")

    if not validate_max_consecutive_days(sessions):
        violations.append("Plan exceeds max 4 consecutive active training days without rest")

    if not validate_80_20_intensity(sessions):
        violations.append("Plan violates 80-20 intensity distribution (Easy volume < 80%)")

    return len(violations) == 0, violations


def split_weeks(sessions: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Group sessions by week_number (sessions without one count as week 1), each in list (date) order."""
    weeks: Dict[int, List[Dict[str, Any]]] = {}
    for s in sessions:
        weeks.setdefault(int(s.get("week_number") or 1), []).append(s)
    return dict(sorted(weeks.items()))

def weekly_volumes(sessions: List[Dict[str, Any]]) -> Dict[int, float]:
    """Total prescribed km per week_number."""
    return {w: round(sum(float(s.get("distance_km") or 0.0) for s in ss), 1) for w, ss in split_weeks(sessions).items()}

def training_volumes(sessions: List[Dict[str, Any]]) -> Dict[int, float]:
    """Prescribed TRAINING km per week_number (goal race sessions excluded)."""
    return weekly_volumes([s for s in sessions if s.get("session_type") not in RACE_SESSION_TYPES])

def easy_share_by_week(sessions: List[Dict[str, Any]]) -> Dict[int, float]:
    """Easy/aerobic share (%) of training km per week (race excluded); 100.0 for an all-rest week."""
    out: Dict[int, float] = {}
    for week, ws in split_weeks(sessions).items():
        ws = [s for s in ws if s.get("session_type") not in RACE_SESSION_TYPES]
        total = sum(float(s.get("distance_km") or 0.0) for s in ws)
        easy = sum(float(s.get("distance_km") or 0.0) for s in ws if s.get("session_type") in EASY_SESSION_TYPES)
        out[week] = round(easy / total * 100.0, 1) if total > 0 else 100.0
    return out

def validate_acwr(week_volumes: List[float], history_volumes: Optional[List[float]] = None,
                  max_ratio: float = 1.3) -> List[str]:
    """Acute:chronic workload ratio per week (Gabbett 2016): week km / mean of the previous 4 weeks (history
    first, then earlier plan weeks). Weeks without any chronic data are skipped. Returns violations."""
    rolling = [float(v) for v in (history_volumes or [])]
    violations = []
    for i, vol in enumerate(week_volumes, start=1):
        chronic = rolling[-4:]
        if chronic and sum(chronic) > 0:
            ratio = vol / (sum(chronic) / len(chronic))
            if ratio > max_ratio + 0.005:
                violations.append(f"Week {i} acute:chronic ratio {ratio:.2f} exceeds {max_ratio}")
        rolling.append(float(vol))
    return violations

def validate_recovery_weeks(week_kinds: List[str], max_loading_weeks: int = 4) -> List[str]:
    """At most max_loading_weeks consecutive loading weeks (build/peak) without a deload, taper, race or
    recovery week (3:1 step loading, allowing one extra peak week that runs straight into a taper)."""
    streak, violations = 0, []
    for i, kind in enumerate(week_kinds, start=1):
        streak = streak + 1 if kind in ("build", "peak", "base") else 0
        if streak > max_loading_weeks:
            violations.append(f"Week {i} is loading week {streak} in a row without a recovery week")
    return violations

def validate_long_run_cap(sessions: List[Dict[str, Any]], max_minutes: float) -> List[str]:
    """No Long Run longer than max_minutes (Daniels: road long runs <= 150 min)."""
    return [f"Long run on {s.get('session_date') or s.get('day_of_week')} is {s.get('duration_min')} min (> {max_minutes:g})"
            for s in sessions if s.get("session_type") == "Long Run" and float(s.get("duration_min") or 0) > max_minutes + 0.5]

def validate_multiweek_plan(plan: Dict[str, Any], prior_volume_km: float, max_increase_pct: float = 10.0,
                            max_consecutive: int = 4) -> Tuple[bool, List[str]]:
    """Validate a multi-week plan: per-week volume cap (default 10%; week 1 vs prior_volume_km, race km
    excluded), 80/20 per week, and back-to-back-hard / max-consecutive-days over the whole continuous
    date-ordered session list (so week boundaries are checked too)."""
    violations: List[str] = []
    sessions = plan.get("sessions", [])
    prev = prior_volume_km
    for week, vol in training_volumes(sessions).items():
        if not validate_plan_volume_increase(prev, vol, max_increase_pct):
            violations.append(f"Week {week} volume increase exceeds {max_increase_pct:g}% limit (Prior: {prev}km, Proposed: {vol}km)")
        prev = vol
    for week, ws in split_weeks(sessions).items():
        if not validate_80_20_intensity(ws):
            violations.append(f"Week {week} violates 80-20 intensity distribution (Easy volume < 80%)")
    if not validate_no_back_to_back_hard_days(sessions):
        violations.append("Plan contains back-to-back hard days (Threshold/VO2max/Long Run/Vert on consecutive days)")
    if not validate_max_consecutive_days(sessions, max_consecutive):
        violations.append(f"Plan exceeds max {max_consecutive} consecutive active training days without rest")
    return len(violations) == 0, violations

def validate_evidence_rules(plan: Dict[str, Any], prior_volume_km: float,
                            history_volumes: Optional[List[float]] = None, max_increase_pct: float = 10.0,
                            max_consecutive: int = 4, long_run_max_min: Optional[float] = None) -> Tuple[bool, List[str]]:
    """validate_multiweek_plan plus ACWR <= 1.3, recovery-week frequency (needs plan["week_summaries"] kinds)
    and the long-run duration cap."""
    ok, violations = validate_multiweek_plan(plan, prior_volume_km, max_increase_pct, max_consecutive)
    sessions = plan.get("sessions", [])
    violations += validate_acwr(list(training_volumes(sessions).values()), history_volumes)
    kinds = [w.get("kind", "build") for w in plan.get("week_summaries", [])]
    if kinds:
        violations += validate_recovery_weeks(kinds)
    if long_run_max_min:
        violations += validate_long_run_cap(sessions, long_run_max_min)
    return len(violations) == 0, violations
