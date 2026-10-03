"""SQLite persistence for race scan state (table ``race_watch_status``)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

RACE_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS race_watch_status (
    race_id       TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'unknown',
    confidence    TEXT NOT NULL DEFAULT 'low',
    evidence      TEXT,
    evidence_url  TEXT,
    detected_dates TEXT,          -- JSON list of {date, raw, kind, url}
    http_status   INTEGER,
    error         TEXT,
    checked_at    TEXT NOT NULL,  -- UTC ISO-8601, last scan attempt
    last_ok_at    TEXT,           -- UTC ISO-8601, last scan that produced a known status
    changed_at    TEXT            -- UTC ISO-8601, last time the known status changed
)
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(RACE_STATUS_DDL)


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["detected_dates"] = json.loads(d.get("detected_dates") or "[]")
    except ValueError:
        d["detected_dates"] = []
    return d


def load_states(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    ensure_table(conn)
    conn.row_factory = sqlite3.Row
    return {r["race_id"]: _row_to_dict(r) for r in conn.execute("SELECT * FROM race_watch_status")}


def upsert_scan(conn: sqlite3.Connection, scan: Dict[str, Any], seed_status: str,
                previous: Optional[Dict[str, Any]] = None) -> bool:
    """Persist a scan without letting an 'unknown' result clobber a known status.

    Returns True when the known status changed versus the previous known value (prior row, else seed).
    """
    ensure_table(conn)
    now = scan.get("checked_at")
    known = scan.get("status") in ("open", "not_started", "closed")
    prev_known = (previous or {}).get("status")
    if prev_known not in ("open", "not_started", "closed"):
        prev_known = seed_status if seed_status in ("open", "not_started", "closed") else None

    authoritative = known and scan.get("confidence") in ("high", "medium")
    prev_applied = bool(previous) and previous.get("status") in ("open", "not_started", "closed") \
        and previous.get("confidence") in ("high", "medium")
    if authoritative or (known and not prev_applied):
        changed = authoritative and prev_known is not None and scan["status"] != prev_known
        conn.execute(
            """INSERT INTO race_watch_status (race_id, status, confidence, evidence, evidence_url, detected_dates,
                   http_status, error, checked_at, last_ok_at, changed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(race_id) DO UPDATE SET status=excluded.status, confidence=excluded.confidence,
                   evidence=excluded.evidence, evidence_url=excluded.evidence_url,
                   detected_dates=excluded.detected_dates, http_status=excluded.http_status,
                   error=excluded.error, checked_at=excluded.checked_at, last_ok_at=excluded.last_ok_at,
                   changed_at=COALESCE(excluded.changed_at, race_watch_status.changed_at)""",
            (scan["race_id"], scan["status"], scan.get("confidence") or "low", scan.get("evidence"),
             scan.get("evidence_url"), json.dumps(scan.get("detected_dates") or []), scan.get("http_status"),
             scan.get("error"), now, now, now if changed else None))
        return changed

    # Unknown (or weak result over a confident one): record the attempt (http status / error / time) but keep prior status + evidence.
    conn.execute(
        """INSERT INTO race_watch_status (race_id, status, confidence, evidence, detected_dates, http_status,
               error, checked_at) VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(race_id) DO UPDATE SET http_status=excluded.http_status, error=excluded.error,
               checked_at=excluded.checked_at""",
        (scan["race_id"], "unknown", "low", scan.get("evidence"), json.dumps(scan.get("detected_dates") or []),
         scan.get("http_status"), scan.get("error"), now))
    return False
