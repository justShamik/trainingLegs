"""Training Plan Generation Engine & Literature Methodology Router.

Generates defensible, structured weekly running plans (FR-2.1 - FR-2.5)
grounded in evidence-based running literature and verified by deterministic code guardrails.
"""
import uuid
from typing import Dict, Any, List, Optional
from app.data.queries import get_user_profile, get_dashboard_summary, get_recent_activities, calculate_weekly_compliance
from app.engine.guardrails import validate_weekly_plan
from app.engine.tracking import detect_overtraining_risk

ULTRA_DISTANCES = {"50K Ultra", "100K Ultra", "50K", "100K", "Ultra"}

def determine_prior_weekly_volume(db_path: Optional[str] = None) -> float:
    """Determine baseline weekly volume from recent training history."""
    summary = get_dashboard_summary(db_path=db_path)
    current_vol = summary.get("weekly_volume_km", 0.0)
    if current_vol > 0:
        return current_vol
        
    recent_runs = get_recent_activities(limit=10, db_path=db_path)
    if not recent_runs:
        return 30.0  # Safe default starting baseline
        
    total_dist = sum(r.get("distance_km", 0.0) for r in recent_runs)
    return max(30.0, round(total_dist / 2.0, 1))

class TrainingPlanner:
    """Core plan generator implementing distinct Road vs Ultra logic paths and adaptive feedback loops."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def generate_plan(self, is_deload: bool = False) -> Dict[str, Any]:
        """Generate a weekly training plan tailored to current goals, compliance & fatigue state."""
        profile = get_user_profile(db_path=self.db_path)
        prior_vol = determine_prior_weekly_volume(db_path=self.db_path)
        goal_distance = profile.get("race_distance_type", "Marathon")
        
        # Check weekly compliance from prior plan
        compliance = calculate_weekly_compliance(db_path=self.db_path)
        compliance_pct = compliance.get("volume_compliance_pct", 100.0)

        # Check overtraining risk signals (ACWR, HRV, Sleep)
        overtraining = detect_overtraining_risk(db_path=self.db_path)

        is_ultra = goal_distance in ULTRA_DISTANCES

        # Calculate target volume with adaptive logic
        if overtraining["is_flagged"]:
            adj = overtraining.get("recommended_adjustment_pct", -20.0)
            target_vol = round(prior_vol * (1.0 + adj / 100.0), 1)
            is_deload = True
        elif is_deload:
            target_vol = round(prior_vol * 0.75, 1)  # 25% deload reduction
        elif compliance_pct < 70.0 and compliance_pct > 0.0:
            # Low compliance (<70%) -> cap volume increase to 0% (repeat prior volume)
            target_vol = round(prior_vol * 1.0, 1)
        else:
            target_vol = round(prior_vol * 1.08, 1)  # 8% progressive overload build
            
        if is_ultra:
            plan = self._build_ultra_plan(profile, target_vol, is_deload)
        else:
            plan = self._build_road_plan(profile, target_vol, is_deload)

        # Append adaptation context to methodology rationale if triggered
        if overtraining["is_flagged"]:
            reasons_str = "; ".join(overtraining["reasons"])
            plan["methodology_rationale"] += f" ⚠️ [ADAPTATION ALERT: Fatigue detected ({reasons_str}). Volume reduced by {abs(overtraining['recommended_adjustment_pct']):.0f}%]."
        elif compliance_pct < 70.0 and compliance_pct > 0.0:
            plan["methodology_rationale"] += f" ℹ️ [ADAPTATION: Prior week compliance was {compliance_pct:.1f}% (< 70%). Volume held steady for adaptation]."

        # Enforce deterministic guardrail validation
        valid, violations = validate_weekly_plan(plan, prior_vol)
        if not valid:
            plan["total_volume_km"] = round(prior_vol * 1.0, 1)
            plan["methodology_rationale"] += f" (Guardrail sanitized: {', '.join(violations)})"
            
        return plan


    def _build_road_plan(self, profile: Dict[str, Any], target_vol: float, is_deload: bool) -> Dict[str, Any]:
        """Build plan for road distances (5K - Marathon) based on Daniels VDOT & Pfitzinger."""
        easy_vol = round(target_vol * 0.82, 1)
        quality_vol = round(target_vol * 0.18, 1)
        
        long_run_dist = round(target_vol * 0.35, 1)
        tempo_dist = round(quality_vol, 1)
        easy_run_1 = round(easy_vol * 0.35, 1)
        easy_run_2 = round(easy_vol * 0.30, 1)
        easy_run_3 = round(easy_vol * 0.35, 1)
        
        methodology = "Daniels' VDOT & Pfitzinger Periodisation"
        rationale = (
            f"Deload recovery week: -25% volume reduction for supercompensation." if is_deload else
            f"Polarised 82/18 intensity distribution targeting {profile.get('target_time_str')} at {profile.get('race_distance_type')}. "
            "Focus on aerobic threshold development and steady progressive long run."
        )

        sessions = [
            {
                "day_of_week": "Mon",
                "session_type": "Rest",
                "distance_km": 0.0,
                "duration_min": 0.0,
                "target_pace_or_hr": "Rest & Recovery",
                "stated_purpose": "Mandatory rest day for muscular repair and central nervous system recovery."
            },
            {
                "day_of_week": "Tue",
                "session_type": "Threshold",
                "distance_km": tempo_dist,
                "duration_min": round(tempo_dist * 5.0, 0),
                "target_pace_or_hr": "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)",
                "stated_purpose": "Jack Daniels LT Session: Raise lactate threshold pace and improve metabolic efficiency."
            },
            {
                "day_of_week": "Wed",
                "session_type": "Easy Aerobic",
                "distance_km": easy_run_1,
                "duration_min": round(easy_run_1 * 5.8, 0),
                "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)",
                "stated_purpose": "Aerobic conditioning run for mitochondrial capillary density."
            },
            {
                "day_of_week": "Thu",
                "session_type": "Easy Aerobic",
                "distance_km": easy_run_2,
                "duration_min": round(easy_run_2 * 5.8, 0),
                "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm (Zone 2 Active Recovery, 6:00 – 6:30 /km)",
                "stated_purpose": "Active recovery aerobic volume run."
            },
            {
                "day_of_week": "Fri",
                "session_type": "Rest",
                "distance_km": 0.0,
                "duration_min": 0.0,
                "target_pace_or_hr": "Rest & Mobility",
                "stated_purpose": "Complete rest day before weekend long run."
            },
            {
                "day_of_week": "Sat",
                "session_type": "Long Run",
                "distance_km": long_run_dist,
                "duration_min": round(long_run_dist * 5.5, 0),
                "target_pace_or_hr": "Pace Focus: 5:40 – 6:00 /km (Zone 2-3 Long Run, 138 – 152 bpm)",
                "stated_purpose": "Pfitzinger Long Run: Endurance building, glycogen storage adaptation, and race-day pacing."
            },
            {
                "day_of_week": "Sun",
                "session_type": "Easy Aerobic",
                "distance_km": easy_run_3,
                "duration_min": round(easy_run_3 * 6.0, 0),
                "target_pace_or_hr": "Heart Rate Focus: 115 – 130 bpm (Zone 1 Recovery Run, 6:30 – 7:00 /km)",
                "stated_purpose": "Hansons Recovery Run: Flushing metabolic waste and increasing weekly aerobic volume."
            }
        ]

        return {
            "id": f"plan_{uuid.uuid4().hex[:8]}",
            "version": 1,
            "goal_distance": profile.get("race_distance_type", "Marathon"),
            "race_date": profile.get("race_date"),
            "total_volume_km": round(sum(s["distance_km"] for s in sessions), 1),
            "methodology_name": methodology,
            "methodology_rationale": rationale,
            "is_deload": is_deload,
            "sessions": sessions
        }

    def _build_ultra_plan(self, profile: Dict[str, Any], target_vol: float, is_deload: bool) -> Dict[str, Any]:
        """Build plan for Ultra/Trail distances (50K+) based on House, Johnston & Jornet Uphill Athlete."""
        easy_vol = round(target_vol * 0.85, 1)
        vert_session_dist = round(target_vol * 0.20, 1)
        long_run_dist = round(target_vol * 0.40, 1)
        back_to_back_dist = round(target_vol * 0.25, 1)
        
        methodology = "Training for the Uphill Athlete (House, Johnston & Jornet)"
        rationale = (
            f"Ultra/Trail time-on-feet methodology for {profile.get('race_distance_type')}. "
            "Focus on vertical elevation gain, continuous aerobic endurance, and fatigue management."
        )

        sessions = [
            {
                "day_of_week": "Mon",
                "session_type": "Rest",
                "distance_km": 0.0,
                "duration_min": 0.0,
                "target_pace_or_hr": "Rest & Mobility",
                "stated_purpose": "Mandatory rest for muscle fiber and connective tissue repair."
            },
            {
                "day_of_week": "Tue",
                "session_type": "Vert/Time-on-Feet",
                "distance_km": vert_session_dist,
                "duration_min": round(vert_session_dist * 7.0, 0),
                "target_pace_or_hr": "Heart Rate Focus: 135 – 155 bpm (Zone 2-3 Uphill Vert, 7:30 – 8:30 /km)",
                "stated_purpose": "Uphill Athlete Vert Session: Targeted vertical climbing + 500m elevation gain for trail power."
            },
            {
                "day_of_week": "Wed",
                "session_type": "Easy Aerobic",
                "distance_km": round(easy_vol * 0.20, 1),
                "duration_min": round(easy_vol * 0.20 * 6.0, 0),
                "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy Trail, 6:15 – 6:45 /km)",
                "stated_purpose": "Aerobic base efficiency and trail agility."
            },
            {
                "day_of_week": "Thu",
                "session_type": "Rest",
                "distance_km": 0.0,
                "duration_min": 0.0,
                "target_pace_or_hr": "Rest & S&C",
                "stated_purpose": "Rest day to prepare legs for back-to-back weekend long runs."
            },
            {
                "day_of_week": "Fri",
                "session_type": "Easy Aerobic",
                "distance_km": round(easy_vol * 0.15, 1),
                "duration_min": round(easy_vol * 0.15 * 6.0, 0),
                "target_pace_or_hr": "Heart Rate Focus: 115 – 130 bpm (Zone 1 Shakeout)",
                "stated_purpose": "Shakeout run for leg turnover."
            },
            {
                "day_of_week": "Sat",
                "session_type": "Long Run",
                "distance_km": long_run_dist,
                "duration_min": round(long_run_dist * 6.5, 0),
                "target_pace_or_hr": "Pace Focus: 6:15 – 6:45 /km (Zone 2 Ultra Time-on-Feet, 130 – 145 bpm)",
                "stated_purpose": "Jason Koop Time-on-Feet Session: Sub-maximal continuous trail running & gut fueling practice."
            },
            {
                "day_of_week": "Sun",
                "session_type": "Vert/Time-on-Feet",
                "distance_km": back_to_back_dist,
                "duration_min": round(back_to_back_dist * 7.0, 0),
                "target_pace_or_hr": "Heart Rate Focus: 120 – 138 bpm (Zone 1-2 Back-to-Back Ultra)",
                "stated_purpose": "Back-to-Back Ultra Simulation: Training on pre-fatigued legs to build mental and muscular stamina."
            }
        ]

        return {
            "id": f"plan_{uuid.uuid4().hex[:8]}",
            "version": 1,
            "goal_distance": profile.get("race_distance_type", "50K Ultra"),
            "race_date": profile.get("race_date"),
            "total_volume_km": round(sum(s["distance_km"] for s in sessions), 1),
            "methodology_name": methodology,
            "methodology_rationale": rationale,
            "is_deload": is_deload,
            "sessions": sessions
        }
