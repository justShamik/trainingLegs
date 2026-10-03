"""Race watchlist service: home-page view model, refresh (scan + persist), staleness check, discovery."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.data.db import get_db_connection
from app.races import store
from app.races.scanner import scan_race
from app.races.textutil import parse_date
from app.races.watchlist import load_seed, merge_state

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "open": "Registration open",
    "not_started": "Registration not started",
    "closed": "Registration closed",
    "unknown": "Status unknown",
}


def _fmt(d: Optional[date]) -> Optional[str]:
    return f"{d.day} {d.strftime('%b %Y')}" if d else None


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def last_registration_closed(previous: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Most recent previous-edition registration close date (validation hint), or None."""
    best = None
    for p in previous or []:
        d = parse_date(p.get("closed"))
        if d and (best is None or d > best[0]):
            best = (d, p)
    if not best:
        return None
    d, p = best
    year = p.get("edition_year")
    return {
        "date": d.isoformat(),
        "date_display": _fmt(d),
        "edition_year": year,
        "source": p.get("source"),
        "text": f"{year} edition registration closed {_fmt(d)}" if year else f"Registration closed {_fmt(d)}",
    }


def _load_states(db_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        states = store.load_states(conn)
        conn.commit()
        return states
    finally:
        conn.close()


def _view(race: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    """Build the display dict for one merged race; None if it should be hidden."""
    scan = race.get("scan") or {}
    event = parse_date(race.get("event_date"))
    status = race["status"]
    edition_passed = False
    event_text = race.get("event_date_text") or (_fmt(event) if event else "Date not announced")
    if event and event < today:
        if race["category"] != "watchlist":
            return None  # one-off / discovered events: past = gone
        # Recurring watchlist race whose listed edition is over: keep it, next edition unannounced.
        edition_passed = True
        scanned_after = _parse_ts(scan.get("last_ok_at"))
        if not (race["status_source"] == "scan" and scanned_after and scanned_after.date() > event):
            status = "unknown"
        event_text = f"Next edition date not announced (last edition {_fmt(event)})"
        event = None

    applied = race["status_source"] == "scan" and not edition_passed
    lrc = last_registration_closed(race.get("previous_registrations"))
    opens = parse_date(race.get("registration_opens"))
    closes = parse_date(race.get("registration_closes"))
    return {
        "id": race["id"],
        "name": race["name"],
        "distance_km": race.get("distance_km"),
        "location": race.get("location"),
        "category": race["category"],
        "is_watchlist": race["category"] == "watchlist",
        "event_date": event.isoformat() if event else None,
        "event_date_display": _fmt(event),
        "event_date_text": event_text,
        "edition_year": race.get("edition_year"),
        "edition_passed": edition_passed,
        "days_until_event": (event - today).days if event else None,
        "status": status,
        "status_label": STATUS_LABELS.get(status, STATUS_LABELS["unknown"]),
        "status_source": "scan" if applied else "seed",
        "confidence": scan.get("confidence") if applied else None,
        "registration_opens": opens.isoformat() if opens else None,
        "registration_opens_display": _fmt(opens),
        "registration_closes": closes.isoformat() if closes else None,
        "registration_closes_display": _fmt(closes),
        "last_registration_closed": lrc,
        "last_checked_at": scan.get("checked_at"),
        "last_ok_at": scan.get("last_ok_at"),
        "status_changed_at": scan.get("changed_at"),
        "evidence": scan.get("evidence"),
        "evidence_url": scan.get("evidence_url"),
        "scan_error": scan.get("error"),
        "source_url": race.get("official_url") or race.get("registration_url") or (race.get("sources") or [None])[0],
        "registration_url": race.get("registration_url"),
        "notes": race.get("notes"),
    }


def get_races_for_home(db_path: Optional[str] = None, today: Optional[date] = None,
                       seed_path: Optional[str] = None) -> Dict[str, Any]:
    """Home-page view model.

    Returns {"as_of", "races" (all, sorted by event date, unknown last), "watchlist", "ncr_50k",
             "last_checked_at", "needs_refresh"}.
    """
    today = today or date.today()
    seed = load_seed(seed_path)
    try:
        states = _load_states(db_path)
    except Exception as exc:  # DB problems must not break the home page
        logger.warning("Could not load race scan state: %s", exc)
        states = {}
    races = []
    for r in seed["races"]:
        v = _view(merge_state(r, states.get(r["id"])), today)
        if v:
            races.append(v)
    races.sort(key=lambda v: (v["event_date"] is None, v["event_date"] or "", v["name"].lower()))
    checked = [s.get("checked_at") for rid, s in states.items() if s.get("checked_at")]
    return {
        "as_of": seed.get("as_of"),
        "races": races,
        "watchlist": [v for v in races if v["category"] == "watchlist"],
        "ncr_50k": [v for v in races if v["category"] == "ncr_50k"],
        "last_checked_at": max(checked) if checked else None,
        "needs_refresh": _needs_refresh(seed["races"], states, 24, None),
    }


def _needs_refresh(races, states, max_age_hours, now) -> bool:
    now = now or datetime.now(timezone.utc)
    for r in races:
        if not (r.get("scrape_urls") or r.get("official_url") or r.get("registration_url")):
            continue  # nothing to scan
        ts = _parse_ts((states.get(r["id"]) or {}).get("checked_at"))
        if ts is None or now - ts > timedelta(hours=max_age_hours):
            return True
    return False


def needs_refresh(max_age_hours: float = 24, db_path: Optional[str] = None,
                  seed_path: Optional[str] = None, now: Optional[datetime] = None) -> bool:
    """True if any scannable race was never checked or was last checked more than max_age_hours ago."""
    seed = load_seed(seed_path)
    try:
        states = _load_states(db_path)
    except Exception:
        return True
    return _needs_refresh(seed["races"], states, max_age_hours, now)


def refresh_races(db_path: Optional[str] = None, fetch: Optional[Callable[[str], Any]] = None,
                  seed_path: Optional[str] = None, race_ids: Optional[List[str]] = None,
                  budget_s: float = 240.0, per_race_budget_s: float = 30.0) -> Dict[str, Any]:
    """Scan every watched race and persist results to race_watch_status.

    Returns {"checked", "changed", "errors", "results": [{race_id, status, confidence, changed, error, pages}]}.
    """
    seed = load_seed(seed_path)
    races = [r for r in seed["races"] if not race_ids or r["id"] in race_ids]
    summary: Dict[str, Any] = {"checked": 0, "changed": 0, "errors": 0, "results": []}
    started = time.monotonic()
    conn = get_db_connection(db_path)
    try:
        states = store.load_states(conn)
        for race in races:
            if time.monotonic() - started > budget_s:
                summary["results"].append({"race_id": race["id"], "skipped": "time budget exhausted"})
                continue
            prev = states.get(race["id"])
            # Scan against the current effective status (seed refined by earlier confident scans).
            effective = merge_state(race, prev)["status"]
            scan = scan_race({**race, "registration_status": effective}, fetch=fetch,
                             budget_s=per_race_budget_s).to_dict()
            if scan.get("error") == "no URLs to scan":
                summary["results"].append({"race_id": race["id"], "skipped": "no URLs to scan"})
                continue
            changed = store.upsert_scan(conn, scan, race["registration_status"], prev)
            conn.commit()
            summary["checked"] += 1
            summary["changed"] += int(changed)
            if scan.get("error"):
                summary["errors"] += 1
            summary["results"].append({
                "race_id": race["id"], "status": scan["status"], "confidence": scan["confidence"],
                "changed": changed, "conflict": scan["conflict"], "evidence": scan["evidence"],
                "error": scan["error"], "pages": scan["pages"],
            })
    finally:
        conn.close()
    return summary


def discover_candidates(fetch: Optional[Callable[[str], Any]] = None, seed_path: Optional[str] = None,
                        report: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Unverified NCR 50K candidates not already on the watchlist (never auto-added)."""
    from app.races.discover import discover_ncr_50k
    seed = load_seed(seed_path)
    known_names = {r["name"].lower() for r in seed["races"]}
    known_urls = {u for r in seed["races"] for u in [r.get("official_url"), r.get("registration_url"), *r["scrape_urls"]] if u}
    return [c for c in discover_ncr_50k(fetch=fetch, report=report)
            if c["name"].lower() not in known_names and c["url"] not in known_urls]
