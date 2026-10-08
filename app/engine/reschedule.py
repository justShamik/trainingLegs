"""Session adjustments: swap a session for a lighter alternative, or mark it missed and rebalance the week.

Pure functions over the active-plan dict returned by get_active_training_plan (no DB access). A proposal lists
per-day before -> after changes; nothing is written until the caller passes the confirmed proposal to
app.data.queries.apply_session_adjustments.

Rebalancing rules (evidence-based, enforced here, checked with guardrails.validate_multiweek_plan):
1. Hard sessions (Threshold / VO2max / Long Run / Vert) never land on consecutive days.
2. Missed volume is not simply added to other days: at most MAX_CARRY_SHARE of the dropped km reappears, only
   on easy runs, each growing by at most MAX_DAY_INCREASE (the 10% rule), so the week never exceeds its plan
   and the >=80% easy distribution holds.
3. If the week cannot absorb a session it is dropped, not crammed.
4. A missed long run or key quality session is moved to a LATER easy day (or a free available day) of the same
   week only if the spacing rules still hold; otherwise it is dropped.
5. Rest days only become run days if they are in the profile's available days.
6. Illness: nothing is made up, and hard sessions in the next 2 days are eased to short easy runs.
7. The proposal is validated with validate_multiweek_plan on the "as executed" plan (skipped sessions count as
   rest). It may not add any violation that skipping the session alone would not cause. Volume-ramp checks of
   weeks after the current week are ignored, because those weeks were planned against the prescribed week and
   one missed session is not a reason to cut next week.
"""
import copy
import hashlib
import json
import math
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from app.engine.guardrails import EASY_SESSION_TYPES, HARD_SESSION_TYPES, easy_km, validate_multiweek_plan, weekly_volumes

REASONS: List[Tuple[str, str]] = [
    ("illness", "Illness"), ("travel", "Travel"), ("time", "Short on time"), ("weather", "Weather"), ("other", "Other"),
]
REASON_LABELS = dict(REASONS)
QUALITY_TYPES = {"Threshold", "VO2max", "Vert/Time-on-Feet", "LTHR Test"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_AVAILABLE_DAYS = {0, 1, 3, 5, 6}     # profile default Mon,Tue,Thu,Sat,Sun

MAX_CARRY_SHARE = 0.25      # at most 25% of the dropped km is re-added elsewhere in the week
MAX_DAY_INCREASE = 0.10     # each receiving easy run grows by at most 10%
MIN_QUALITY_KEEP = 0.5      # 80/20 repair may trim a pending quality session to no less than half
ILLNESS_EASE_DAYS = 2       # hard sessions within this many days after an illness become short easy runs

EASY_TARGET = "Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"
RECOVERY_TARGET = "Heart Rate Focus: 115 – 130 bpm (Zone 1 Recovery, 6:30 – 7:00 /km)"
XTRAIN_TARGET = "Heart Rate Focus: 120 – 140 bpm (Zone 1-2 non-impact: bike, elliptical, pool)"
REST_TARGET = "Rest & Recovery"

_FIELDS = ("session_type", "distance_km", "duration_min", "target_pace_or_hr", "stated_purpose", "status")
_VOLUME_RE = re.compile(r"^Week (\d+) volume increase")


class AdjustError(ValueError):
    """The requested adjustment is not possible (unknown session, already done, outside the current week...)."""


# ---------------------------------------------------------------------------- small helpers
def _d(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _km(s: Dict[str, Any]) -> float:
    return float(s.get("distance_km") or 0.0)


def _min(s: Dict[str, Any]) -> float:
    return float(s.get("duration_min") or 0.0)


def _r1(x: float) -> float:
    return round(x + 1e-9, 1)


def fmt_km(km: Any) -> str:
    return f"{float(km or 0.0):g}"


def day_label(s: Dict[str, Any]) -> str:
    d = _d(s.get("session_date"))
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}" if d else str(s.get("day_of_week") or "")


def describe(s: Dict[str, Any]) -> str:
    """'Threshold 10 km', 'Cross-Training 45 min', 'Rest'."""
    t = s.get("session_type") or "Rest"
    if t == "Rest":
        return "Rest"
    if _km(s) > 0:
        return f"{t} {fmt_km(_km(s))} km"
    return f"{t} {int(_min(s))} min" if _min(s) else t


def parse_available_days(text: Optional[str]) -> Set[int]:
    days = {WEEKDAYS.index(p.strip()[:3].title()) for p in str(text or "").split(",")
            if p.strip()[:3].title() in WEEKDAYS}
    return days or set(DEFAULT_AVAILABLE_DAYS)


def week_bounds(today: date) -> Tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def _pending(s: Dict[str, Any]) -> bool:
    return s.get("status") in (None, "", "Pending")


def can_swap(s: Dict[str, Any], today: date) -> bool:
    """Swap: a not-yet-done run from today to the end of the current week."""
    d = _d(s.get("session_date"))
    return bool(d and s.get("session_type") != "Rest" and _pending(s) and today <= d <= week_bounds(today)[1])


def can_mark_missed(s: Dict[str, Any], today: date) -> bool:
    """Missed: any not-yet-done run of the current week (also an earlier day still Pending)."""
    d = _d(s.get("session_date"))
    monday, sunday = week_bounds(today)
    return bool(d and s.get("session_type") != "Rest" and _pending(s) and monday <= d <= sunday)


def adjustable_sessions(plan: Optional[Dict[str, Any]], today: date) -> Dict[str, Dict[str, bool]]:
    """{session_id: {"swap": bool, "missed": bool}} for the sessions that offer the adjust link."""
    out: Dict[str, Dict[str, bool]] = {}
    for s in (plan or {}).get("sessions", []):
        acts = {"swap": can_swap(s, today), "missed": can_mark_missed(s, today)}
        if acts["swap"] or acts["missed"]:
            out[s["id"]] = acts
    return out


def _snapshot(s: Dict[str, Any]) -> Dict[str, Any]:
    return {k: s.get(k) for k in _FIELDS}


def _set(s: Dict[str, Any], session_type: str, km: float, minutes: float, target: str, purpose: str) -> None:
    s.update({"session_type": session_type, "distance_km": _r1(km), "duration_min": float(round(minutes)),
              "target_pace_or_hr": target, "stated_purpose": purpose})


def _scale(s: Dict[str, Any], new_km: float) -> None:
    old = _km(s)
    if old > 0 and _min(s):
        s["duration_min"] = float(round(_min(s) * new_km / old))
    s["distance_km"] = _r1(new_km)


def _sorted_copy(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted((copy.deepcopy(s) for s in plan.get("sessions", [])), key=lambda s: str(s.get("session_date") or ""))


def _find(sessions: List[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
    for s in sessions:
        if s.get("id") == session_id:
            return s
    raise AdjustError("Session not found in the active plan.")


# ---------------------------------------------------------------------------- guardrail checks
def effective_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The plan as it will actually be executed: skipped sessions count as rest days."""
    return [{**s, "session_type": "Rest", "distance_km": 0.0, "duration_min": 0.0} if s.get("status") == "Skipped" else s
            for s in sessions]


def check_guardrails(sessions: List[Dict[str, Any]], prior_volume_km: float, current_week: int) -> Tuple[Set[str], List[str]]:
    """Run validate_multiweek_plan on the executed view. Returns (comparable violation keys, raw violations)."""
    _, raw = validate_multiweek_plan({"sessions": effective_sessions(sessions)}, prior_volume_km)
    keys: Set[str] = set()
    for v in raw:
        m = _VOLUME_RE.match(v)
        if m:
            if int(m.group(1)) > current_week:
                continue  # later weeks were planned against the prescribed (not executed) current week
            v = re.sub(r"\s*\(Prior.*$", "", v)
        keys.add(v)
    return keys, raw


def _week(sessions: List[Dict[str, Any]], week: int) -> List[Dict[str, Any]]:
    return [s for s in sessions if int(s.get("week_number") or 1) == week]


def _easy_ok(sessions: List[Dict[str, Any]], week: int) -> bool:
    eff = _week(effective_sessions(sessions), week)
    total = sum(_km(s) for s in eff)
    easy = sum(easy_km(s) for s in eff)
    return total <= 0 or easy / total * 100.0 >= 79.9


# ---------------------------------------------------------------------------- swap
def _option(key: str, label: str, why: str, session_type: str, km: float, minutes: float, target: str,
            purpose: str) -> Dict[str, Any]:
    return {"key": key, "label": label, "why": why, "recommended": False,
            "after": {"session_type": session_type, "distance_km": _r1(km), "duration_min": float(round(minutes)),
                      "target_pace_or_hr": target, "stated_purpose": purpose,
                      "status": "Skipped" if session_type == "Rest" else "Pending"}}


def swap_options(session: Dict[str, Any], reason: str) -> List[Dict[str, Any]]:
    """Lower-load alternatives for a session, tailored to the reason. Illness only offers rest / very easy."""
    t, km = session.get("session_type") or "Easy Aerobic", _km(session)
    minutes = _min(session) or round(km * 6.0)
    rest = _option("rest", "Rest day", "Take the day off. Counts as a skipped session in compliance.",
                   "Rest", 0.0, 0.0, REST_TARGET, "Rest day replacing the planned session.")
    if reason == "illness":
        rest["why"] = "Illness: rest is the safest choice. Resume easy running after 24 h without symptoms."
        rest["recommended"] = True
        very_easy = _option("very_easy", "Very easy 20 min (only if symptoms are above the neck)",
                            "No fever, chest or body aches: a short Zone 1 jog at most. Stop if you feel worse.",
                            "Easy Aerobic", 20 / 6.5, 20, RECOVERY_TARGET,
                            f"Very easy 20 min jog replacing {describe(session)} while unwell.")
        return [rest, very_easy]

    opts: List[Dict[str, Any]] = []
    if t == "LTHR Test":
        easy_km = min(km, minutes / 6.0)
        opts.append(_option("easy", f"Easy aerobic run instead ({int(minutes)} min)",
                            "A shortened or tired test gives a wrong threshold HR, so postpone it and run easy today. "
                            "Do the test on a fresh, cool day within the next week or two.",
                            "Easy Aerobic", easy_km, minutes, EASY_TARGET,
                            f"Easy aerobic run replacing the zone test (postponed)."))
    elif t in QUALITY_TYPES:
        opts.append(_option("short", f"Shortened {t} ({fmt_km(_r1(km * 0.6))} km)",
                            "Same stimulus with fewer reps: about 60% of the planned work.",
                            t, km * 0.6, minutes * 0.6, session.get("target_pace_or_hr") or EASY_TARGET,
                            f"Shortened {t}: fewer reps at the same target. {session.get('stated_purpose') or ''}".strip()))
        easy_km = min(km, minutes / 6.0)
        opts.append(_option("easy", f"Easy aerobic run, similar time ({int(minutes)} min)",
                            "Keeps the time on feet but drops the intensity: much lower load.",
                            "Easy Aerobic", easy_km, minutes, EASY_TARGET,
                            f"Easy aerobic run replacing {describe(session)}."))
    elif t == "Long Run":
        opts.append(_option("short", f"Shortened long run ({fmt_km(_r1(km * 0.65))} km)",
                            "About two thirds of the distance at the same easy long-run effort.",
                            "Long Run", km * 0.65, minutes * 0.65, session.get("target_pace_or_hr") or EASY_TARGET,
                            "Shortened long run: endurance stimulus kept, less time on feet."))
        opts.append(_option("easy", f"Easy aerobic run ({fmt_km(_r1(km * 0.5))} km)",
                            "Half the distance as a normal easy run.",
                            "Easy Aerobic", km * 0.5, km * 0.5 * 6.0, EASY_TARGET,
                            f"Easy aerobic run replacing {describe(session)}."))
    elif km > 0:
        opts.append(_option("short", f"Short easy run ({fmt_km(_r1(km * 0.6))} km)",
                            "About 60% of the planned easy run.",
                            t, km * 0.6, minutes * 0.6, session.get("target_pace_or_hr") or EASY_TARGET,
                            f"Shortened easy run. {session.get('stated_purpose') or ''}".strip()))
    if t != "Cross-Training":
        xmin = max(20.0, min(minutes, 60.0))
        opts.append(_option("xtrain", f"Cross-training, non-impact ({int(xmin)} min)",
                            "Bike, elliptical or pool at easy effort: aerobic work without running load.",
                            "Cross-Training", 0.0, xmin, XTRAIN_TARGET,
                            f"Non-impact cross-training replacing {describe(session)}."))
    opts.append(rest)

    preferred = {"time": "short", "travel": "short", "weather": "easy" if t in QUALITY_TYPES else "xtrain",
                 "other": "short"}.get(reason, "short")
    keys = [o["key"] for o in opts]
    pick = preferred if preferred in keys else keys[0]
    for o in opts:
        o["recommended"] = o["key"] == pick
    return opts


# ---------------------------------------------------------------------------- proposals
def _context(plan: Dict[str, Any], sessions: List[Dict[str, Any]], target: Dict[str, Any]) -> Tuple[int, float]:
    current_week = int(target.get("week_number") or 1)
    prior = weekly_volumes(sessions).get(1, 0.0)   # prescribed week 1: proposals never add net volume
    return current_week, prior


def _finish(mode: str, reason: str, note: str, target: Dict[str, Any], original: List[Dict[str, Any]],
            proposed: List[Dict[str, Any]], actions: Dict[str, Tuple[str, str]], notes: List[str],
            baseline_keys: Set[str], prior: float, current_week: int) -> Dict[str, Any]:
    by_id = {s["id"]: s for s in original}
    changes = []
    for s in proposed:
        before = by_id[s["id"]]
        if _snapshot(before) == _snapshot(s):
            continue
        action, why = actions.get(s["id"], ("Changed", ""))
        changes.append({"session_id": s["id"], "date": s.get("session_date"), "date_label": day_label(s),
                        "is_target": s["id"] == target["id"], "action": action, "why": why,
                        "before": _snapshot(before), "after": _snapshot(s),
                        "before_text": describe(before), "after_text": describe(s)})
    keys, raw = check_guardrails(proposed, prior, current_week)
    new = sorted(keys - baseline_keys)
    week_before = _r1(sum(_km(s) for s in _week(effective_sessions(original), current_week)))
    week_after = _r1(sum(_km(s) for s in _week(effective_sessions(proposed), current_week)))
    proposal = {
        "mode": mode, "reason": reason, "reason_label": REASON_LABELS.get(reason, "Other"), "note": note,
        "session_id": target["id"], "session_label": f"{day_label(target)}: {describe(target)}",
        "week_number": current_week, "changes": changes, "notes": notes,
        "valid": not new, "new_violations": new,
        "existing_violations": sorted(k for k in keys if k in baseline_keys),
        "week_km_before": week_before, "week_km_after": week_after,
    }
    proposal["token"] = proposal_token(proposal)
    return proposal


def proposal_token(proposal: Dict[str, Any]) -> str:
    """Fingerprint of the proposed changes: confirm only applies what the preview showed."""
    payload = [(c["session_id"], c["before"], c["after"]) for c in proposal["changes"]]
    payload.append((proposal["mode"], proposal["reason"], proposal.get("note") or ""))
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _normalise_reason(reason: Optional[str]) -> str:
    return reason if reason in REASON_LABELS else "other"


def propose_swap(plan: Dict[str, Any], session_id: str, option_key: str, reason: Optional[str], note: str = "",
                 today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    reason = _normalise_reason(reason)
    original = _sorted_copy(plan)
    target = _find(original, session_id)
    if not can_swap(target, today):
        raise AdjustError("Only a not-yet-done run from today to the end of this week can be swapped.")
    option = next((o for o in swap_options(target, reason) if o["key"] == option_key), None)
    if option is None:
        raise AdjustError("Unknown alternative for this session.")
    current_week, prior = _context(plan, original, target)

    skip_only = copy.deepcopy(original)
    _find(skip_only, session_id)["status"] = "Skipped"
    baseline_keys, _ = check_guardrails(skip_only, prior, current_week)

    proposed = copy.deepcopy(original)
    t = _find(proposed, session_id)
    t.update(option["after"])
    actions = {session_id: ("Swapped" if option["key"] != "rest" else "Swapped for rest (counts as skipped)",
                            option["why"])}
    notes = [f"Reason: {REASON_LABELS[reason]}. The original prescription stays on record and compliance is "
             f"measured against it: " + ("a rest day counts as Skipped." if option["key"] == "rest"
                                         else "the swapped session counts as Modified when done.")]
    return _finish("swap", reason, note, target, original, proposed, actions, notes, baseline_keys, prior, current_week)


def propose_missed(plan: Dict[str, Any], session_id: str, reason: Optional[str], note: str = "",
                   today: Optional[date] = None, available_days: Optional[str] = None) -> Dict[str, Any]:
    today = today or date.today()
    reason = _normalise_reason(reason)
    original = _sorted_copy(plan)
    target = _find(original, session_id)
    if not can_mark_missed(target, today):
        raise AdjustError("Only a not-yet-done run of the current week can be marked as missed.")
    current_week, prior = _context(plan, original, target)
    avail = parse_available_days(available_days)
    missed_date = _d(target["session_date"])
    missed_type, missed_km = target.get("session_type"), _km(target)

    skip_only = copy.deepcopy(original)
    _find(skip_only, session_id)["status"] = "Skipped"
    baseline_keys, _ = check_guardrails(skip_only, prior, current_week)

    def new_violations(sessions: List[Dict[str, Any]]) -> Set[str]:
        return check_guardrails(sessions, prior, current_week)[0] - baseline_keys

    def modifiable(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [s for s in sessions if int(s.get("week_number") or 1) == current_week and s["id"] != session_id
                and _pending(s) and (_d(s.get("session_date")) or today) > today]

    actions: Dict[str, Tuple[str, str]] = {
        session_id: ("Missed", f"Marked as skipped ({REASON_LABELS[reason]}). It stays on record and counts as Skipped.")}
    notes: List[str] = []
    base = copy.deepcopy(skip_only)
    dropped_km = missed_km
    host_id: Optional[str] = None

    if reason == "illness":
        notes.append("Illness: the missed session is not made up and no volume is added this week.")
        limit = max(today, missed_date) + timedelta(days=ILLNESS_EASE_DAYS)
        for s in modifiable(base):
            if s.get("session_type") in HARD_SESSION_TYPES and _d(s["session_date"]) <= limit:
                was = describe(s)
                km = _r1(_km(s) * 0.5)
                _set(s, "Easy Aerobic", km, km * 6.5, RECOVERY_TARGET,
                     f"Eased after illness (was {was}). Keep it very easy; skip it if symptoms return.")
                actions[s["id"]] = ("Eased after illness", "Hard sessions within 48 h of being ill are replaced by a short easy run.")
        if new_violations(base):
            # Halving a long run can tip the week under 80% easy: keep long runs, still ease the intense sessions
            for s in base:
                if s["id"] in actions and s["id"] != session_id and _find(original, s["id"]).get("session_type") == "Long Run":
                    s.update({k: v for k, v in _find(original, s["id"]).items() if k in _FIELDS})
                    del actions[s["id"]]
            notes.append("The long run is kept (shortening it would push the week under 80% easy); "
                         "run it only if you are fully recovered.")
        dropped_km = 0.0
    elif missed_type in HARD_SESSION_TYPES:
        later = [s for s in modifiable(base) if _d(s["session_date"]) > missed_date]
        hosts = [s for s in later if s.get("session_type") == "Easy Aerobic"] + \
                [s for s in later if s.get("session_type") == "Rest" and _d(s["session_date"]).weekday() in avail]
        for host in hosts:
            trial = copy.deepcopy(base)
            h = _find(trial, host["id"])
            _set(h, missed_type, missed_km, _min(target), target.get("target_pace_or_hr") or "",
                 f"{target.get('stated_purpose') or ''} (Moved from {day_label(target)}.)".strip())
            trim_acts: Dict[str, Tuple[str, str]] = {}
            trim_notes: List[str] = []
            if not _easy_ok(trial, current_week):
                # the easy run it replaces is gone, so the quality share rises: trim it (>= half kept) for 80/20
                _repair_80_20(trial, [h], current_week, trim_acts, trim_notes)
            if not new_violations(trial):
                was = describe(host)
                base, host_id = trial, host["id"]
                dropped_km = _km(host)
                actions[host_id] = (f"{missed_type} moved here",
                                    f"Moved from {day_label(target)}; replaces {was} (that volume is dropped, "
                                    "not added elsewhere). Spacing rules still hold."
                                    + (" Trimmed so the week stays at least 80% easy." if trim_acts else ""))
                notes.append(f"{missed_type} moved to {day_label(host)} - no hard sessions on consecutive days.")
                break
        if host_id is None:
            notes.append(f"No later day this week can take the {missed_type} without two hard days in a row or "
                         "breaking the rest-day rule, so it is dropped rather than crammed in.")
    else:
        notes.append("Easy run dropped; the week is not re-loaded with the missed kilometres.")

    def build(with_carry: bool) -> Tuple[List[Dict[str, Any]], Dict[str, Tuple[str, str]], List[str]]:
        sessions, acts, extra = copy.deepcopy(base), dict(actions), []
        if with_carry and dropped_km > 0:
            budget = _r1(dropped_km * MAX_CARRY_SHARE)
            eff = effective_sessions(sessions)
            prev_type = {}
            for i, s in enumerate(eff):
                prev_type[s["id"]] = eff[i - 1].get("session_type") if i else None
            added = 0.0
            for s in modifiable(sessions):
                if budget - added < 0.1:
                    break
                if s.get("session_type") != "Easy Aerobic" or s["id"] == host_id or _km(s) <= 0:
                    continue
                if prev_type.get(s["id"]) in HARD_SESSION_TYPES:
                    continue  # leave recovery runs after hard days alone
                add = min(budget - added, math.floor(_km(s) * MAX_DAY_INCREASE * 10) / 10.0)
                if add < 0.1:
                    continue
                _scale(s, _km(s) + add)
                added = _r1(added + add)
                acts[s["id"]] = ("Slightly extended", f"+{fmt_km(_r1(add))} km easy (max +10% per run).")
            if added:
                extra.append(f"Only {fmt_km(added)} of the {fmt_km(dropped_km)} dropped km are re-added "
                             f"(max {int(MAX_CARRY_SHARE * 100)}%, max +10% per easy run). The rest is not made up.")
        if not _easy_ok(sessions, current_week):
            _repair_80_20(sessions, modifiable(sessions), current_week, acts, extra)
        return sessions, acts, extra

    proposed, acts, extra = build(reason != "illness")
    if new_violations(proposed) and reason != "illness":
        proposed, acts, extra = build(False)
        extra.append("Re-adding volume would break a guardrail, so nothing is added.")
    if dropped_km > 0 and not any(a[0] == "Slightly extended" for a in acts.values()) and reason != "illness":
        extra.append(f"{fmt_km(dropped_km)} km dropped from this week (no easy run can safely absorb more).")
    return _finish("missed", reason, note, target, original, proposed, acts, notes + extra, baseline_keys, prior,
                   current_week)


def _repair_80_20(sessions: List[Dict[str, Any]], candidates: List[Dict[str, Any]], week: int,
                  acts: Dict[str, Tuple[str, str]], notes: List[str]) -> None:
    """Trim pending quality sessions (not below MIN_QUALITY_KEEP) so easy volume is >= 80% again, if achievable."""
    eff = _week(effective_sessions(sessions), week)
    total = sum(_km(s) for s in eff)
    hard = total - sum(easy_km(s) for s in eff)
    need = (hard - 0.2 * total) / 0.8          # km of quality to remove so hard <= 20% of the new total
    quality = [s for s in candidates if s.get("session_type") in QUALITY_TYPES and _km(s) > 0]
    room = sum(_km(s) * (1 - MIN_QUALITY_KEEP) for s in quality)
    if need <= 0 or room + 1e-9 < need:
        return
    for s in quality:
        cut = min(_km(s) * (1 - MIN_QUALITY_KEEP), need)
        cut = min(math.ceil(cut * 10) / 10.0, _km(s) * (1 - MIN_QUALITY_KEEP))
        if cut <= 0:
            continue
        _scale(s, _km(s) - cut)
        need -= cut
        acts[s["id"]] = ("Quality trimmed", f"-{fmt_km(_r1(cut))} km so easy running stays >= 80% of the week.")
        if need <= 1e-9:
            break
    notes.append("The quality session is trimmed slightly to keep the week at least 80% easy.")
