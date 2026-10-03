"""Analytics ingestion API, dashboard, export, delete."""
import csv
import io
import json
import time

from flask import Blueprint, Response, current_app, redirect, render_template, request, url_for

from app.analytics import store

bp = Blueprint("analytics", __name__)

MAX_BODY = 4096
RATE_LIMIT_PER_MIN = 120


def _rate_ok() -> bool:
    st = current_app.extensions.setdefault("analytics_rate", {"window_start": 0.0, "count": 0})
    now = time.monotonic()
    if now - st["window_start"] >= 60:
        st["window_start"], st["count"] = now, 0
    st["count"] += 1
    return st["count"] <= RATE_LIMIT_PER_MIN


@bp.route("/analytics/event", methods=["POST"])
def ingest():
    """Accept a client event. Always 204; bad/oversized/limited/DNT payloads are ignored."""
    try:
        if request.headers.get("DNT") == "1":
            return "", 204
        if (request.content_length or 0) > MAX_BODY:
            return "", 204
        raw = request.get_data(cache=False)
        if len(raw) > MAX_BODY or not _rate_ok():
            return "", 204
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or data.get("type") not in store.CLIENT_TYPES:
            return "", 204
        props = data.get("props")
        if not isinstance(props, dict):
            props = None
        else:
            props = {str(k)[:30]: (v if isinstance(v, (int, float, bool)) else str(v)[:80])
                     for k, v in list(props.items())[:8]}
        page = data.get("page")
        if not isinstance(page, str) or not page.startswith("/"):
            page = None
        target = data.get("target")
        store.insert_event(current_app.config.get("DATABASE_PATH"), data["type"], page=page,
                           target=target if isinstance(target, (str, int)) else None,
                           props=props, duration_ms=data.get("duration_ms"),
                           session_id=data.get("sid"))
    except Exception:
        pass
    return "", 204


@bp.route("/analytics")
def dashboard():
    days = request.args.get("days", 30, type=int)
    if days not in (7, 30, 90):
        days = 30
    summary = store.summarize(current_app.config.get("DATABASE_PATH"), days)
    return render_template("analytics.html", s=summary, days=days, active_page="analytics")


@bp.route("/analytics/export.csv")
def export_csv():
    rows = store.all_events(current_app.config.get("DATABASE_PATH"))
    buf = io.StringIO()
    cols = ["id", "ts", "session_id", "event_type", "page", "target", "props_json", "duration_ms"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=analytics_events.csv"})


@bp.route("/analytics/export.json")
def export_json():
    rows = store.all_events(current_app.config.get("DATABASE_PATH"))
    return Response(json.dumps(rows, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=analytics_events.json"})


@bp.route("/analytics/delete", methods=["POST"])
def delete():
    store.delete_all(current_app.config.get("DATABASE_PATH"))
    return redirect(url_for("analytics.dashboard"))
