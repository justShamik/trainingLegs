"""Analytics storage: schema, insert, prune, aggregation. SQLite only (ADR-001, ADR-006)."""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.data.db import get_db_connection

RETENTION_DAYS = 180

SCHEMA = """
CREATE TABLE IF NOT EXISTS analytics_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,
    page TEXT,
    target TEXT,
    props_json TEXT,
    duration_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_analytics_ts ON analytics_events(ts);
CREATE INDEX IF NOT EXISTS idx_analytics_type ON analytics_events(event_type);
"""

CLIENT_TYPES = {"click", "form_submit", "error", "page_load_ms", "time_on_page", "feature_used"}
MAX_PROPS_BYTES = 512

_SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def init_schema(db_path: Optional[str] = None) -> None:
    """Create the table and prune events older than RETENTION_DAYS."""
    conn = get_db_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime(_TS_FMT)
        conn.execute("DELETE FROM analytics_events WHERE ts < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


def _clip(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    return str(v).strip()[:n] or None


def insert_event(db_path, event_type, page=None, target=None, props=None,
                 duration_ms=None, session_id=None) -> bool:
    """Insert one sanitized event. Never raises."""
    try:
        props_json = None
        if props:
            props_json = json.dumps(props, default=str, separators=(",", ":"))
            if len(props_json.encode("utf-8")) > MAX_PROPS_BYTES:
                props_json = None
        if session_id is not None and not _SID_RE.match(str(session_id)):
            session_id = None
        try:
            dur = float(duration_ms) if duration_ms is not None else None
            if dur is not None and not (0 <= dur < 1e9):
                dur = None
        except (TypeError, ValueError):
            dur = None
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO analytics_events (ts, session_id, event_type, page, target, props_json, duration_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                (utc_now(), session_id, _clip(event_type, 40), _clip(page, 120),
                 _clip(target, 80), props_json, dur))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def delete_all(db_path=None) -> int:
    conn = get_db_connection(db_path)
    try:
        n = conn.execute("DELETE FROM analytics_events").rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def all_events(db_path=None, days: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(_TS_FMT)
            rows = conn.execute("SELECT * FROM analytics_events WHERE ts >= ? ORDER BY id", (cutoff,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM analytics_events ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _props(e) -> dict:
    try:
        return json.loads(e["props_json"]) if e["props_json"] else {}
    except Exception:
        return {}


def summarize(db_path=None, days: int = 30) -> Dict[str, Any]:
    events = all_events(db_path, days)
    by_type: Dict[str, List[dict]] = {}
    for e in events:
        by_type.setdefault(e["event_type"], []).append(e)

    def cnt(t):
        return len(by_type.get(t, []))

    sessions = {e["session_id"] for e in events if e["session_id"]}
    views = by_type.get("page_view", [])
    loads = [e["duration_ms"] for e in by_type.get("page_load_ms", []) if e["duration_ms"] is not None]

    finished = by_type.get("sync_finished", [])
    ok = [e for e in finished if _props(e).get("status") == "success"]
    sync_dur = [e["duration_ms"] for e in finished if e["duration_ms"] is not None]

    features: Dict[str, int] = {}
    named = {"sync_finished": "sync", "plan_generated": "plan_generate",
             "session_logged": "session_log", "chat_question": "chat"}
    for t, label in named.items():
        if cnt(t):
            features[label] = cnt(t)
    for e in by_type.get("feature_used", []):
        if e["target"]:
            features[e["target"]] = features.get(e["target"], 0) + 1

    pages: Dict[str, Dict[str, Any]] = {}
    for e in views:
        key = e["page"] or "?"
        p = pages.setdefault(key, {"page": key, "views": 0, "load": [], "time": []})
        p["views"] += 1
    for e in by_type.get("page_load_ms", []):
        if e["page"] in pages and e["duration_ms"] is not None:
            pages[e["page"]]["load"].append(e["duration_ms"])
    for e in by_type.get("time_on_page", []):
        if e["page"] in pages and e["duration_ms"] is not None:
            pages[e["page"]]["time"].append(e["duration_ms"])
    page_rows = []
    for p in sorted(pages.values(), key=lambda x: -x["views"]):
        page_rows.append({
            "page": p["page"], "views": p["views"],
            "avg_load_ms": round(sum(p["load"]) / len(p["load"])) if p["load"] else None,
            "avg_time_s": round(sum(p["time"]) / len(p["time"]) / 1000, 1) if p["time"] else None})

    daily: Dict[str, Dict[str, int]] = {}
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"page_views": 0, "actions": 0}
    action_types = ("click", "form_submit", "feature_used", "sync_finished",
                    "plan_generated", "session_logged", "chat_question")
    for e in events:
        d = e["ts"][:10]
        if d in daily:
            if e["event_type"] == "page_view":
                daily[d]["page_views"] += 1
            elif e["event_type"] in action_types:
                daily[d]["actions"] += 1

    dash_views = sum(1 for e in views if e["page"] in ("/", "/dashboard"))
    funnel = [
        {"step": "Home or dashboard viewed", "count": dash_views},
        {"step": "Sync completed", "count": len(ok)},
        {"step": "Plan generated", "count": cnt("plan_generated")},
        {"step": "Session logged", "count": cnt("session_logged")},
    ]
    errors = list(reversed(by_type.get("error", [])))[:20]
    return {
        "days": days,
        "kpis": {
            "sessions": len(sessions), "page_views": len(views),
            "sync_runs": len(finished),
            "sync_success_rate": round(100 * len(ok) / len(finished)) if finished else None,
            "avg_sync_s": round(sum(sync_dur) / len(sync_dur) / 1000, 1) if sync_dur else None,
            "errors": cnt("error"),
            "avg_page_load_ms": round(sum(loads) / len(loads)) if loads else None,
        },
        "features": sorted(({"feature": k, "count": v} for k, v in features.items()),
                           key=lambda x: -x["count"]),
        "pages": page_rows,
        "daily": [{"date": d, **v} for d, v in daily.items()],
        "funnel": funnel,
        "recent_errors": [{"ts": e["ts"], "page": e["page"],
                           "message": _props(e).get("message") or e["target"] or ""} for e in errors],
        "total_events": len(events),
    }
