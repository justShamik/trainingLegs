"""Lactate-threshold heart rate (LTHR) from a 30-minute solo field test, and COROS LT-model zones.

Method and evidence: docs/HR_ZONES_RESEARCH.md sections 3-5. LTHR = mean HR of minutes 10-30 of the test
(Friel rule), reported with the field-test standard error of +-8 bpm (McGehee, Tanner & Houmard 2005).
Pure functions only: no database or network access here.
"""
import io
import math
from datetime import datetime
from statistics import mean, median, pstdev
from typing import Any, Dict, List, Optional, Tuple

TEST_S = 1800
WINDOW_START_S, WINDOW_END_S = 600, 1800
WINDOW_S = WINDOW_END_S - WINDOW_START_S
SEM_BPM = 8
MIN_VALID_S = 1150
STOP_SPEED_MS = 1.5
MAX_SINGLE_STOP_S = 15
MAX_TOTAL_STOP_S = 60

# COROS Lactate Threshold model (EvoLab default), % of LTHR, verified on coros.com (research doc 5.1)
COROS_LT_MODEL: List[Tuple[str, str, Optional[float], Optional[float]]] = [
    ("Z1", "Recovery", None, 0.80),
    ("Z2", "Aerobic Endurance", 0.80, 0.90),
    ("Z3", "Aerobic Power", 0.90, 0.95),
    ("Z4", "Threshold", 0.95, 1.02),
    ("Z5", "Anaerobic Endurance", 1.02, 1.06),
    ("Z6", "Anaerobic Power", 1.06, None),
]

SENSORS = {"strap": "Chest strap", "wrist": "Wrist (optical)"}


class ZoneTestError(ValueError):
    """The activity cannot be analysed as a zone test; the message says why, in plain words."""


# ---------------------------------------------------------------------------------------- zones
def _bound(lthr: int, pct: float) -> int:
    # round() first so 0.8 * 170 = 136.00000000000003 does not ceil to 137
    return math.ceil(round(pct * lthr, 6))


def coros_lt_zones(lthr: int) -> List[Dict[str, Any]]:
    """Whole-bpm ranges for the six COROS LT zones; zone k spans [ceil(lo*L), ceil(hi*L) - 1]."""
    zones = []
    for code, name, lo, hi in COROS_LT_MODEL:
        zones.append({
            "zone": code, "name": name, "low_pct": lo, "high_pct": hi,
            "low": _bound(lthr, lo) if lo is not None else None,
            "high": _bound(lthr, hi) - 1 if hi is not None else None,
        })
    return zones


def zone_range_text(z: Dict[str, Any]) -> str:
    if z["low"] is None:
        return f"≤ {z['high']} bpm"
    if z["high"] is None:
        return f"≥ {z['low']} bpm"
    return f"{z['low']} – {z['high']} bpm"


def band_bpm(lthr: int, lo: float, hi: float) -> Tuple[int, int]:
    return _bound(lthr, lo), _bound(lthr, hi) - 1


# ------------------------------------------------------------------------------------- FIT input
def parse_fit(data: bytes) -> Dict[str, Any]:
    """Decode FIT `record` messages into 1 Hz-ish samples: t (s from first record), hr, speed (m/s), cadence."""
    import fitdecode

    samples: List[Dict[str, Any]] = []
    t0: Optional[datetime] = None
    avg_temp = None
    try:
        with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.RAISE) as fit:
            for frame in fit:
                if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                if frame.name == "session" and frame.has_field("avg_temperature"):
                    avg_temp = frame.get_value("avg_temperature")
                if frame.name != "record" or not frame.has_field("timestamp"):
                    continue
                ts = frame.get_value("timestamp")
                if not isinstance(ts, datetime):
                    continue
                t0 = t0 or ts

                def val(*names):
                    for n in names:
                        if frame.has_field(n):
                            v = frame.get_value(n)
                            if v is not None:
                                return v
                    return None

                samples.append({"t": int(round((ts - t0).total_seconds())), "hr": val("heart_rate"),
                                "speed": val("enhanced_speed", "speed"), "cadence": val("cadence")})
    except Exception as err:  # corrupt or truncated download
        raise ZoneTestError(f"The activity file could not be read ({type(err).__name__}).") from err
    if not samples:
        raise ZoneTestError("The activity file has no per-second records.")
    return {"samples": samples, "watch_avg_temperature": avg_temp}


# --------------------------------------------------------------------------------- test window
def window_from_laps(laps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the test from laps: a ~10:00 lap followed by a ~20:00 lap (pushed workout or LAP pressed at 10:00),
    or a single ~30:00 lap. Returns test start offset (s) and the 20-min lap's average HR when present."""
    for i, lap in enumerate(laps):
        t = float(lap.get("time") or 0)
        start = float(lap.get("totalLength") or 0) - t
        nxt = laps[i + 1] if i + 1 < len(laps) else None
        if abs(t - 600) <= 30 and nxt and abs(float(nxt.get("time") or 0) - 1200) <= 60:
            return {"start_s": start, "source": "10:00 + 20:00 laps", "lap_avg_hr": nxt.get("avgHr") or None,
                    "lap_time_s": float(nxt.get("time") or 0)}
    for lap in laps:
        t = float(lap.get("time") or 0)
        if abs(t - 1800) <= 60:
            return {"start_s": float(lap.get("totalLength") or 0) - t, "source": "30:00 lap", "lap_avg_hr": None,
                    "lap_time_s": t}
    return None


def window_auto(samples: List[Dict[str, Any]]) -> Optional[float]:
    """Start of the 30-min stretch with the highest average speed (the test effort), or None if too short."""
    speed = {s["t"]: float(s["speed"] or 0) for s in samples}
    if not speed:
        return None
    end = max(speed)
    if end < TEST_S:
        return None
    grid = [speed.get(t, 0.0) for t in range(end + 1)]
    prefix = [0.0]
    for v in grid:
        prefix.append(prefix[-1] + v)
    best_start, best = None, -1.0
    for start in range(0, end + 1 - TEST_S + 1, 5):
        total = prefix[start + TEST_S] - prefix[start]
        if total > best:
            best_start, best = start, total
    return float(best_start) if best_start is not None else None


# ------------------------------------------------------------------------------------- analysis
def _criteria(sensor: Optional[str], temp_c: Optional[float], **stats) -> List[Dict[str, Any]]:
    def c(key, label, ok, detail):
        return {"key": key, "label": label, "ok": bool(ok), "detail": detail}

    out = [
        c("sensor", "Chest strap", sensor == "strap",
          SENSORS.get(sensor or "", "Sensor not stated") + ("" if sensor == "strap" else ": optical HR is less reliable")),
        c("temperature", "Cool conditions (≤ 25 °C)", temp_c is not None and temp_c <= 25,
          f"{temp_c:g} °C" if temp_c is not None else "Temperature not recorded"),
    ]
    if "pace_cv_pct" in stats:
        cv = stats["pace_cv_pct"]
        out.append(c("pacing", "Even pacing (minute-to-minute variation ≤ 5%)", cv is not None and cv <= 5.0,
                     f"{cv:.1f}%" if cv is not None else "No pace data"))
        out.append(c("dropouts", "HR dropouts ≤ 2%", stats["missing_pct"] <= 2.0, f"{stats['missing_pct']:.1f}% missing"))
        out.append(c("cadence_lock", "No cadence lock", stats["lock_pct"] <= 2.0,
                     f"{stats['lock_pct']:.1f}% of the window looked locked to cadence"))
        out.append(c("drift", "HR drift ≤ 6 bpm", stats["drift_bpm"] is not None and stats["drift_bpm"] <= 6,
                     f"{stats['drift_bpm']:+d} bpm (minutes 20-30 vs 10-20)" if stats["drift_bpm"] is not None
                     else "Not measurable"))
    else:
        out.append(c("cleaning", "Per-second data checked for artefacts", False,
                     "Only lap averages were available: no dropout, spike or cadence-lock check"))
    return out


def _confidence(criteria: List[Dict[str, Any]], invalid: bool) -> str:
    missed = sum(1 for c in criteria if not c["ok"])
    if invalid or missed >= 2:
        return "Poor"
    return "Good" if missed == 0 else "Fair"


def _rolling_median(values: List[float], i: int, half: int = 7) -> float:
    lo, hi = max(0, i - half), min(len(values), i + half + 1)
    return median(values[lo:hi])


def analyse_samples(samples: List[Dict[str, Any]], start_s: float, sensor: Optional[str] = None,
                    temp_c: Optional[float] = None) -> Dict[str, Any]:
    """Clean minutes 10-30 of the test (research doc 4.3) and compute LTHR, diagnostics and confidence."""
    by_t = {s["t"]: s for s in samples}
    w0 = int(round(start_s)) + WINDOW_START_S
    if max(by_t) < w0 + WINDOW_S - 30:
        raise ZoneTestError("The activity ends before 30 minutes of test effort were recorded.")

    # 1-2. stops: missing seconds (watch paused) or < 1.5 m/s for 5 s or more
    moving: List[Optional[Dict[str, Any]]] = []
    stopped = [False] * WINDOW_S
    for i in range(WINDOW_S):
        s = by_t.get(w0 + i)
        moving.append(s)
        if s is None:
            stopped[i] = True
    i = 0
    while i < WINDOW_S:
        s = moving[i]
        if s is not None and s.get("speed") is not None and s["speed"] < STOP_SPEED_MS:
            j = i
            while j < WINDOW_S and moving[j] is not None and moving[j].get("speed") is not None \
                    and moving[j]["speed"] < STOP_SPEED_MS:
                j += 1
            if j - i >= 5:
                for k in range(i, j):
                    stopped[k] = True
            i = j
        else:
            i += 1
    stop_runs, run = [], 0
    for flag in stopped + [False]:
        if flag:
            run += 1
        elif run:
            stop_runs.append(run)
            run = 0
    longest_stop, total_stop = max(stop_runs or [0]), sum(stop_runs)
    invalid_reason = None
    if longest_stop > MAX_SINGLE_STOP_S:
        invalid_reason = f"a stop of {longest_stop} s during minutes 10-30 (limit {MAX_SINGLE_STOP_S} s)"
    elif total_stop > MAX_TOTAL_STOP_S:
        invalid_reason = f"{total_stop} s of stops during minutes 10-30 (limit {MAX_TOTAL_STOP_S} s)"

    # 3. dropouts + 6. bounds: interpolate gaps <= 5 s, drop longer
    hr: List[Optional[float]] = []
    for k in range(WINDOW_S):
        s = moving[k]
        v = s.get("hr") if (s is not None and not stopped[k]) else None
        hr.append(float(v) if v is not None and 40 <= v <= 220 else None)
    moving_n = sum(1 for k in range(WINDOW_S) if not stopped[k])
    k = 0
    while k < WINDOW_S:
        if hr[k] is None and not stopped[k]:
            j = k
            while j < WINDOW_S and hr[j] is None and not stopped[j]:
                j += 1
            before = hr[k - 1] if k > 0 else None
            after = hr[j] if j < WINDOW_S else None
            if j - k <= 5 and before is not None and after is not None:
                for m in range(k, j):
                    hr[m] = before + (after - before) * (m - k + 1) / (j - k + 1)
            k = j
        else:
            k += 1
    missing_n = sum(1 for k in range(WINDOW_S) if hr[k] is None and not stopped[k])
    missing_pct = 100.0 * missing_n / max(moving_n, 1)

    # 4. spikes: replace with the 15 s rolling median
    idx = [k for k in range(WINDOW_S) if hr[k] is not None]
    vals = [hr[k] for k in idx]
    spikes = 0
    cleaned = list(vals)
    for n in range(len(vals)):
        med = _rolling_median(vals, n)
        jump = abs(vals[n] - vals[n - 1]) if n > 0 and idx[n] - idx[n - 1] == 1 else 0
        if abs(vals[n] - med) > 10 or jump > 8:
            cleaned[n] = med
            spikes += 1
    clean = dict(zip(idx, cleaned))

    # 5. cadence lock (FIT cadence is per leg): flagged runs longer than 30 s
    locked = [False] * WINDOW_S
    for k in idx:
        cad = moving[k].get("cadence") if moving[k] else None
        if cad:
            h = clean[k]
            locked[k] = abs(h - cad * 2) <= 3 or abs(h - cad) <= 3
    lock_n, run = 0, 0
    for flag in locked + [False]:
        if flag:
            run += 1
        else:
            if run > 30:
                lock_n += run
            run = 0
    lock_pct = 100.0 * lock_n / max(len(idx), 1)

    if len(clean) < MIN_VALID_S and invalid_reason is None:
        invalid_reason = f"only {len(clean)} s of usable heart rate in minutes 10-30 (need {MIN_VALID_S} s)"
    if not clean:
        raise ZoneTestError("No usable heart-rate data in minutes 10-30 of the test.")

    lthr = int(round(mean(clean.values())))
    first = [v for k, v in clean.items() if k < WINDOW_S // 2]
    second = [v for k, v in clean.items() if k >= WINDOW_S // 2]
    drift = int(round(mean(second) - mean(first))) if first and second else None

    minute_speed = []
    for mnt in range(WINDOW_S // 60):
        sp = [moving[k]["speed"] for k in range(mnt * 60, mnt * 60 + 60)
              if moving[k] is not None and not stopped[k] and moving[k].get("speed")]
        if sp:
            minute_speed.append(mean(sp))
    pace_cv = 100.0 * pstdev(minute_speed) / mean(minute_speed) if len(minute_speed) >= 2 else None
    avg_speed = mean(minute_speed) if minute_speed else None
    half = len(minute_speed) // 2
    pace_change = (100.0 * (mean(minute_speed[half:]) - mean(minute_speed[:half])) / mean(minute_speed[:half])
                   if half else None)

    stats = {"pace_cv_pct": round(pace_cv, 1) if pace_cv is not None else None, "missing_pct": round(missing_pct, 1),
             "lock_pct": round(lock_pct, 1), "drift_bpm": drift}
    criteria = _criteria(sensor, temp_c, **stats)
    flags = []
    if spikes:
        flags.append(f"{spikes} heart-rate spike(s) smoothed")
    if drift is not None and drift > 8 and pace_change is not None and pace_change < -2:
        flags.append("HR rose more than 8 bpm while pace fell: heat, dehydration or a too-fast start")
    if invalid_reason:
        flags.append("Test invalid: " + invalid_reason)
    return {
        "method": "fit", "lthr": lthr, "confidence": _confidence(criteria, invalid_reason is not None),
        "invalid_reason": invalid_reason, "criteria": criteria, "flags": flags,
        "stats": {**stats, "valid_s": len(clean), "spikes": spikes, "longest_stop_s": longest_stop,
                  "total_stop_s": total_stop, "pace_change_pct": round(pace_change, 1) if pace_change is not None else None,
                  "avg_pace_s_km": round(1000.0 / avg_speed) if avg_speed else None},
    }


def analyse_lap_window(window: Dict[str, Any], sensor: Optional[str] = None,
                       temp_c: Optional[float] = None) -> Dict[str, Any]:
    """Fallback without the FIT file: the 20:00 lap's average HR is the Friel LTHR, uncleaned."""
    if not window.get("lap_avg_hr"):
        raise ZoneTestError("The 20-minute lap has no average heart rate.")
    criteria = _criteria(sensor, temp_c)
    return {"method": "laps", "lthr": int(window["lap_avg_hr"]), "confidence": _confidence(criteria, False),
            "invalid_reason": None, "criteria": criteria,
            "flags": ["Per-second file unavailable: result uses the lap average without artefact cleaning"],
            "stats": {"valid_s": int(window.get("lap_time_s") or 0)}}


def recommendation(result: Dict[str, Any], previous_lthr: Optional[int], observed_max_hr: Optional[int]) -> Dict[str, Any]:
    """Whether to update COROS, and cross-checks shown next to the result (research doc 4.4 and 8.4)."""
    lthr, conf = result["lthr"], result["confidence"]
    delta = lthr - previous_lthr if previous_lthr else None
    notes = []
    if observed_max_hr and lthr >= 0.95 * observed_max_hr:
        notes.append(f"Threshold HR is {lthr / observed_max_hr:.0%} of your highest recorded HR ({observed_max_hr} bpm): "
                     "your true max is probably higher than any run has shown.")
    if conf == "Poor":
        update, why = False, "Confidence is poor: don't change COROS. Repeat the test in better conditions."
    elif delta is not None and abs(delta) < 3:
        update, why = False, f"Within {abs(delta)} bpm of your previous test: no need to change COROS."
    else:
        update = True
        why = ("First test: enter this threshold HR in COROS." if delta is None
               else f"{delta:+d} bpm vs your previous test: update COROS.")
    return {"update_coros": update, "why": why, "delta": delta, "notes": notes}
