"""Load + validate the race watchlist seed (race_watchlist.json) and merge it with scanned DB state.

The seed is curated research. Scanned state may only *refine* it: a scan result is applied when it is
a known status with high/medium confidence. "unknown" or low-confidence scans never replace the seed.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.races.textutil import parse_date

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = os.path.join(os.path.dirname(__file__), "race_watchlist.json")

STATUSES = ("open", "not_started", "closed", "unknown")
CATEGORIES = ("watchlist", "ncr_50k")
APPLY_CONFIDENCE = ("high", "medium")


def _iso_or_none(value) -> Optional[str]:
    d = parse_date(value)
    return d.isoformat() if d else None


def _str_list(value) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if v and str(v).strip()]
    return []


def _norm_status(value) -> str:
    s = str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")
    return s if s in STATUSES else "unknown"


def _valid_regex(value) -> Optional[str]:
    if not value:
        return None
    try:
        re.compile(str(value))
        return str(value)
    except re.error:
        logger.warning("Ignoring invalid ticket_filter regex %r", value)
        return None


def normalize_race(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a normalized race dict, or None if it lacks the required id/name."""
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not rid or not name:
        return None
    try:
        distance = float(raw["distance_km"]) if raw.get("distance_km") is not None else None
    except (TypeError, ValueError):
        distance = None
    category = str(raw.get("category") or "watchlist").strip().lower()
    if category not in CATEGORIES:
        category = "watchlist"
    try:
        edition_year = int(raw["edition_year"]) if raw.get("edition_year") not in (None, "") else None
    except (TypeError, ValueError):
        edition_year = None

    prev = []
    for p in raw.get("previous_registrations") or []:
        if not isinstance(p, dict):
            continue
        try:
            ey = int(p["edition_year"]) if p.get("edition_year") not in (None, "") else None
        except (TypeError, ValueError):
            ey = None
        prev.append({
            "edition_year": ey,
            "opened": _iso_or_none(p.get("opened")),
            "closed": _iso_or_none(p.get("closed")),
            "closed_raw": p.get("closed"),
            "source": p.get("source"),
        })

    official = (raw.get("official_url") or "").strip() or None
    reg_url = (raw.get("registration_url") or "").strip() or None
    scrape = _str_list(raw.get("scrape_urls"))
    return {
        "id": rid,
        "name": name,
        "distance_km": distance,
        "location": raw.get("location") or "",
        "category": category,
        "event_date": _iso_or_none(raw.get("event_date")),
        "event_date_text": raw.get("event_date_text") or "",
        "edition_year": edition_year,
        "registration_status": _norm_status(raw.get("registration_status")),
        "registration_opens": _iso_or_none(raw.get("registration_opens")),
        "registration_closes": _iso_or_none(raw.get("registration_closes")),
        "previous_registrations": prev,
        "official_url": official,
        "registration_url": reg_url,
        "scrape_urls": scrape,
        "sources": _str_list(raw.get("sources")),
        "notes": raw.get("notes") or "",
        # Optional scanner rules (see scanner.scan_race / docs/RACE_RESEARCH.md "Scanner rules")
        "ignore_phrases": _str_list(raw.get("ignore_phrases")),
        "ignore_signals": [s for s in (_norm_status(x) for x in _str_list(raw.get("ignore_signals"))) if s != "unknown"],
        "trusted_urls": _str_list(raw.get("trusted_urls")),
        "ticket_filter": _valid_regex(raw.get("ticket_filter")),
    }


def load_seed(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the seed JSON. Missing/broken file -> empty watchlist (logged), never an exception."""
    path = path or DEFAULT_SEED_PATH
    if not os.path.exists(path):
        logger.info("Race watchlist seed not found at %s", path)
        return {"as_of": None, "races": [], "path": path}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read race watchlist %s: %s", path, exc)
        return {"as_of": None, "races": [], "path": path, "error": str(exc)}
    if isinstance(data, list):  # tolerate a bare list of races
        data = {"races": data}
    races, seen = [], set()
    for raw in (data.get("races") or []):
        race = normalize_race(raw)
        if race is None:
            logger.warning("Skipping watchlist entry without id/name: %r", raw)
            continue
        if race["id"] in seen:
            logger.warning("Duplicate race id %s in watchlist; keeping first", race["id"])
            continue
        seen.add(race["id"])
        races.append(race)
    return {"as_of": _iso_or_none(data.get("as_of")), "races": races, "path": path}


def merge_state(race: Dict[str, Any], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Overlay persisted scan state onto a seed race. Adds: status, status_source, scan."""
    out = dict(race)
    out["status"] = race["registration_status"]
    out["status_source"] = "seed"
    out["scan"] = state
    if state:
        st = state.get("status")
        if st in ("open", "not_started", "closed") and state.get("confidence") in APPLY_CONFIDENCE:
            out["status"] = st
            out["status_source"] = "scan"
            # Fill (never overwrite) seed dates with dates the scanner tied to a phrase.
            for d in state.get("detected_dates") or []:
                if d.get("kind") == "opens" and not out.get("registration_opens") and st == "not_started":
                    out["registration_opens"] = d.get("date")
                if d.get("kind") == "closes" and not out.get("registration_closes") and st == "open":
                    out["registration_closes"] = d.get("date")
    return out
