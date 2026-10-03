"""Training Plan Generation Engine & Literature Methodology Router.

Generates defensible, structured, DATED 5-week running plans (FR-2.1 - FR-2.5): the current Monday-Sunday week
plus the next four, grounded in evidence-based running literature and verified by deterministic code guardrails.
"""
import uuid
from datetime import date, timedelta
from itertools import combinations
from typing import Dict, Any, List, Optional
from app.data.queries import get_user_profile, get_dashboard_summary, get_recent_activities, calculate_weekly_compliance
from app.engine.guardrails import validate_multiweek_plan
from app.engine.tracking import detect_overtraining_risk

PLAN_WEEKS = 5                      # current week + next 4
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BUILD_GROWTH = 1.08                 # +8% per build week (guardrail cap is 10%; the rest is rounding slack)
HELD_GROWTH = 1.05                  # growth after a low-compliance week 1 (week 1 itself is held flat)
DELOAD_FACTOR = 0.80                # scheduled deload: -20% vs the previous build week
FORCED_DELOAD_FACTOR = 0.75         # user-requested / first-week deload (unchanged from earlier sprints)
BUILDS_BEFORE_DELOAD = 3            # 3:1 loading -> deload lands on week 4

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
    """Core plan generator: 5 dated weeks (current Mon-Sun week + next 4), Road vs Ultra logic paths, adaptive loops.

    Periodisation: 3:1 loading. Weeks build +8% for three weeks, the next week is a -20% deload, then building
    resumes (+8%, so the week-over-week <=10% guardrail also holds on the rebound). With a normal start this gives
    build, build, build, deload, build. If week 1 is itself a deload (user request or overtraining flag) the cycle
    restarts: deload, build, build, build, deload. A race date inside the window overrides the pattern with a taper
    (race week -50%, week before -25%) and post-race recovery weeks held flat.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------ public API
    def generate_plan(self, is_deload: bool = False, today: Optional[date] = None) -> Dict[str, Any]:
        """Generate a dated 5-week training plan tailored to current goals, compliance & fatigue state."""
        today = today or date.today()
        start = today - timedelta(days=today.weekday())            # Monday of the current week
        end = start + timedelta(days=7 * PLAN_WEEKS - 1)             # Sunday of week 5

        profile = get_user_profile(db_path=self.db_path)
        prior_vol = determine_prior_weekly_volume(db_path=self.db_path)
        goal_distance = profile.get("race_distance_type", "Marathon")

        # Check weekly compliance from prior plan
        compliance = calculate_weekly_compliance(db_path=self.db_path, today=today)
        compliance_pct = compliance.get("volume_compliance_pct", 100.0)

        # Check overtraining risk signals (ACWR, HRV, Sleep)
        overtraining = detect_overtraining_risk(db_path=self.db_path)

        is_ultra = goal_distance in ULTRA_DISTANCES
        held = False

        # Week-1 target volume with adaptive logic
        if overtraining["is_flagged"]:
            adj = overtraining.get("recommended_adjustment_pct", -20.0)
            week1_vol = round(prior_vol * (1.0 + adj / 100.0), 1)
            is_deload = True
        elif is_deload:
            week1_vol = round(prior_vol * FORCED_DELOAD_FACTOR, 1)  # 25% deload reduction
        elif compliance_pct < 70.0 and compliance_pct > 0.0:
            week1_vol = round(prior_vol * 1.0, 1)  # low compliance (<70%) -> repeat prior volume
            held = True
        else:
            week1_vol = round(prior_vol * BUILD_GROWTH, 1)  # 8% progressive overload build

        schedule = self._week_schedule(week1_vol, is_deload, held, start, profile.get("race_date"))
        layout = self._solve_layout(profile.get("available_days"))
        niggles = self._active_niggles(profile.get("current_niggles"))

        sessions: List[Dict[str, Any]] = []
        for wk in schedule:
            sessions.extend(self._build_week(wk, layout, is_ultra, niggles))

        if is_ultra:
            methodology = "Training for the Uphill Athlete (House, Johnston & Jornet)"
            rationale = (
                f"Ultra/Trail time-on-feet methodology for {goal_distance}. "
                "Focus on vertical elevation gain, continuous aerobic endurance, and fatigue management."
            )
        else:
            methodology = "Daniels' VDOT & Pfitzinger Periodisation"
            rationale = (
                "Deload recovery week: -25% volume reduction for supercompensation." if is_deload else
                f"Polarised 82/18 intensity distribution targeting {profile.get('target_time_str')} at {goal_distance}. "
                "Focus on aerobic threshold development and steady progressive long run."
            )
        week_vols = {w["week_number"]: round(sum(s["distance_km"] for s in sessions if s["week_number"] == w["week_number"]), 1)
                     for w in schedule}
        pattern = ", ".join(f"W{w['week_number']} {w['kind']} {week_vols[w['week_number']]:.1f}km" for w in schedule)
        rationale += f" 5-week dated plan ({start.isoformat()} to {end.isoformat()}), 3:1 loading: {pattern}."
        if niggles:
            rationale += f" Quality intensity replaced by easy running while niggle(s) active ({niggles})."

        # Append adaptation context to methodology rationale if triggered
        if overtraining["is_flagged"]:
            reasons_str = "; ".join(overtraining["reasons"])
            rationale += f" ⚠️ [ADAPTATION ALERT: Fatigue detected ({reasons_str}). Volume reduced by {abs(overtraining['recommended_adjustment_pct']):.0f}%]."
        elif held:
            rationale += f" ℹ️ [ADAPTATION: Prior week compliance was {compliance_pct:.1f}% (< 70%). Volume held steady for adaptation]."

        plan = {
            "id": f"plan_{uuid.uuid4().hex[:8]}",
            "version": 1,
            "goal_distance": goal_distance,
            "race_date": profile.get("race_date"),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_weeks": PLAN_WEEKS,
            "total_volume_km": week_vols[1],  # week 1 (current week) volume
            "methodology_name": methodology,
            "methodology_rationale": rationale,
            "is_deload": is_deload,
            "week_summaries": [
                {"week_number": w["week_number"], "start_date": w["start"].isoformat(),
                 "end_date": (w["start"] + timedelta(days=6)).isoformat(), "kind": w["kind"],
                 "volume_km": week_vols[w["week_number"]]}
                for w in schedule
            ],
            "sessions": sessions,
        }

        # Enforce deterministic guardrail validation across all weeks (volume cap, 80/20, hard days, consecutive days)
        valid, violations = validate_multiweek_plan(plan, prior_vol)
        if not valid:
            plan["methodology_rationale"] += f" (Guardrail warning: {'; '.join(violations)})"

        return plan

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_days(available_days: Optional[str]) -> List[int]:
        days = set()
        for part in str(available_days or "").split(","):
            key = part.strip()[:3].title()
            if key in WEEKDAYS:
                days.add(WEEKDAYS.index(key))
        return sorted(days) if days else [0, 1, 3, 5, 6]  # profile default: Mon,Tue,Thu,Sat,Sun

    @staticmethod
    def _active_niggles(niggles: Optional[str]) -> str:
        text = (niggles or "").strip()
        return "" if text.lower() in ("", "none", "n/a", "no", "nil") else text

    @staticmethod
    def _week_schedule(week1_vol: float, week1_deload: bool, held: bool, start: date, race_date: Optional[str]) -> List[Dict[str, Any]]:
        """Periodise volumes for the 5 weeks: week_number, start Monday, nominal volume_km, kind."""
        try:
            race = date.fromisoformat(str(race_date)[:10]) if race_date else None
        except ValueError:
            race = None
        if race is not None and race < start:
            race = None  # race already run: no taper logic

        def race_kind(week_start: date) -> Optional[str]:
            if race is None:
                return None
            days_to = (race - week_start).days
            if 0 <= days_to <= 6:
                return "race"
            if 7 <= days_to <= 13:
                return "taper"
            if days_to < 0:
                return "recovery"
            return None

        weeks: List[Dict[str, Any]] = []
        streak = 0
        prev = week1_vol
        for n in range(1, PLAN_WEEKS + 1):
            wstart = start + timedelta(days=7 * (n - 1))
            rk = race_kind(wstart)
            if n == 1:
                vol = week1_vol
                if rk == "race":
                    vol = round(vol * 0.5, 1)
                elif rk == "taper":
                    vol = round(vol * 0.75, 1)
                kind = rk if rk in ("race", "taper") else ("deload" if week1_deload else "build")
                streak = 1 if kind == "build" else 0
            elif rk == "race":
                vol, kind, streak = round(prev * 0.5, 1), "race", 0
            elif rk == "taper":
                vol, kind, streak = round(prev * 0.75, 1), "taper", 0
            elif rk == "recovery":
                vol, kind, streak = round(prev * 1.0, 1), "recovery", 0
            elif streak >= BUILDS_BEFORE_DELOAD:
                vol, kind, streak = round(prev * DELOAD_FACTOR, 1), "deload", 0
            else:
                vol, kind, streak = round(prev * (HELD_GROWTH if held else BUILD_GROWTH), 1), "build", streak + 1
            weeks.append({"week_number": n, "start": wstart, "volume_km": vol, "kind": kind})
            prev = vol
        return weeks

    @staticmethod
    def _solve_layout(available_days: Optional[str]) -> Dict[str, Any]:
        """Pick run days + roles (long run, quality, easy) among available days, deterministically.

        Constraints (cyclic, since the weekly pattern repeats): long run and quality day not adjacent,
        at most 4 consecutive run days. Preferences: long run Sat > Sun, quality Tue > Thu > Wed, few adjacent runs.
        """
        avail = TrainingPlanner._parse_days(available_days)
        q_pref = {1: 0, 3: 1, 2: 2, 0: 3, 4: 4, 5: 5, 6: 6}
        lr_pref = {5: 0, 6: 1}
        for k in range(min(len(avail), 5), 0, -1):
            has_q = k >= 3
            best = None
            for combo in combinations(avail, k):
                run = set(combo)
                if any(all(((d + i) % 7) in run for i in range(5)) for d in range(7)):
                    continue  # would create 5 consecutive run days
                adjacent = sum(1 for d in run if ((d + 1) % 7) in run)
                for lr in combo:
                    for q in (combo if has_q else (None,)):
                        if q is not None and (q == lr or (q - lr) % 7 in (1, 6)):
                            continue
                        score = 10 * lr_pref.get(lr, 3) + (3 * q_pref[q] if q is not None else 0) + adjacent
                        if best is None or score < best[0]:
                            best = (score, combo, lr, q)
            if best:
                _, combo, lr, q = best
                return {"run_days": list(combo), "long_run_day": lr, "quality_day": q, "k": k}
        return {"run_days": [avail[0]], "long_run_day": avail[0], "quality_day": None, "k": 1}

    # (long run share, quality share) of weekly volume by number of run days; the remainder is easy running
    _ROAD_SHARES = {5: (0.32, 0.16), 4: (0.34, 0.17), 3: (0.38, 0.18), 2: (0.55, 0.0), 1: (1.0, 0.0)}
    _ULTRA_SHARES = {5: (0.36, 0.18), 4: (0.38, 0.18), 3: (0.42, 0.18), 2: (0.55, 0.0), 1: (1.0, 0.0)}

    def _build_week(self, wk: Dict[str, Any], layout: Dict[str, Any], is_ultra: bool, niggles: str) -> List[Dict[str, Any]]:
        vol = wk["volume_km"]
        run_days, lr_day, q_day, k = layout["run_days"], layout["long_run_day"], layout["quality_day"], layout["k"]
        lr_share, q_share = (self._ULTRA_SHARES if is_ultra else self._ROAD_SHARES)[k]
        easy_days = [d for d in run_days if d not in (lr_day, q_day)]
        after_lr = (lr_day + 1) % 7
        weights = {d: ((1.6 if is_ultra else 0.8) if d == after_lr else 1.0) for d in easy_days}
        easy_share = max(0.0, 1.0 - lr_share - q_share)
        wsum = sum(weights.values()) or 1.0
        deload_note = " (Deload week: reduced volume.)" if wk["kind"] == "deload" else ""
        sessions: List[Dict[str, Any]] = []
        easy_i = 0
        for offset in range(7):
            d = wk["start"] + timedelta(days=offset)
            if offset == lr_day:
                s = self._long_run(round(vol * lr_share, 1), is_ultra)
            elif offset == q_day:
                s = self._quality(round(vol * q_share, 1), is_ultra, niggles)
            elif offset in weights:
                s = self._easy(round(vol * easy_share * weights[offset] / wsum, 1), is_ultra, offset == after_lr, easy_i)
                easy_i += 1
            else:
                s = self._rest(is_ultra, (offset + 1) % 7 == lr_day)
            s["week_number"] = wk["week_number"]
            s["session_date"] = d.isoformat()
            s["day_of_week"] = WEEKDAYS[offset]
            if deload_note and s["session_type"] != "Rest":
                s["stated_purpose"] += deload_note
            sessions.append(s)
        return sessions

    @staticmethod
    def _rest(is_ultra: bool, before_long_run: bool) -> Dict[str, Any]:
        if before_long_run:
            target = "Rest & S&C" if is_ultra else "Rest & Mobility"
            purpose = "Rest day to prepare legs for the long run."
        else:
            target = "Rest & Mobility" if is_ultra else "Rest & Recovery"
            purpose = "Rest day for muscular repair and central nervous system recovery."
        return {"session_type": "Rest", "distance_km": 0.0, "duration_min": 0.0,
                "target_pace_or_hr": target, "stated_purpose": purpose}

    @staticmethod
    def _long_run(dist: float, is_ultra: bool) -> Dict[str, Any]:
        if is_ultra:
            return {"session_type": "Long Run", "distance_km": dist, "duration_min": round(dist * 6.5, 0),
                    "target_pace_or_hr": "Pace Focus: 6:15 – 6:45 /km (Zone 2 Ultra Time-on-Feet, 130 – 145 bpm)",
                    "stated_purpose": "Jason Koop Time-on-Feet Session: Sub-maximal continuous trail running & gut fueling practice."}
        return {"session_type": "Long Run", "distance_km": dist, "duration_min": round(dist * 5.5, 0),
                "target_pace_or_hr": "Pace Focus: 5:40 – 6:00 /km (Zone 2-3 Long Run, 138 – 152 bpm)",
                "stated_purpose": "Pfitzinger Long Run: Endurance building, glycogen storage adaptation, and race-day pacing."}

    @staticmethod
    def _quality(dist: float, is_ultra: bool, niggles: str) -> Dict[str, Any]:
        if niggles:
            return {"session_type": "Easy Aerobic", "distance_km": dist, "duration_min": round(dist * 6.0, 0),
                    "target_pace_or_hr": "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)",
                    "stated_purpose": f"Easy aerobic run replacing the quality session while niggle(s) are active ({niggles})."}
        if is_ultra:
            return {"session_type": "Vert/Time-on-Feet", "distance_km": dist, "duration_min": round(dist * 7.0, 0),
                    "target_pace_or_hr": "Heart Rate Focus: 135 – 155 bpm (Zone 2-3 Uphill Vert, 7:30 – 8:30 /km)",
                    "stated_purpose": "Uphill Athlete Vert Session: Targeted vertical climbing + 500m elevation gain for trail power."}
        return {"session_type": "Threshold", "distance_km": dist, "duration_min": round(dist * 5.0, 0),
                "target_pace_or_hr": "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)",
                "stated_purpose": "Jack Daniels LT Session: Raise lactate threshold pace and improve metabolic efficiency."}

    @staticmethod
    def _easy(dist: float, is_ultra: bool, after_long_run: bool, idx: int) -> Dict[str, Any]:
        if is_ultra and after_long_run:
            target, purpose, pace = ("Heart Rate Focus: 120 – 138 bpm (Zone 1-2 Back-to-Back Ultra)",
                                     "Back-to-Back Ultra Simulation: Training on pre-fatigued legs to build mental and muscular stamina.", 7.0)
        elif is_ultra:
            target, purpose, pace = (
                ("Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy Trail, 6:15 – 6:45 /km)", "Aerobic base efficiency and trail agility.", 6.0)
                if idx % 2 == 0 else
                ("Heart Rate Focus: 115 – 130 bpm (Zone 1 Shakeout)", "Shakeout run for leg turnover.", 6.0))
        elif after_long_run:
            target, purpose, pace = ("Heart Rate Focus: 115 – 130 bpm (Zone 1 Recovery Run, 6:30 – 7:00 /km)",
                                     "Hansons Recovery Run: Flushing metabolic waste and increasing weekly aerobic volume.", 6.0)
        elif idx % 2 == 0:
            target, purpose, pace = ("Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)",
                                     "Aerobic conditioning run for mitochondrial capillary density.", 5.8)
        else:
            target, purpose, pace = ("Heart Rate Focus: 130 – 145 bpm (Zone 2 Active Recovery, 6:00 – 6:30 /km)",
                                     "Active recovery aerobic volume run.", 5.8)
        return {"session_type": "Easy Aerobic", "distance_km": dist, "duration_min": round(dist * pace, 0),
                "target_pace_or_hr": target, "stated_purpose": purpose}
