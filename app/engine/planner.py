"""Training Plan Generation Engine: goal-profile-driven, evidence-based, DATED 5-week plans (FR-2.1 - FR-2.5).

Every Goal Profile field drives a concrete decision (all deterministic Python, ADR-002):
  race_distance_type -> methodology (Daniels/Pfitzinger road, Uphill Athlete ultra), quality-session type per phase,
                        taper length, long-run caps, post-race recovery
  race_date          -> phase of each week (base / build / peak / taper / race / recovery), taper volumes, race day
  target_time_str    -> Daniels VDOT -> E/M/T/I paces (road) or goal race pace (ultra) -> targets and durations
  weekly_hours       -> weekly volume ceiling (total prescribed running time never exceeds it)
  available_days     -> run days and roles (long run / quality / easy), consecutive-day limit
  injury_history     -> conservative progression (+5%/week) and max 3 consecutive run days
  current_niggles    -> quality sessions replaced with easy running, week-1 volume held
Each decision, the profile inputs behind it and the studies/methods it follows are returned in plan["decisions"]
and persisted with the plan (training_plans.decisions_json).

Missing or unreadable required fields are never replaced by defaults (NFR-4.1): generate_plan raises
ProfileIncompleteError listing exactly what is missing (see profile_gaps).
"""
import math
import uuid
from datetime import date, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from app.data.queries import get_user_profile, get_run_history, calculate_weekly_compliance
from app.engine.guardrails import validate_evidence_rules, training_volumes, easy_share_by_week
from app.engine.tracking import detect_overtraining_risk

PLAN_WEEKS = 5                      # current week + next 4
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULL_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

BUILD_GROWTH = 1.08                 # +8% per loading week (ADR-002 cap is 10%)
CONSERVATIVE_GROWTH = 1.05          # injury history / active niggles / low compliance
HELD_GROWTH = CONSERVATIVE_GROWTH   # kept for backwards compatibility
MAX_WEEKLY_INCREASE = 1.10          # ADR-002 10% rule, enforced while scheduling (and re-checked by guardrails)
ACWR_MAX = 1.3                      # Gabbett (2016) acute:chronic "sweet spot" upper bound
DELOAD_FACTOR = 0.80                # scheduled 3:1 deload: -20% vs the previous loading week
FORCED_DELOAD_FACTOR = 0.75         # user-requested deload in week 1
BUILDS_BEFORE_DELOAD = 3            # 3:1 step loading
NO_HISTORY_START_FRACTION = 0.40    # no runs in the last 4 weeks: start at 40% of the weekly-hours ceiling (app rule)

RACE_DISTANCE_KM = {"5K": 5.0, "10K": 10.0, "Half Marathon": 21.0975, "Marathon": 42.195,
                    "50K Ultra": 50.0, "100K Ultra": 100.0, "50K": 50.0, "100K": 100.0}
ULTRA_DISTANCES = {"50K Ultra", "100K Ultra", "50K", "100K", "Ultra"}
# Taper weeks BEFORE race week (the race week itself is also reduced). Short races ~10-14 days in total,
# marathon/ultra ~3 weeks (Pfitzinger 3-week marathon taper; Bosquet 2007 optimum 8-14 days).
TAPER_WEEKS = {"5K": 1, "10K": 1, "Half Marathon": 1, "Marathon": 2}
TAPER_FACTORS = {1: [0.70], 2: [0.80, 0.65]}       # training km vs peak week, progressive (Mujika & Padilla 2003)
RACE_WEEK_FACTOR = {1: 0.50, 2: 0.45}              # race-week training km (race itself excluded) vs peak
# (first post-race week volume vs peak, recovery weeks of easy-only running)
RECOVERY = {"5K": (0.70, 1), "10K": (0.70, 1), "Half Marathon": (0.60, 1), "Marathon": (0.50, 2)}
PEAK_PHASE_WEEKS = 3                # race-specific weeks before the taper
BUILD_PHASE_START = 12              # weeks before race when the specific build starts (12-18 week schedules)
QUALITY_SHARE = {"base": 0.12, "build": 0.16, "peak": 0.18, "taper": 0.18, "race": 0.15, "recovery": 0.0}
LONG_RUN_SHARE = {"road": {5: 0.28, 4: 0.30, 3: 0.36, 2: 0.50, 1: 1.0},
                  "ultra": {5: 0.34, 4: 0.36, 3: 0.40, 2: 0.55, 1: 1.0}}
LONG_RUN_MAX_MIN = {"road": 150.0, "ultra": 240.0}
# Daniels %HRmax bands; ultra vert Zone 3 band is an app mapping of Uphill Athlete's zone model
HR_ZONES = {"E": (0.65, 0.79), "R": (0.60, 0.70), "M": (0.80, 0.90), "T": (0.88, 0.92), "I": (0.95, 1.00),
            "V": (0.80, 0.87)}

SOURCES: Dict[str, Dict[str, str]] = {
    "daniels": {"label": "Daniels (2014)", "citation":
                "Daniels, J. (2014). Daniels' Running Formula (3rd ed.). Human Kinetics. VDOT training paces "
                "(E/M/T/I), long run <= 25-30% of weekly volume and <= 150 min, quality-volume limits."},
    "daniels_gilbert": {"label": "Daniels & Gilbert (1979)", "citation":
                        "Daniels, J. & Gilbert, J. (1979). Oxygen Power: Performance Tables for Distance Runners. "
                        "Oxygen-cost and time-to-exhaustion equations used to compute VDOT from a race time."},
    "pfitzinger": {"label": "Pfitzinger & Douglas (2019)", "citation":
                   "Pfitzinger, P. & Douglas, S. (2019). Advanced Marathoning (3rd ed.). Human Kinetics. "
                   "Mesocycle periodisation (base/endurance, lactate threshold, race preparation), lactate-threshold "
                   "and marathon-pace runs, 3-week marathon taper, post-race recovery."},
    "uphill": {"label": "House, Johnston & Jornet (2019)", "citation":
               "House, S., Johnston, S. & Jornet, K. (2019). Training for the Uphill Athlete. Patagonia. Aerobic-base "
               "dominant training, muscular-endurance/vertical sessions, long time-on-feet runs for mountain/ultra."},
    "seiler": {"label": "Seiler (2010)", "citation":
               "Seiler, S. (2010). What is best practice for training intensity and duration distribution in "
               "endurance athletes? Int J Sports Physiol Perform, 5(3), 276-291. ~80% of training at low intensity."},
    "stoggl": {"label": "Stöggl & Sperlich (2014)", "citation":
               "Stöggl, T. & Sperlich, B. (2014). Polarized training has greater impact on key endurance variables "
               "than threshold, high intensity, or high volume training. Front Physiol, 5, 33."},
    "bosquet": {"label": "Bosquet et al. (2007)", "citation":
                "Bosquet, L., Montpetit, J., Arvisais, D. & Mujika, I. (2007). Effects of tapering on performance: a "
                "meta-analysis. Med Sci Sports Exerc, 39(8), 1358-1365. ~2-week taper, volume -41-60%, intensity "
                "and frequency maintained."},
    "mujika": {"label": "Mujika & Padilla (2003)", "citation":
               "Mujika, I. & Padilla, S. (2003). Scientific bases for precompetition tapering strategies. Med Sci "
               "Sports Exerc, 35(7), 1182-1187. Progressive (non-linear) volume reduction, intensity maintained."},
    "gabbett": {"label": "Gabbett (2016)", "citation":
                "Gabbett, T. J. (2016). The training-injury prevention paradox: should athletes be training smarter "
                "and harder? Br J Sports Med, 50(5), 273-280. Acute:chronic workload ratio kept within ~0.8-1.3."},
    "van_gent": {"label": "van Gent et al. (2007)", "citation":
                 "van Gent, R. N., Siem, D., van Middelkoop, M., van Os, A. G., Bierma-Zeinstra, S. M. & Koes, B. W. "
                 "(2007). Incidence and determinants of lower extremity running injuries in long distance runners: "
                 "a systematic review. Br J Sports Med, 41(8), 469-480. Previous injury is a risk factor."},
    "bompa": {"label": "Bompa & Haff (2009)", "citation":
              "Bompa, T. O. & Haff, G. G. (2009). Periodization: Theory and Methodology of Training (5th ed.). "
              "Human Kinetics. Step loading: three loading weeks followed by an unloading or deload week."},
    "adr002": {"label": "ADR-002 guardrails", "citation":
               "Project ADR-002 deterministic guardrails (app/engine/guardrails.py): <=10% weekly volume increase, "
               "no back-to-back hard days, max 4 consecutive run days, >=80% easy volume."},
    "app": {"label": "App rule", "citation":
            "Conservative app rule (engineering choice, not taken from a specific study)."},
}


class ProfileIncompleteError(ValueError):
    """Raised when required Goal Profile fields are missing or unreadable. .gaps lists them."""

    def __init__(self, gaps: List[Dict[str, str]]):
        self.gaps = gaps
        super().__init__("Goal Profile incomplete: " + "; ".join(f"{g['label']}: {g['problem']}" for g in gaps))


# ---------------------------------------------------------------------------------------------- profile parsing
def parse_available_days(text: Optional[str]) -> Tuple[List[int], List[str]]:
    """'Mon, tue,Thursday' -> ([0, 1, 3], []) ; unrecognised tokens are returned, never guessed."""
    days, bad = set(), []
    for part in str(text or "").replace(";", ",").replace("/", ",").split(","):
        token = part.strip().lower()
        if not token:
            continue
        idx = next((i for i, (short, full) in enumerate(zip(WEEKDAYS, FULL_DAY_NAMES))
                    if token in (short.lower(), full) or (len(token) >= 3 and full.startswith(token))), None)
        if idx is None:
            bad.append(part.strip())
        else:
            days.add(idx)
    return sorted(days), bad


def _vo2(v: float) -> float:            # ml/kg/min at velocity v (m/min), Daniels & Gilbert
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _pct_max(t: float) -> float:        # fraction of VO2max sustainable for t minutes
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def vdot_from_performance(distance_m: float, minutes: float) -> float:
    return _vo2(distance_m / minutes) / _pct_max(minutes)


def _velocity_for_vo2(vo2: float) -> float:
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def _pace_for_fraction(vdot: float, fraction: float) -> float:
    """min/km at a fraction of VDOT."""
    return 1000.0 / _velocity_for_vo2(vdot * fraction)


def predict_race_minutes(vdot: float, distance_m: float) -> float:
    lo, hi = distance_m / 600.0, distance_m / 40.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_performance(distance_m, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fmt_pace(min_per_km: float) -> str:
    total = int(round(min_per_km * 60))
    return f"{total // 60}:{total % 60:02d}"


def fmt_minutes(minutes: float) -> str:
    total = int(round(minutes * 60))
    h, rem = divmod(total, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


def _plausible(minutes: float, distance_key: str) -> bool:
    dist_km = RACE_DISTANCE_KM[distance_key]
    if distance_key in ULTRA_DISTANCES:
        return 3.0 <= minutes / dist_km <= 20.0
    if minutes <= 0:
        return False
    return 15.0 <= vdot_from_performance(dist_km * 1000.0, minutes) <= 90.0


def parse_target_minutes(text: Optional[str], distance_key: str) -> Optional[float]:
    """'3:45:00' -> 225.0. Two-part values are read as MM:SS or H:MM, whichever is plausible for the distance."""
    parts = str(text or "").strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    if len(nums) == 3:
        candidates = [nums[0] * 60 + nums[1] + nums[2] / 60.0]
    elif len(nums) == 2:
        candidates = [nums[0] + nums[1] / 60.0, nums[0] * 60 + nums[1]]
    else:
        return None
    return next((c for c in candidates if _plausible(c, distance_key)), None)


def profile_gaps(profile: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Required Goal Profile fields that are missing or unreadable: [{field, label, problem}].

    Injury history and current niggles are optional free text: blank means "none reported".
    """
    p = profile or {}
    gaps: List[Dict[str, str]] = []

    def gap(field, label, problem):
        gaps.append({"field": field, "label": label, "problem": problem})

    dist = (p.get("race_distance_type") or "").strip()
    if not dist:
        gap("race_distance_type", "Race distance", "not set")
    elif dist not in RACE_DISTANCE_KM:
        gap("race_distance_type", "Race distance", f"'{dist}' is not a supported distance "
            "(5K, 10K, Half Marathon, Marathon, 50K Ultra, 100K Ultra)")
    race = p.get("race_date")
    if not race:
        gap("race_date", "Race date", "not set")
    else:
        try:
            date.fromisoformat(str(race)[:10])
        except ValueError:
            gap("race_date", "Race date", f"'{race}' is not a valid date (YYYY-MM-DD)")
    target = (p.get("target_time_str") or "").strip()
    if not target:
        gap("target_time_str", "Target time", "not set")
    elif dist in RACE_DISTANCE_KM and parse_target_minutes(target, dist) is None:
        gap("target_time_str", "Target time", f"'{target}' cannot be read as a realistic {dist} time (use H:MM:SS)")
    hours = p.get("weekly_hours_available")
    try:
        hours_f = float(hours) if hours not in (None, "") else None
    except (TypeError, ValueError):
        hours_f = None
    if hours in (None, ""):
        gap("weekly_hours_available", "Weekly hours available", "not set")
    elif hours_f is None or not (1.0 <= hours_f <= 30.0):
        gap("weekly_hours_available", "Weekly hours available", f"'{hours}' must be a number of hours between 1 and 30")
    days_text = p.get("available_days")
    if not (days_text or "").strip():
        gap("available_days", "Available training days", "not set")
    else:
        days, bad = parse_available_days(days_text)
        if bad or not days:
            gap("available_days", "Available training days",
                f"could not read {', '.join(repr(b) for b in bad) or repr(days_text)} (use e.g. Mon,Wed,Sat)")
    return gaps


def _none_reported(text: Optional[str]) -> str:
    t = (text or "").strip()
    return "" if t.lower() in ("", "none", "n/a", "na", "no", "nil", "-") else t


def _fmt_date(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}"


class TrainingPlanner:
    """Core plan generator: 5 dated weeks (current Mon-Sun week + next 4), Road vs Ultra paths, adaptive loops."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------ public API
    def generate_plan(self, is_deload: bool = False, today: Optional[date] = None) -> Dict[str, Any]:
        """Generate a dated 5-week plan from the Goal Profile, training history, compliance and fatigue state.

        Raises ProfileIncompleteError when required profile fields are missing (no defaults are invented).
        """
        today = today or date.today()
        start = today - timedelta(days=today.weekday())            # Monday of the current week
        end = start + timedelta(days=7 * PLAN_WEEKS - 1)             # Sunday of week 5

        profile = get_user_profile(db_path=self.db_path)
        gaps = profile_gaps(profile)
        if gaps:
            raise ProfileIncompleteError(gaps)

        ctx = self._context(profile, start)
        compliance = calculate_weekly_compliance(db_path=self.db_path, today=today)
        compliance_pct = compliance.get("volume_compliance_pct", 100.0)
        overtraining = detect_overtraining_risk(db_path=self.db_path)
        low_compliance = 0.0 < compliance_pct < 70.0
        if low_compliance:
            ctx["growth"] = min(ctx["growth"], HELD_GROWTH)

        weeks, sessions = self._schedule(ctx, start, is_deload, overtraining, low_compliance)

        tvols = training_volumes(sessions)
        easy = easy_share_by_week(sessions)
        for w in weeks:
            n = w["week_number"]
            ws = [s for s in sessions if s["week_number"] == n]
            w["training_km"] = tvols.get(n, 0.0)
            w["volume_km"] = round(sum(s["distance_km"] for s in ws), 1)
            w["race_km"] = round(w["volume_km"] - w["training_km"], 1)
            w["easy_pct"] = easy.get(n, 100.0)
            w["hours"] = round(sum(s["duration_min"] for s in ws if s["session_type"] != "Race") / 60.0, 2)

        week1_deload = weeks[0]["kind"] == "deload"
        methodology = ("Training for the Uphill Athlete (House, Johnston & Jornet)" if ctx["is_ultra"]
                       else "Daniels' VDOT & Pfitzinger Periodisation")

        plan = {
            "id": f"plan_{uuid.uuid4().hex[:8]}",
            "version": 1,
            "goal_distance": ctx["distance"],
            "race_date": profile.get("race_date"),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_weeks": PLAN_WEEKS,
            "total_volume_km": weeks[0]["volume_km"],  # week 1 (current week) volume
            "prior_volume_km": ctx["baseline"],
            "methodology_name": methodology,
            "methodology_rationale": "",
            "is_deload": week1_deload,
            "week_summaries": [
                {"week_number": w["week_number"], "start_date": w["start"].isoformat(),
                 "end_date": (w["start"] + timedelta(days=6)).isoformat(), "kind": w["kind"], "phase": w["phase"],
                 "volume_km": w["volume_km"], "training_km": w["training_km"]}
                for w in weeks
            ],
            "sessions": sessions,
        }

        # Deterministic guardrails (ADR-002 + evidence rules) re-check the finished plan
        valid, violations = validate_evidence_rules(
            plan, ctx["baseline"], ctx["history_km"] if ctx["baseline_from_history"] else [],
            max_increase_pct=10.0, max_consecutive=ctx["max_consecutive"], long_run_max_min=ctx["lr_cap_min"])
        plan["methodology_rationale"] = self._rationale(ctx, weeks, start, end, overtraining, low_compliance,
                                                        compliance_pct, week1_deload)
        if not valid:
            plan["methodology_rationale"] += f" (Guardrail warning: {'; '.join(violations)})"
        plan["decisions"] = self._decisions(ctx, weeks, overtraining, low_compliance, compliance_pct,
                                            is_deload, violations)
        return plan

    # ------------------------------------------------------------------ context from the profile
    def _context(self, profile: Dict[str, Any], start: date) -> Dict[str, Any]:
        dist = profile["race_distance_type"].strip()
        is_ultra = dist in ULTRA_DISTANCES
        dist_km = RACE_DISTANCE_KM[dist]
        target_min = parse_target_minutes(profile["target_time_str"], dist)
        race = date.fromisoformat(str(profile["race_date"])[:10])
        race_passed = race < start
        hours = float(profile["weekly_hours_available"])
        days, _ = parse_available_days(profile["available_days"])
        injury = _none_reported(profile.get("injury_history"))
        niggles = _none_reported(profile.get("current_niggles"))
        max_consecutive = 3 if injury else 4

        history = get_run_history(start, weeks=4, db_path=self.db_path)
        max_hr = history["observed_max_hr"]
        paces = self._paces(dist, dist_km, target_min, is_ultra)
        ceiling_km = round(hours * 60.0 / paces["E_mid"], 1)
        history_km = history["weekly_km"]
        if history_km and sum(history_km) > 0:
            baseline = round(sum(history_km) / len(history_km), 1)
            baseline_from_history = True
        else:
            baseline = round(ceiling_km * NO_HISTORY_START_FRACTION, 1)
            baseline_from_history = False

        key = "ultra" if is_ultra else "road"
        taper_key = "Marathon" if is_ultra else dist
        return {
            "profile": profile, "distance": dist, "dist_km": dist_km, "is_ultra": is_ultra, "kind_key": key,
            "target_min": target_min, "target_str": profile["target_time_str"].strip(),
            "race": None if race_passed else race, "race_date": race, "race_passed": race_passed,
            "hours": hours, "ceiling_min": hours * 60.0, "ceiling_km": ceiling_km,
            "avail_days": days, "injury": injury, "niggles": niggles, "max_consecutive": max_consecutive,
            "layout": self._solve_layout(profile["available_days"], max_consecutive),
            "growth": CONSERVATIVE_GROWTH if (injury or niggles) else BUILD_GROWTH,
            "history": history, "history_km": history_km, "baseline": baseline,
            "baseline_from_history": baseline_from_history, "max_hr": max_hr, "paces": paces,
            "taper_len": TAPER_WEEKS[taper_key], "recovery": RECOVERY[taper_key],
            "lr_share": LONG_RUN_SHARE[key], "lr_cap_min": LONG_RUN_MAX_MIN[key],
        }

    @staticmethod
    def _paces(dist: str, dist_km: float, target_min: float, is_ultra: bool) -> Dict[str, Any]:
        race_pace = target_min / dist_km
        if is_ultra:
            e = (race_pace * 1.05, race_pace * 1.20)
            return {"vdot": None, "race": race_pace, "E": e, "E_mid": sum(e) / 2,
                    "L": (race_pace * 1.00, race_pace * 1.10), "V": race_pace * 1.25}
        vdot = vdot_from_performance(dist_km * 1000.0, target_min)
        e = (_pace_for_fraction(vdot, 0.70), _pace_for_fraction(vdot, 0.62))    # (fast, slow)
        return {"vdot": round(vdot, 1), "race": race_pace, "E": e, "E_mid": sum(e) / 2, "L": e,
                "M": predict_race_minutes(vdot, 42195.0) / 42.195,
                "T": _pace_for_fraction(vdot, 0.88), "I": _pace_for_fraction(vdot, 0.975)}

    # ------------------------------------------------------------------ periodisation
    def _phase(self, ctx: Dict[str, Any], wstart: date) -> Tuple[str, Optional[int]]:
        """(phase, race weekday offset if race week)."""
        race = ctx["race"]
        if race is None:
            return "base", None
        days_to = (race - wstart).days
        if days_to < 0:
            weeks_since = (-days_to - 1) // 7 + 1
            return ("recovery" if weeks_since <= ctx["recovery"][1] else "base"), None
        if days_to <= 6:
            return "race", days_to
        wtr = days_to // 7
        if wtr <= ctx["taper_len"]:
            return "taper", None
        if wtr <= ctx["taper_len"] + PEAK_PHASE_WEEKS:
            return "peak", None
        if wtr <= BUILD_PHASE_START:
            return "build", None
        return "base", None

    def _schedule(self, ctx, start, is_deload, overtraining, low_compliance):
        weeks: List[Dict[str, Any]] = []
        sessions: List[Dict[str, Any]] = []
        baseline = ctx["baseline"]
        prev, peak, streak = baseline, baseline, 0
        rolling = list(ctx["history_km"]) if ctx["baseline_from_history"] else []
        first_recovery = True
        for n in range(1, PLAN_WEEKS + 1):
            wstart = start + timedelta(days=7 * (n - 1))
            phase, race_offset = self._phase(ctx, wstart)
            next_phase, _ = self._phase(ctx, wstart + timedelta(days=7))
            notes: List[str] = []
            tl = ctx["taper_len"]
            if phase == "race":
                target, kind = peak * RACE_WEEK_FACTOR[tl], "race"
                notes.append(f"race week: training {RACE_WEEK_FACTOR[tl]:.0%} of peak {peak:.1f} km")
            elif phase == "taper":
                wtr = (ctx["race"] - wstart).days // 7
                factor = TAPER_FACTORS[tl][tl - wtr]
                target, kind = peak * factor, "taper"
                notes.append(f"taper: {factor:.0%} of peak {peak:.1f} km")
            elif phase == "recovery":
                if first_recovery:
                    target = peak * ctx["recovery"][0]
                    notes.append(f"post-race: {ctx['recovery'][0]:.0%} of peak, easy only")
                    first_recovery = False
                else:
                    target = prev * ctx["growth"]
                kind = "recovery"
            elif n == 1:
                if overtraining.get("is_flagged"):
                    adj = overtraining.get("recommended_adjustment_pct", -20.0)
                    target, kind = baseline * (1.0 + adj / 100.0), "deload"
                    notes.append(f"fatigue flag: {adj:+.0f}% vs baseline")
                elif is_deload:
                    target, kind = baseline * FORCED_DELOAD_FACTOR, "deload"
                    notes.append("requested deload: -25% vs baseline")
                elif ctx["niggles"]:
                    target, kind = baseline, "build"
                    notes.append("held at baseline while niggles are active")
                elif low_compliance:
                    target, kind = baseline, "build"
                    notes.append("held at baseline (compliance < 70%)")
                else:
                    target, kind = baseline * ctx["growth"], "build"
                    notes.append(f"baseline +{ctx['growth'] - 1:.0%}")
            elif streak >= BUILDS_BEFORE_DELOAD and next_phase not in ("taper", "race"):
                target, kind = prev * DELOAD_FACTOR, "deload"
                notes.append(f"3:1 deload: -{1 - DELOAD_FACTOR:.0%}")
            else:
                target, kind = prev * ctx["growth"], "build"
                notes.append(f"+{ctx['growth'] - 1:.0%}")

            if prev > 0 and target > prev * MAX_WEEKLY_INCREASE:
                target = prev * MAX_WEEKLY_INCREASE
                notes.append("capped by 10% rule")
            chronic = rolling[-4:]
            if chronic and sum(chronic) > 0 and target > ACWR_MAX * sum(chronic) / len(chronic):
                target = ACWR_MAX * sum(chronic) / len(chronic)
                notes.append("capped by ACWR 1.3")

            wk = {"week_number": n, "start": wstart, "phase": phase, "kind": kind, "race_offset": race_offset,
                  "target_km": round(target, 1), "peak": peak}
            week_sessions, actual, flags = self._build_week(ctx, wk, round(target, 1))
            caps = [prev * MAX_WEEKLY_INCREASE] if prev > 0 else []
            if chronic and sum(chronic) > 0:
                caps.append(ACWR_MAX * sum(chronic) / len(chronic))
            limit = min(caps) if caps else None
            for _ in range(5):   # per-session rounding can overshoot the cap by a few 100 m
                if limit is None or actual <= limit:
                    break
                target -= (actual - limit) + 0.1
                week_sessions, actual, flags = self._build_week(ctx, wk, round(target, 1))
            if flags.get("hours_capped"):
                notes.append(f"capped by {ctx['hours']:g} h/week available")
            if flags.get("lr_capped"):
                notes.append(f"long run capped at {ctx['lr_cap_min']:.0f} min")
            wk.update(notes=notes, hours_capped=bool(flags.get("hours_capped")), lr_capped=bool(flags.get("lr_capped")))
            weeks.append(wk)
            sessions.extend(week_sessions)
            rolling.append(actual)
            prev = actual
            if kind == "build" and phase in ("base", "build", "peak"):
                peak = actual
            streak = streak + 1 if kind == "build" and phase != "recovery" else 0
        return weeks, sessions

    # ------------------------------------------------------------------ weekly layout
    @staticmethod
    def _parse_days(available_days: Optional[str]) -> List[int]:
        return parse_available_days(available_days)[0]

    @staticmethod
    def _solve_layout(available_days: Optional[str], max_consecutive: int = 4) -> Dict[str, Any]:
        """Pick run days + roles (long run, quality, easy) among available days, deterministically.

        Constraints (cyclic, since the weekly pattern repeats): long run and quality day not adjacent,
        at most `max_consecutive` consecutive run days. Preferences: long run Sat > Sun, quality Tue > Thu > Wed,
        few adjacent runs. Up to 5 run days.
        """
        avail = TrainingPlanner._parse_days(available_days)
        if not avail:
            return {"run_days": [], "long_run_day": None, "quality_day": None, "k": 0}
        q_pref = {1: 0, 3: 1, 2: 2, 0: 3, 4: 4, 5: 5, 6: 6}
        lr_pref = {5: 0, 6: 1}
        for k in range(min(len(avail), 5), 0, -1):
            has_q = k >= 3
            best = None
            for combo in combinations(avail, k):
                run = set(combo)
                if any(all(((d + i) % 7) in run for i in range(max_consecutive + 1)) for d in range(7)):
                    continue  # would exceed the consecutive-day limit
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

    def _quality_type(self, ctx: Dict[str, Any], phase: str) -> Optional[str]:
        if ctx["niggles"] or phase == "recovery" or ctx["layout"]["quality_day"] is None:
            return None
        if ctx["is_ultra"]:
            return "Vert/Time-on-Feet"
        dist = ctx["distance"]
        if phase == "base":
            return "Threshold"
        if dist in ("5K", "10K"):
            return "VO2max"
        if dist == "Marathon" and phase in ("peak", "taper", "race"):
            return "Marathon Pace"
        return "Threshold"

    def _allocate(self, ctx: Dict[str, Any], wk: Dict[str, Any], vol: float) -> Tuple[Dict[int, Tuple[str, float]], bool]:
        """offset -> (role, km). Roles: long, quality, easy, recovery, b2b, niggle_easy, race."""
        layout = ctx["layout"]
        run_days, lr_day, q_day, k = layout["run_days"], layout["long_run_day"], layout["quality_day"], layout["k"]
        phase = wk["phase"]
        q_type = self._quality_type(ctx, phase)
        roles: Dict[int, Tuple[str, float]] = {}
        lr_capped = False

        if wk["race_offset"] is not None:
            ro = wk["race_offset"]
            pre = [d for d in run_days if d < ro - 1]
            q_ok = q_type is not None and q_day in pre and q_day <= ro - 3
            q_km = vol * QUALITY_SHARE["race"] if q_ok else 0.0
            easy_days = [d for d in pre if not (q_ok and d == q_day)]
            if q_ok and not easy_days:
                q_ok, q_km, easy_days = False, 0.0, pre
            if q_ok:
                roles[q_day] = ("quality", q_km)
            for d in easy_days:
                roles[d] = ("easy", (vol - q_km) / len(easy_days))
            roles[ro] = ("race", ctx["dist_km"])
            # short races: easy recovery runs from 2 days after the race; marathon/ultra: rest for the rest of the week
            post = [d for d in run_days if d > ro + 1] if ctx["recovery"][1] == 1 else []
            for d in post:
                roles[d] = ("post_race", wk.get("peak", vol) * ctx["recovery"][0] / max(len(run_days), 1))
            return roles, False

        # the day before and after the race are rest days, also across a week boundary
        race = ctx["race"]
        blocked = {o for o in range(7) if race is not None and abs((wk["start"] + timedelta(days=o) - race).days) == 1}
        run_days = [d for d in run_days if d not in blocked]
        if not run_days:
            return roles, False

        if phase == "recovery":
            for d in run_days:
                roles[d] = ("easy", vol / len(run_days))
            return roles, False

        lr_km = 0.0
        if lr_day in run_days:
            lr_km = vol * ctx["lr_share"][k]
            lr_mid = sum(ctx["paces"]["L"]) / 2
            if lr_km * lr_mid > ctx["lr_cap_min"]:
                lr_km, lr_capped = ctx["lr_cap_min"] / lr_mid, True
            roles[lr_day] = ("long", lr_km)
        has_q = bool(q_type) and q_day in run_days
        q_km = vol * QUALITY_SHARE[phase] if has_q else 0.0
        after_lr = (lr_day + 1) % 7 if lr_day in run_days else None
        easy_days = [d for d in run_days if d != lr_day and not (has_q and d == q_day)]
        weights = {d: ((1.6 if ctx["is_ultra"] else 0.8) if d == after_lr else 1.0) for d in easy_days}
        wsum = sum(weights.values()) or 1.0
        easy_total = max(0.0, vol - lr_km - q_km) if easy_days else 0.0
        if has_q:
            # keep >= 80% easy even when easy km are lost (few run days / long-run cap): q <= 0.19 of the week
            q_km = min(q_km, 0.19 / 0.81 * (lr_km + easy_total))
            roles[q_day] = ("quality", q_km)
        for d in easy_days:
            role = "niggle_easy" if (d == q_day and ctx["niggles"]) else (
                ("b2b" if ctx["is_ultra"] else "recovery") if d == after_lr else "easy")
            roles[d] = (role, easy_total * weights[d] / wsum)
        return roles, lr_capped

    def _build_week(self, ctx: Dict[str, Any], wk: Dict[str, Any], target: float):
        """Build the 7 sessions of a week at `target` training km, scaled down to fit the weekly hours."""
        vol, flags = target, {}
        for _ in range(4):
            roles, lr_capped = self._allocate(ctx, wk, vol)
            sessions = self._sessions_for(ctx, wk, roles)
            minutes = sum(s["duration_min"] for s in sessions if s["session_type"] != "Race")
            if minutes <= ctx["ceiling_min"] + 0.5:
                break
            flags["hours_capped"] = True
            vol = vol * ctx["ceiling_min"] / minutes * 0.995
        flags["lr_capped"] = lr_capped
        actual = round(sum(s["distance_km"] for s in sessions if s["session_type"] != "Race"), 1)
        return sessions, actual, flags

    def _sessions_for(self, ctx, wk, roles) -> List[Dict[str, Any]]:
        lr_day = ctx["layout"]["long_run_day"]
        q_type = self._quality_type(ctx, wk["phase"])
        suffix = {"deload": " (Deload week: reduced volume.)",
                  "taper": " (Taper: volume reduced, intensity kept - Bosquet 2007.)",
                  "recovery": " (Post-race recovery: easy running only.)"}.get(wk["kind"], "")
        ro = wk["race_offset"]
        sessions = []
        for offset in range(7):
            d = wk["start"] + timedelta(days=offset)
            role, km = roles.get(offset, ("rest", 0.0))
            km = round(km, 1)
            if role != "rest" and role != "race" and km < 0.1:
                role = "rest"
            if role == "race":
                s = self._race(ctx)
            elif role == "long":
                s = self._long_run(ctx, km)
            elif role == "quality":
                s = self._quality(ctx, q_type, km)
            elif role in ("easy", "recovery", "b2b", "niggle_easy", "post_race"):
                s = self._easy(ctx, km, role, offset)
            elif ro is not None and offset == ro - 1:
                s = self._rest("Rest before race day (taper).", "Rest & Mobility")
            elif ro is not None and offset > ro:
                s = self._rest("Post-race recovery: rest.", "Rest & Recovery")
            elif lr_day is not None and (offset + 1) % 7 == lr_day:
                s = self._rest("Rest day to prepare legs for the long run.",
                               "Rest & S&C" if ctx["is_ultra"] else "Rest & Mobility")
            else:
                s = self._rest("Rest day for muscular repair and central nervous system recovery.",
                               "Rest & Mobility" if ctx["is_ultra"] else "Rest & Recovery")
            s["week_number"] = wk["week_number"]
            s["session_date"] = d.isoformat()
            s["day_of_week"] = WEEKDAYS[offset]
            if suffix and s["session_type"] not in ("Rest", "Race"):
                s["stated_purpose"] += suffix
            sessions.append(s)
        return sessions

    # ------------------------------------------------------------------ session builders
    def _hr(self, ctx, zone: str) -> Optional[str]:
        mx = ctx["max_hr"]
        if not mx:
            return None
        lo, hi = HR_ZONES[zone]
        return f"{round(mx * lo)} – {round(mx * hi)} bpm"

    @staticmethod
    def _rest(purpose: str, target: str) -> Dict[str, Any]:
        return {"session_type": "Rest", "distance_km": 0.0, "duration_min": 0.0,
                "target_pace_or_hr": target, "stated_purpose": purpose}

    def _race(self, ctx) -> Dict[str, Any]:
        p = ctx["paces"]["race"]
        return {"session_type": "Race", "distance_km": round(ctx["dist_km"], 1), "duration_min": round(ctx["target_min"], 0),
                "target_pace_or_hr": f"Pace Focus: {fmt_pace(p)} /km (Goal race pace for {ctx['target_str']})",
                "stated_purpose": f"GOAL RACE: {ctx['distance']} - target {ctx['target_str']}. Start controlled, "
                                  "even pacing, fuel as rehearsed."}

    def _long_run(self, ctx, km: float) -> Dict[str, Any]:
        lo, hi = ctx["paces"]["L"]
        dur = round(km * (lo + hi) / 2, 0)
        if ctx["is_ultra"]:
            hr = self._hr(ctx, "E")
            return {"session_type": "Long Run", "distance_km": km, "duration_min": dur,
                    "target_pace_or_hr": f"Pace Focus: {fmt_pace(lo)} – {fmt_pace(hi)} /km (Zone 2 time-on-feet at goal "
                                         f"race effort{', ' + hr if hr else ''})",
                    "stated_purpose": "Uphill Athlete time-on-feet long run at goal race effort on race-like terrain; "
                                      "practise fuelling and pacing."}
        hr = self._hr(ctx, "E")
        return {"session_type": "Long Run", "distance_km": km, "duration_min": dur,
                "target_pace_or_hr": f"Pace Focus: {fmt_pace(lo)} – {fmt_pace(hi)} /km (Zone 2 Long Run at Daniels E pace"
                                     f"{', ' + hr if hr else ''})",
                "stated_purpose": f"Long run at E pace (<= {ctx['lr_cap_min']:.0f} min, Daniels; Pfitzinger endurance): "
                                  "aerobic endurance, glycogen storage and fat-oxidation adaptation."}

    def _quality(self, ctx, q_type: str, km: float) -> Dict[str, Any]:
        p = ctx["paces"]
        e_mid = p["E_mid"]
        if q_type == "Vert/Time-on-Feet":
            hr = self._hr(ctx, "V")
            target = (f"Heart Rate Focus: {hr} (Zone 3 uphill effort, about {fmt_pace(p['V'])} /km incl. climbs)" if hr
                      else f"Pace Focus: {fmt_pace(p['V'])} /km average incl. climbs (Zone 3 uphill effort, RPE 6-7/10)")
            return {"session_type": q_type, "distance_km": km, "duration_min": round(km * p["V"], 0),
                    "target_pace_or_hr": target,
                    "stated_purpose": "Uphill Athlete muscular-endurance session: sustained climbing or hill repeats at "
                                      "Zone 3 effort to build climbing strength for the ultra."}
        if q_type == "VO2max":
            fast = km * 0.4
            reps = max(3, min(8, int(round(fast))))
            hr = self._hr(ctx, "I")
            return {"session_type": q_type, "distance_km": km, "duration_min": round(fast * p["I"] + (km - fast) * e_mid, 0),
                    "target_pace_or_hr": f"Pace Focus: {fmt_pace(p['I'] - 0.05)} – {fmt_pace(p['I'] + 0.05)} /km "
                                         f"(Zone 5 Daniels I pace{', ' + hr if hr else ''})",
                    "stated_purpose": f"Daniels I session: warm-up, {reps} x 1000 m at I pace with equal-time jog "
                                      "recoveries (I-pace volume <= 8% of weekly km), cool-down. Develops VO2max."}
        if q_type == "Marathon Pace":
            fast = km * 0.7
            hr = self._hr(ctx, "M")
            return {"session_type": q_type, "distance_km": km, "duration_min": round(fast * p["M"] + (km - fast) * e_mid, 0),
                    "target_pace_or_hr": f"Pace Focus: {fmt_pace(p['M'] - 0.05)} – {fmt_pace(p['M'] + 0.05)} /km "
                                         f"(Zone 3 goal marathon pace{', ' + hr if hr else ''})",
                    "stated_purpose": f"Pfitzinger marathon-pace run: about {fast:.0f} km at goal M pace inside the run. "
                                      "Rehearses race pace, fuelling and kit."}
        fast = km * 0.5
        hr = self._hr(ctx, "T")
        return {"session_type": "Threshold", "distance_km": km, "duration_min": round(fast * p["T"] + (km - fast) * e_mid, 0),
                "target_pace_or_hr": f"Pace Focus: {fmt_pace(p['T'] - 0.05)} – {fmt_pace(p['T'] + 0.05)} /km "
                                     f"(Zone 4 Daniels T pace / LT{', ' + hr if hr else ''})",
                "stated_purpose": f"Daniels/Pfitzinger threshold session: warm-up, about {fast:.0f} km at T pace as "
                                  "cruise intervals (1 min jog rests), cool-down. Raises lactate threshold."}

    def _easy(self, ctx, km: float, role: str, offset: int) -> Dict[str, Any]:
        fast, slow = ctx["paces"]["E"]
        if role == "recovery":
            fast, slow = slow, slow + 0.25
            hr = self._hr(ctx, "R")
            zone, purpose = "Zone 1 Recovery", "Recovery run the day after the long run: very easy, short."
        elif role == "b2b":
            hr = self._hr(ctx, "E")
            zone, purpose = "Zone 1-2 Back-to-Back Ultra", ("Back-to-back ultra simulation: easy running on "
                                                             "pre-fatigued legs (Uphill Athlete).")
        elif role == "post_race":
            fast, slow = slow, slow + 0.25
            hr = self._hr(ctx, "R")
            zone, purpose = "Zone 1 Recovery", "Post-race recovery run: very easy and short (Pfitzinger)."
        elif role == "niggle_easy":
            hr = self._hr(ctx, "E")
            zone, purpose = "Zone 2 Easy", (f"Easy aerobic run replacing the quality session while niggle(s) are active "
                                            f"({ctx['niggles']}).")
        else:
            hr = self._hr(ctx, "E")
            zone = "Zone 2 Easy"
            purpose = ("Aerobic base run at easy intensity (about 80% of training is easy - Seiler)."
                       if offset % 2 == 0 else "Easy aerobic run building capillary and mitochondrial density.")
        dur = round(km * (fast + slow) / 2, 0)
        pace = f"{fmt_pace(fast)} – {fmt_pace(slow)} /km"
        target = (f"Heart Rate Focus: {hr} ({zone}, {pace})" if hr else f"Pace Focus: {pace} ({zone}, conversational)")
        return {"session_type": "Easy Aerobic", "distance_km": km, "duration_min": dur,
                "target_pace_or_hr": target, "stated_purpose": purpose}

    # ------------------------------------------------------------------ explanation
    def _rationale(self, ctx, weeks, start, end, overtraining, low_compliance, compliance_pct, week1_deload) -> str:
        if ctx["is_ultra"]:
            text = (f"Ultra/Trail time-on-feet methodology for {ctx['distance']} (target {ctx['target_str']}). "
                    "Focus on vertical elevation gain, continuous aerobic endurance, and fatigue management.")
        elif week1_deload:
            text = "Deload recovery week: reduced volume for supercompensation."
        else:
            text = (f"Daniels VDOT {ctx['paces']['vdot']} paces targeting {ctx['target_str']} at {ctx['distance']}; "
                    "at least 80% easy volume with one quality session per week.")
        pattern = ", ".join(f"W{w['week_number']} {w['kind']} {w['volume_km']:.1f}km" for w in weeks)
        text += f" 5-week dated plan ({start.isoformat()} to {end.isoformat()}), 3:1 loading: {pattern}."
        if ctx["niggles"]:
            text += f" Quality intensity replaced by easy running while niggle(s) active ({ctx['niggles']})."
        if overtraining.get("is_flagged"):
            reasons = "; ".join(overtraining.get("reasons", []))
            text += (f" ⚠️ [ADAPTATION ALERT: Fatigue detected ({reasons}). Volume reduced by "
                     f"{abs(overtraining.get('recommended_adjustment_pct', -20.0)):.0f}%].")
        elif low_compliance:
            text += (f" ℹ️ [ADAPTATION: Prior week compliance was {compliance_pct:.1f}% (< 70%). "
                     "Volume held steady for adaptation].")
        return text

    def _decisions(self, ctx, weeks, overtraining, low_compliance, compliance_pct, is_deload, violations) -> Dict[str, Any]:
        p, prof = ctx["paces"], ctx["profile"]
        items: List[Dict[str, Any]] = []

        def add(topic, summary, inputs, sources):
            items.append({"topic": topic, "summary": summary, "inputs": inputs, "sources": sources})

        dist_in = f"Race distance: {ctx['distance']}"
        date_in = f"Race date: {ctx['race_date'].isoformat()}"
        target_in = f"Target time: {ctx['target_str']}"
        hours_in = f"Weekly hours available: {ctx['hours']:g} h"
        days_in = f"Available days: {prof.get('available_days')}"
        method_src = ["uphill"] if ctx["is_ultra"] else ["daniels", "pfitzinger"]
        start = weeks[0]["start"]
        plan_end = start + timedelta(days=7 * PLAN_WEEKS - 1)

        # 1. Goal, methodology and phases (race distance + race date)
        if ctx["race_passed"]:
            add("Goal race & phases",
                f"Race date {_fmt_date(ctx['race_date'])} has already passed, so no taper or race is scheduled: all "
                "weeks are general base training. Update your Goal Profile with your next race.",
                [dist_in, date_in], method_src)
        else:
            weeks_out = (ctx["race"] - start).days // 7
            phases = ", ".join(f"W{w['week_number']} {w['phase'].title()}" for w in weeks)
            where = ("inside this plan" if ctx["race"] <= plan_end
                     else f"{(ctx['race'] - plan_end).days // 7 + 1} week(s) after this plan ends")
            add("Goal race & phases",
                f"{ctx['distance']} on {_fmt_date(ctx['race'])} ({weeks_out} weeks from the plan start, {where}) -> "
                f"{'Uphill Athlete ultra' if ctx['is_ultra'] else 'Daniels/Pfitzinger road'} periodisation: {phases}. "
                f"Build phase starts {BUILD_PHASE_START} weeks out, race-specific peak {PEAK_PHASE_WEEKS} weeks before "
                f"a {ctx['taper_len']}-week taper plus race week.",
                [dist_in, date_in], method_src + ["bompa"])

        # 2. Paces from target time
        if ctx["is_ultra"]:
            add("Training paces",
                f"Target {ctx['target_str']} for {ctx['distance']} = {fmt_pace(p['race'])} /km average. Long runs at "
                f"{fmt_pace(p['L'][0])} – {fmt_pace(p['L'][1])} /km (goal race effort), easy runs "
                f"{fmt_pace(p['E'][0])} – {fmt_pace(p['E'][1])} /km. Ultra races are run at aerobic intensity, so "
                "training stays mostly easy with vertical muscular-endurance work.",
                [target_in, dist_in], ["uphill"])
        else:
            add("Training paces",
                f"Target {ctx['target_str']} for {ctx['distance']} -> VDOT {p['vdot']} -> E {fmt_pace(p['E'][0])} – "
                f"{fmt_pace(p['E'][1])}, M {fmt_pace(p['M'])}, T {fmt_pace(p['T'])}, I {fmt_pace(p['I'])} /km. "
                "Daniels advises training at current-fitness VDOT: if T/I paces feel unsustainable, your current "
                "fitness is below the goal and the target time should be reviewed.",
                [target_in, dist_in], ["daniels_gilbert", "daniels"])
        if ctx["max_hr"]:
            add("Heart-rate zones",
                f"Observed max HR {ctx['max_hr']} bpm (highest in your COROS runs, last 365 days) -> easy "
                f"{self._hr(ctx, 'E')}, threshold {self._hr(ctx, 'T')}. Observed max may understate true max.",
                ["COROS activity max HR"], ["daniels"])
        else:
            add("Heart-rate zones",
                "No max HR found in your COROS runs, so targets are pace-only: no heart-rate zones are invented.",
                ["COROS activity max HR: not available"], ["daniels"])

        # 3. Starting volume & weekly hours ceiling
        w1 = weeks[0]
        hist = ", ".join(f"{w['km']:.0f}" for w in ctx["history"]["weeks"])
        if ctx["baseline_from_history"]:
            base_txt = (f"prior {len(ctx['history_km'])}-week average {ctx['baseline']:.1f} km (weeks: {hist} km)")
            base_src = ["adr002", "gabbett"]
        else:
            base_txt = (f"no runs in your COROS history for the last 4 weeks, so the start is "
                        f"{NO_HISTORY_START_FRACTION:.0%} of the {ctx['ceiling_km']:.0f} km weekly-hours ceiling "
                        f"({ctx['baseline']:.1f} km)")
            base_src = ["app", "adr002"]
        add("Week 1 volume",
            f"Week 1 training volume {w1['training_km']:.1f} km: {base_txt}; {'; '.join(w1['notes'])}.",
            ["COROS run history", hours_in], base_src)
        capped = [f"W{w['week_number']}" for w in weeks if w["hours_capped"]]
        longest = max(weeks, key=lambda w: w["hours"])
        add("Weekly hours ceiling",
            f"{ctx['hours']:g} h/week available is about {ctx['ceiling_km']:.0f} km at your easy pace. "
            + (f"Volume was reduced to fit in {', '.join(capped)}." if capped else
               f"Not binding: the longest week (W{longest['week_number']}) is {longest['hours']:.1f} h."),
            [hours_in, target_in], ["app"])

        # 4. Progression, deloads, injury history
        deloads = [f"W{w['week_number']}" for w in weeks if w["kind"] == "deload"]
        growth_pct = round((ctx["growth"] - 1) * 100)
        add("Progression & recovery weeks",
            f"Loading weeks grow +{growth_pct}%/week (never above +10% week-over-week, acute:chronic ratio <= 1.3); "
            f"3:1 step loading with a -{1 - DELOAD_FACTOR:.0%} deload"
            + (f" in {', '.join(deloads)}." if deloads else " (none due inside this window: taper/race weeks unload).")
            + " Weekly: " + "; ".join(f"W{w['week_number']} {w['training_km']:.1f} km ({', '.join(w['notes'])})"
                                      for w in weeks) + ".",
            ["COROS run history"] + (["Injury history", "Current niggles"] if ctx["growth"] < BUILD_GROWTH else []),
            ["adr002", "bompa", "gabbett"])
        if ctx["injury"]:
            add("Injury history",
                f"'{ctx['injury']}' -> conservative plan: +{round((CONSERVATIVE_GROWTH - 1) * 100)}%/week instead of "
                f"+{round((BUILD_GROWTH - 1) * 100)}%, and at most 3 consecutive run days instead of 4.",
                [f"Injury history: {ctx['injury']}"], ["van_gent", "app"])
        else:
            add("Injury history", "None reported -> standard progression and up to 4 consecutive run days.",
                ["Injury history: none reported"], ["adr002"])
        if ctx["niggles"]:
            add("Current niggles",
                f"'{ctx['niggles']}' -> every quality session is replaced with easy running, week 1 is held at the "
                "baseline and growth is limited while symptoms persist. Update the profile when it has settled.",
                [f"Current niggles: {ctx['niggles']}"], ["app"])
        else:
            add("Current niggles", "None reported -> quality sessions scheduled.", ["Current niggles: none reported"], ["app"])

        # 5. Run days
        lay = ctx["layout"]
        names = lambda ds: ", ".join(WEEKDAYS[d] for d in sorted(ds)) or "none"
        rest = [d for d in range(7) if d not in lay["run_days"]]
        unused = [d for d in ctx["avail_days"] if d not in lay["run_days"]]
        add("Run days",
            f"Available {names(ctx['avail_days'])} -> runs on {names(lay['run_days'])}; long run "
            f"{WEEKDAYS[lay['long_run_day']]}"
            + (f", quality {WEEKDAYS[lay['quality_day']]}" if lay["quality_day"] is not None else
               " (fewer than 3 run days: no separate quality day)")
            + f"; rest {names(rest)}. Long run and quality are never on adjacent days; at most "
            f"{ctx['max_consecutive']} run days in a row"
            + (f"; {names(unused)} left as rest to respect that." if unused else "."),
            [days_in] + ([f"Injury history: {ctx['injury']}"] if ctx["injury"] else []), ["adr002"])

        # 6. Intensity distribution & long run
        add("Intensity distribution",
            "Easy share of training km: " + ", ".join(f"W{w['week_number']} {w['easy_pct']:.0f}%" for w in weeks)
            + " (>= 80% enforced in code; one quality session per week).",
            [dist_in, "Current niggles"], ["seiler", "stoggl", "adr002"])
        lr_capped = [f"W{w['week_number']}" for w in weeks if w["lr_capped"]]
        k = lay["k"]
        add("Long run",
            f"Long run = {ctx['lr_share'][k]:.0%} of weekly training km with {k} run days, capped at "
            f"{ctx['lr_cap_min']:.0f} min" + (f" (cap applied in {', '.join(lr_capped)})." if lr_capped else ".")
            + (" Daniels suggests <= 25-30% of weekly volume; with few run days the share is necessarily higher."
               if not ctx["is_ultra"] and ctx["lr_share"][k] > 0.30 else ""),
            [days_in, hours_in, dist_in], (["uphill", "app"] if ctx["is_ultra"] else ["daniels"]))

        # 7. Taper / race / recovery
        if not ctx["race_passed"] and any(w["phase"] in ("taper", "race", "recovery") for w in weeks):
            tl = ctx["taper_len"]
            add("Taper & race",
                f"{tl}-week progressive taper ({', '.join(f'{f:.0%}' for f in TAPER_FACTORS[tl])} of peak) then race "
                f"week at {RACE_WEEK_FACTOR[tl]:.0%} of peak training km with the race on "
                f"{_fmt_date(ctx['race'])}; intensity is kept, rest the day before and after. Post-race: easy running "
                f"only for {ctx['recovery'][1]} week(s), starting at {ctx['recovery'][0]:.0%} of peak.",
                [date_in, dist_in, target_in], ["bosquet", "mujika", "pfitzinger"])

        # 8. Adaptation
        if overtraining.get("is_flagged"):
            add("Fatigue adaptation",
                f"Fatigue flag ({'; '.join(overtraining.get('reasons', []))}) -> week 1 reduced by "
                f"{abs(overtraining.get('recommended_adjustment_pct', -20.0)):.0f}%.",
                ["COROS HRV / sleep / training load"], ["gabbett"])
        elif low_compliance:
            add("Compliance adaptation",
                f"Last plan's volume compliance was {compliance_pct:.1f}% (< 70%) -> week 1 held at baseline and "
                "conservative growth.", ["Plan compliance"], ["app"])
        elif is_deload and weeks[0]["kind"] == "deload":
            add("Requested deload", "You asked for a deload: week 1 at 75% of baseline, then the 3:1 cycle restarts.",
                ["Generate Deload Week"], ["bompa"])

        add("Guardrail check",
            "All deterministic guardrails passed (10% rule, ACWR <= 1.3, 80/20, no back-to-back hard days, "
            f"max {ctx['max_consecutive']} consecutive run days, recovery-week frequency, long-run cap)."
            if not violations else "Guardrail warnings: " + "; ".join(violations),
            ["Whole plan"], ["adr002", "gabbett"])

        used = []
        for it in items:
            for key in it["sources"]:
                if key not in used:
                    used.append(key)
        return {
            "version": 1,
            "items": items,
            "sources": [{"key": k, **SOURCES[k]} for k in used],
            "weeks": [{"week_number": w["week_number"], "start_date": w["start"].isoformat(), "phase": w["phase"],
                       "kind": w["kind"], "training_km": w["training_km"], "race_km": w["race_km"],
                       "volume_km": w["volume_km"], "easy_pct": w["easy_pct"], "hours": w["hours"],
                       "notes": w["notes"]} for w in weeks],
            "profile": {k: prof.get(k) for k in ("race_distance_type", "race_date", "target_time_str",
                                                 "weekly_hours_available", "available_days", "injury_history",
                                                 "current_niggles")},
            "baseline_km": ctx["baseline"],
        }
