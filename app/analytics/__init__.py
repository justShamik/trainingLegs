"""Privacy-first, self-hosted analytics (ADR-006). Nothing leaves the machine."""
import re
import time
from urllib.parse import urlparse, parse_qs

from flask import Flask, g, request, current_app

from app.analytics import store

_TOPICS = [
    ("sleep_recovery", r"sleep|hrv|recover|rest|tired|fatigue"),
    ("load_safety", r"acwr|load|injur|niggle|pain|overtrain|risk"),
    ("pace_volume", r"pace|volume|distance|km|mileage|speed"),
    ("race_plan", r"race|marathon|plan|goal|taper|target"),
    ("strength", r"strength|gym|squat|mobility|s&c"),
]


def topic_bucket(question: str) -> str:
    q = (question or "").lower()
    for name, pat in _TOPICS:
        if re.search(pat, q):
            return name
    return "other"


def track(event_type: str, **props) -> None:
    """Record a server-side event. Never raises, respects Do-Not-Track."""
    try:
        if request.headers.get("DNT") == "1":
            return
        page = props.pop("page", request.path)
        target = props.pop("target", None)
        duration_ms = props.pop("duration_ms", None)
        store.insert_event(current_app.config.get("DATABASE_PATH"), event_type, page=page,
                           target=target, props=props or None, duration_ms=duration_ms)
    except Exception:
        pass


def _after_endpoint(response, elapsed_ms: float) -> None:
    ep = request.endpoint
    ok = response.status_code < 400
    if request.method == "POST":
        if ep == "sync_data":
            loc = response.headers.get("Location", "")
            qs = parse_qs(urlparse(loc).query)
            status = (qs.get("sync_status") or ["error"])[0]
            m = re.search(r"(\d+)", (qs.get("sync_msg") or [""])[0])
            track("sync_started", full=request.form.get("full") == "1")
            track("sync_finished", status="success" if status == "success" else "failed",
                  records=int(m.group(1)) if m else None, duration_ms=round(elapsed_ms, 1))
        elif ep == "plan_generate" and ok:
            track("plan_generated", is_deload=request.form.get("is_deload") == "1")
        elif ep == "plan_discard" and ok:
            track("feature_used", target="plan_discard")
        elif ep == "session_update" and ok:
            track("session_logged", status=str(request.form.get("status") or "Completed")[:20])
        elif ep == "strength_generate" and ok:
            track("feature_used", target="strength_generate")
        elif ep == "strength_update" and ok:
            if request.form.get("status", "Completed") == "Completed":
                track("feature_used", target="strength_complete")
        elif ep == "chat":
            data = request.get_json(silent=True) or {}
            q = data.get("question", "") if isinstance(data, dict) else ""
            if isinstance(q, str) and q.strip():
                # Only length and topic bucket are stored, NEVER the text.
                track("chat_question", length=len(q.strip()), topic=topic_bucket(q), ok=ok)
        elif ep == "profile" and ok:
            track("feature_used", target="profile_saved")
    if response.status_code >= 500:
        track("error", target=f"HTTP {response.status_code}", source="server")


def init_analytics(app: Flask) -> None:
    """Register analytics: schema + pruning, request hooks, API/dashboard blueprint."""
    try:
        store.init_schema(app.config.get("DATABASE_PATH"))
    except Exception:
        app.logger.warning("analytics schema init failed", exc_info=True)

    from app.analytics.views import bp
    app.register_blueprint(bp)
    app.extensions["analytics_rate"] = {"window_start": 0.0, "count": 0}

    @app.before_request
    def _an_start():
        g._an_t0 = time.perf_counter()

    @app.after_request
    def _an_after(response):
        try:
            path = request.path
            if path.startswith("/static") or path.startswith("/analytics") or not request.endpoint:
                return response
            if request.args.get("analytics") == "off":
                return response
            elapsed = (time.perf_counter() - getattr(g, "_an_t0", time.perf_counter())) * 1000
            if request.method == "GET" and response.mimetype == "text/html":
                track("page_view", status=response.status_code, duration_ms=round(elapsed, 1))
            _after_endpoint(response, elapsed)
        except Exception:
            pass
        return response
