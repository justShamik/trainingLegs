"""Deterministic Safety Guardrails for Training Plans.

Enforces exercise science constraints strictly in Python code (AC-4.5, AC-4.6):
1. Capped Weekly Volume Increase (<= 10% rule over prior week).
2. No Back-to-Back Hard Days (Quality sessions: Threshold, VO2max, Long Run, Vert).
3. Max Consecutive Training Days (Hard cap <= 4 active days before mandatory rest).
4. 80-20 Intensity Distribution (Easy/aerobic volume >= 80% of total volume).
"""
from typing import Dict, Any, List, Tuple

# Hard quality sessions for back-to-back checking
HARD_SESSION_TYPES = {"Threshold", "VO2max", "Long Run", "Vert/Time-on-Feet"}

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
