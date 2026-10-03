"""Session intensity target helpers: parse and normalise the target_pace_or_hr text.

New plans store e.g. "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)".
Plans saved before that format was introduced hold generic text such as "Easy / Zone 2 (<75% HRMax)";
normalize_target() upgrades those to the explicit focus + numeric range format.
"""
import re
from typing import Dict, Optional

# (keyword, normalised target) checked in order against legacy text
_LEGACY_RULES = [
    ("marathon pace", "Pace Focus: 5:40 – 6:00 /km (Zone 2-3 Marathon Pace, 138 – 152 bpm)"),
    ("tempo", "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)"),
    ("threshold", "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)"),
    ("zone 4", "Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)"),
    ("vo2", "Pace Focus: 4:50 – 5:05 /km (Zone 5 VO2max, 172 – 185 bpm)"),
    ("zone 3", "Heart Rate Focus: 145 – 158 bpm (Zone 3 Steady, 5:50 – 6:15 /km)"),
    ("zone 2-3", "Heart Rate Focus: 135 – 155 bpm (Zone 2-3 Aerobic, 5:50 – 6:30 /km)"),
    ("zone 1", "Heart Rate Focus: 115 – 130 bpm (Zone 1 Recovery, 6:30 – 7:00 /km)"),
    ("recovery", "Heart Rate Focus: 115 – 130 bpm (Zone 1 Recovery, 6:30 – 7:00 /km)"),
    ("zone 2", "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"),
    ("easy", "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"),
]


def is_normalized(target: Optional[str]) -> bool:
    return bool(target) and ("Heart Rate Focus:" in target or "Pace Focus:" in target)


def normalize_target(target: Optional[str]) -> Optional[str]:
    """Return the explicit focus/range form of a target string (unchanged if already explicit or a rest day)."""
    if not target or is_normalized(target):
        return target
    lowered = target.lower()
    if "rest" in lowered or "mobility" in lowered or "s&c" in lowered:
        return target
    for keyword, replacement in _LEGACY_RULES:
        if keyword in lowered:
            return replacement
    return target


def describe_target(target: Optional[str]) -> Dict[str, Optional[str]]:
    """Split a target string into focus type, headline range and detail for display."""
    target = normalize_target(target) or ""
    m = re.match(r'\s*(Heart Rate|Pace) Focus:\s*([^(]+?)\s*(?:\((.*)\))?\s*$', target)
    if not m:
        return {"focus": None, "range": target or None, "detail": None}
    return {"focus": m.group(1), "range": m.group(2).strip(), "detail": (m.group(3) or "").strip() or None}
