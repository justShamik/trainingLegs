"""Runner Strength & Conditioning Generator Engine.

FR-4.1 - FR-4.5 compliance:
- Generates targeted S&C workouts aligned to running phase (Base, Build, Peak, Taper).
- Dynamically filters out contraindicated exercises based on active user niggles and injuries.
- Prescribes sets, reps, RPE, equipment requirements, and safety/form cues.
"""
import uuid
from typing import Dict, Any, List, Optional
from app.data.queries import get_user_profile, get_available_exercises, get_active_training_plan

PHASE_RULES = {
    "Base": {
        "sets": 3,
        "reps": "10-12 reps",
        "rpe": 7,
        "focus": "Structural Hypertrophy, Motor Control & Connective Tissue Capacity",
        "plyo_allowed": False
    },
    "Build": {
        "sets": 3,
        "reps": "5-6 reps",
        "rpe": 8,
        "focus": "Maximal Strength & High Motor Unit Recruitment",
        "plyo_allowed": True
    },
    "Peak": {
        "sets": 3,
        "reps": "4 reps (Explosive)",
        "rpe": 8,
        "focus": "Rate of Force Development & Reactive Power",
        "plyo_allowed": True
    },
    "Taper": {
        "sets": 2,
        "reps": "6 light reps",
        "rpe": 5,
        "focus": "Maintenance & Central Nervous System Recovery",
        "plyo_allowed": False
    }
}

class StrengthEngine:
    """S&C Generator Engine enforcing runner phase periodisation and niggle safety."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def generate_workout(self, phase: Optional[str] = None) -> Dict[str, Any]:
        """Generate a structured, safe runner strength workout."""
        profile = get_user_profile(db_path=self.db_path)
        current_niggles = profile.get("current_niggles", "")
        
        # Determine phase if not explicitly provided
        if not phase:
            active_plan = get_active_training_plan(db_path=self.db_path)
            if active_plan:
                if active_plan.get("is_deload"):
                    phase = "Taper"
                else:
                    phase = "Base"
            else:
                phase = "Base"

        if phase not in PHASE_RULES:
            phase = "Base"

        rule = PHASE_RULES[phase]
        available_exercises = get_available_exercises(current_niggles, db_path=self.db_path)

        # Categorize available safe exercises
        by_category = {}
        for ex in available_exercises:
            cat = ex["category"]
            by_category.setdefault(cat, []).append(ex)

        selected_exercises = []
        safety_notices = []

        # Target 5 core movement patterns for distance runners
        desired_categories = ["Single-Leg", "Hinge", "Core", "Calf/Ankle", "Upper Body"]
        if rule["plyo_allowed"] and "Plyo" in by_category:
            desired_categories.append("Plyo")

        for cat in desired_categories:
            pool = by_category.get(cat, [])
            if pool:
                ex = dict(pool[0])  # Select top matching exercise
                # Apply phase periodisation
                ex["prescribed_sets"] = rule["sets"]
                ex["prescribed_reps"] = rule["reps"]
                ex["prescribed_rpe"] = rule["rpe"]
                selected_exercises.append(ex)
            else:
                # If a category was excluded due to niggles (e.g. Plyo or Knee Single-Leg)
                safety_notices.append(f"Excluded {cat} exercises due to active niggle constraint ({current_niggles}).")

        if current_niggles and current_niggles.lower() not in ("none", "n/a", ""):
            safety_notices.insert(0, f"Active niggle safety filter applied: '{current_niggles}'. Contraindicated exercises removed.")

        return {
            "id": f"str_{uuid.uuid4().hex[:8]}",
            "phase": phase,
            "focus_area": rule["focus"],
            "total_duration_min": 35 if phase == "Taper" else 45,
            "niggles_addressed": current_niggles or "None",
            "safety_notices": safety_notices,
            "exercises": selected_exercises,
            "status": "Prescribed"
        }


# ---------------------------------------------------------------------------------------------------------------
# S&C schedule generated together with a running plan
#
# Sessions per week follow the running phase (strength is built in base/build, maintained in peak, kept light in a
# deload or taper week and dropped in race and post-race recovery weeks). A session never goes on the day BEFORE a
# hard run (long run, quality, race, test) so legs are fresh for it, never on race day, never within 4 days of the
# race, and two S&C sessions are at least 2 days apart. Easy-run and rest days are preferred; a quality day (after
# the run, "keep hard days hard") is the last resort. Past days of the current week are skipped.
SC_PER_WEEK = {"base": 2, "build": 2, "peak": 1, "taper": 1, "race": 0, "recovery": 0}
SC_PHASE = {"base": "Base", "build": "Build", "peak": "Peak", "taper": "Taper", "race": "Taper", "recovery": "Taper"}
SC_HARD = {"Threshold", "VO2max", "Long Run", "Vert/Time-on-Feet", "Marathon Pace", "Race", "LTHR Test", "Tune-up Race"}
SC_RACES = {"Race", "Tune-up Race"}


def schedule_strength_for_plan(plan: Dict[str, Any], today=None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """S&C workouts (with session_date / week_number) for a generated running plan."""
    from datetime import date, timedelta

    today = today or date.today()
    engine = StrengthEngine(db_path=db_path)
    sessions = {s["session_date"]: s for s in plan.get("sessions", [])}
    race_dates = [date.fromisoformat(d) for d, s in sessions.items() if s.get("session_type") in SC_RACES]
    out: List[Dict[str, Any]] = []
    for w in plan.get("week_summaries", []):
        kind, phase = w.get("kind"), w.get("phase", "base")
        n = 1 if kind == "deload" and SC_PER_WEEK.get(phase, 1) else SC_PER_WEEK.get(phase, 1)
        if n == 0:
            continue
        start = date.fromisoformat(w["start_date"])
        days = [start + timedelta(days=i) for i in range(7)]

        def stype(d):
            return (sessions.get(d.isoformat()) or {}).get("session_type", "Rest")

        def allowed(d):
            if d < today or stype(d) in SC_RACES or stype(d + timedelta(days=1)) in SC_HARD:
                return False
            return not any(0 <= (r - d).days <= 4 for r in race_dates)

        rank = {"Easy Aerobic": 0, "Rest": 1}
        candidates = sorted((d for d in days if allowed(d) and stype(d) != "Long Run"),
                            key=lambda d: (rank.get(stype(d), 2), d))
        chosen: List[date] = []
        for d in candidates:
            if len(chosen) == n:
                break
            if all(abs((d - c).days) >= 2 for c in chosen):
                chosen.append(d)
        workout_phase = "Taper" if kind == "deload" else SC_PHASE.get(phase, "Base")
        for d in sorted(chosen):
            wk = engine.generate_workout(phase=workout_phase)
            wk.update({"session_date": d.isoformat(), "week_number": w["week_number"]})
            out.append(wk)
    return out
