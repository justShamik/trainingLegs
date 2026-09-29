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
