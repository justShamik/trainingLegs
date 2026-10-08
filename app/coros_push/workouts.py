"""Turn a plan session into a COROS structured running workout (createScheduledWorkout `course`).

Course rules come from the COROS MCP tool catalog (see docs/COROS_PUSH_FEASIBILITY.md): sportType 1 = running;
sectionType 1 warm-up / 2 training / 3 recovery / 4 cool-down; targetType 1 distance (m) / 2 time (s);
intensityType 1 = heart rate, 2 = pace; one intensity format per section; interval groups hold 1-20 repeats
of training/recovery members. Warm-ups, recoveries and cool-downs use the watch's own HR zones
(sectionIntensity), so they follow whatever zones are set in COROS.
"""
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

RUN = 1
WARMUP, TRAIN, RECOVER, COOLDOWN = 1, 2, 3, 4
DIST, TIME = 1, 2
HR, PACE = 1, 2

NOT_PUSHABLE = {"Rest": "Rest day: nothing to put on the watch.",
                "Cross-Training": "Cross-training isn't a running workout, so COROS can't take it as a structured run.",
                "S&C": "Strength sessions can't be created as COROS structured workouts."}


def _s(mmss: str) -> int:
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def parse_target(text: Optional[str]) -> Dict[str, Any]:
    """HR range (bpm), pace range (s/km, fast first) and focus from a target string such as
    'Pace Focus: 4:37 – 4:43 /km (Zone 4 Daniels T pace / LT, 160 – 171 bpm)'."""
    text = text or ""
    hr = re.search(r"(\d{2,3})\s*[–-]\s*(\d{2,3})\s*bpm", text)
    pace = re.search(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})\s*/\s*km", text)
    single = re.search(r"(\d{1,2}:\d{2})\s*/\s*km", text)
    out: Dict[str, Any] = {"focus": "hr" if text.startswith("Heart Rate Focus") else "pace" if text.startswith("Pace Focus") else None,
                           "hr": None, "pace": None}
    if hr:
        lo, hi = sorted((int(hr.group(1)), int(hr.group(2))))
        if 30 <= lo and hi <= 240:
            out["hr"] = (lo, hi)
    if pace:
        a, b = sorted((_s(pace.group(1)), _s(pace.group(2))))
        out["pace"] = (a, b)
    elif single:
        v = _s(single.group(1))
        out["pace"] = (v, v)
    if out["pace"] and not (120 <= out["pace"][0] and out["pace"][1] <= 1499):
        out["pace"] = None
    return out


def _section(kind: int, target_type: int, value: float, intensity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sec = {"sectionType": kind, "targetType": target_type, "targetValue": max(1, int(round(value)))}
    if intensity:
        sec.update(intensity)
    return sec


def _zone(z: int) -> Dict[str, Any]:
    return {"intensityType": HR, "sectionIntensity": z}


def _abs(kind: int, rng: Tuple[int, int]) -> Dict[str, Any]:
    return {"intensityType": kind, "intensityValueStart": int(rng[0]), "intensityValueEnd": int(rng[1])}


def _main_intensity(t: Dict[str, Any], prefer_pace: bool, fallback_zone: int = 2) -> Dict[str, Any]:
    """The session's own pace or HR range; the watch's HR zone when the plan text has neither."""
    if prefer_pace and t["pace"]:
        return _abs(PACE, t["pace"])
    if t["hr"]:
        return _abs(HR, t["hr"])
    if t["pace"]:
        return _abs(PACE, t["pace"])
    return _zone(fallback_zone)


def _round_m(km: float, step: int = 10) -> int:
    return max(step, int(round(km * 1000 / step)) * step)


def _fmt_km(km: float) -> str:
    return f"{km:.1f}".rstrip("0").rstrip(".")


def _warm_cool(total_km: float, main_km: float, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rest = max(total_km - main_km, 2.0)
    warm = _section(WARMUP, DIST, _round_m(rest * 0.55, 100), _zone(2))
    cool = _section(COOLDOWN, DIST, _round_m(rest * 0.45, 100), _zone(1))
    return [warm] + sections + [cool]


def build_course(session: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(course, None) for a pushable session, else (None, plain reason)."""
    stype = session.get("session_type") or ""
    if stype in NOT_PUSHABLE:
        return None, NOT_PUSHABLE[stype]
    km = float(session.get("distance_km") or 0.0)
    minutes = float(session.get("duration_min") or 0.0)
    if km <= 0 and minutes <= 0:
        return None, "No distance or duration to put on the watch."
    t = parse_target(session.get("target_pace_or_hr"))
    purpose = (session.get("stated_purpose") or "").strip()
    target_txt = (session.get("target_pace_or_hr") or "").replace("Heart Rate Focus: ", "Heart rate ").replace("Pace Focus: ", "Pace ")
    name = f"{stype} {_fmt_km(km)} km" if km else f"{stype} {int(minutes)} min"

    if stype == "LTHR Test":
        sections = [
            _section(WARMUP, TIME, 15 * 60, _zone(2)),
            _section(TRAIN, TIME, 10 * 60, _zone(4)),
            _section(TRAIN, TIME, 20 * 60, _zone(4)),
            _section(COOLDOWN, TIME, 10 * 60, _zone(1)),
        ]
        name = "Threshold HR test (30 min)"
        how = ("Warm up 15 min easy and add 3 x 20 s strides near the end. Then run 30 minutes solo at the best "
               "even effort you can hold: the watch splits it into 10 + 20 minutes automatically (the heart-rate "
               "zone is only a guide, run by effort). Never pause. Cool down 10 min easy. Afterwards, sync and "
               "analyse the run on the HR Zones page.")
    elif stype == "Threshold" and km >= 4:
        fast_km = km * 0.5
        reps = max(2, min(8, int(round(fast_km / 1.6))))
        rep_m = _round_m(fast_km / reps, 50)
        group = {"intervalGroup": True, "repeats": reps, "sets": [
            _section(TRAIN, DIST, rep_m, _main_intensity(t, prefer_pace=True, fallback_zone=4)),
            _section(RECOVER, TIME, 60, _zone(1)),
        ]}
        sections = _warm_cool(km, fast_km, [group])
        name = f"Threshold {reps} x {rep_m} m"
        how = f"Cruise intervals: warm up easy, then {reps} x {rep_m} m at threshold with 1 min easy jog between, then cool down."
    elif stype == "VO2max" and km >= 4:
        fast_km = km * 0.4
        reps = max(3, min(8, int(round(fast_km))))
        rep_s = int(round(t["pace"][0])) if t["pace"] else 240
        group = {"intervalGroup": True, "repeats": reps, "sets": [
            _section(TRAIN, DIST, 1000, _main_intensity(t, prefer_pace=True, fallback_zone=5)),
            _section(RECOVER, TIME, rep_s, _zone(1)),
        ]}
        sections = _warm_cool(km, fast_km, [group])
        name = f"VO2max {reps} x 1000 m"
        how = f"Warm up easy, then {reps} x 1000 m at interval pace with an equal-time easy jog between, then cool down."
    elif stype == "Marathon Pace" and km >= 4:
        fast_km = km * 0.7
        sections = _warm_cool(km, fast_km, [_section(TRAIN, DIST, _round_m(fast_km, 100), _main_intensity(t, prefer_pace=True, fallback_zone=3))])
        name = f"Marathon pace {_fmt_km(round(fast_km, 1))} km"
        how = f"Warm up easy, then about {_fmt_km(round(fast_km, 1))} km at goal marathon pace, then cool down."
    elif stype == "Race":
        sections = [_section(TRAIN, DIST, _round_m(km, 10), _main_intensity(t, prefer_pace=True, fallback_zone=4))]
        name = f"Race day {_fmt_km(km)} km"
        how = "Goal race: start controlled, hold an even pace and fuel as rehearsed."
    else:
        prefer_pace = t["focus"] == "pace"
        value, ttype = (_round_m(km, 10), DIST) if km > 0 else (minutes * 60, TIME)
        sections = [_section(TRAIN, ttype, value, _main_intensity(t, prefer_pace))]
        how = ""

    description = " ".join(x for x in (how, purpose, f"Target: {target_txt}." if target_txt else "",
                                       "Planned by Running Coach.") if x)
    course = {"courseName": name[:100], "courseDescription": description[:1000], "sportType": RUN, "sections": sections}
    return course, None


def course_hash(course: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(course, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def describe_sections(course: Dict[str, Any]) -> List[str]:
    """Human-readable steps for the preview page."""
    names = {WARMUP: "Warm-up", TRAIN: "Run", RECOVER: "Recover", COOLDOWN: "Cool-down"}

    def one(sec):
        amount = (f"{sec['targetValue'] / 1000:.2f}".rstrip("0").rstrip(".") + " km") if sec["targetType"] == DIST \
            else f"{sec['targetValue'] // 60} min" + (f" {sec['targetValue'] % 60} s" if sec["targetValue"] % 60 else "")
        if "sectionIntensity" in sec:
            inten = f"HR zone {sec['sectionIntensity']}"
        elif sec.get("intensityType") == HR:
            inten = f"{sec['intensityValueStart']}–{sec['intensityValueEnd']} bpm"
        elif sec.get("intensityType") == PACE:
            a, b = sec["intensityValueStart"], sec["intensityValueEnd"]
            inten = f"{a // 60}:{a % 60:02d}–{b // 60}:{b % 60:02d} /km" if a != b else f"{a // 60}:{a % 60:02d} /km"
        else:
            inten = "no target"
        return f"{names.get(sec['sectionType'], 'Run')} {amount} @ {inten}"

    out = []
    for sec in course["sections"]:
        if sec.get("intervalGroup"):
            out.append(f"{sec['repeats']} x (" + " + ".join(one(m) for m in sec["sets"]) + ")")
        else:
            out.append(one(sec))
    return out
