"""Tests for the self-hosted analytics module (temp DBs only)."""
import json

import pytest

from app.analytics import store, topic_bucket
from app.data.db import get_db_connection
from app.web.routes import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "an.db"))
    app.testing = True
    app.config["_db"] = str(tmp_path / "an.db")
    return app.test_client(), app


def events(app, etype=None):
    conn = get_db_connection(app.config["_db"])
    try:
        q = "SELECT * FROM analytics_events" + (" WHERE event_type=?" if etype else "")
        return [dict(r) for r in conn.execute(q, (etype,) if etype else ())]
    finally:
        conn.close()


def post(c, payload, **kw):
    return c.post("/analytics/event", data=json.dumps(payload), content_type="text/plain", **kw)


GOOD = {"sid": "abcdefgh1234", "type": "click", "page": "/plan", "target": "Generate", "duration_ms": None}


def test_ingest_valid(client):
    c, app = client
    assert post(c, GOOD).status_code == 204
    ev = events(app, "click")
    assert len(ev) == 1 and ev[0]["target"] == "Generate" and ev[0]["session_id"] == "abcdefgh1234"


@pytest.mark.parametrize("payload", [
    {"type": "bogus"}, {"type": "page_view"}, ["x"], "junk", {"sid": "a b", "type": "click", "page": "http://evil"},
])
def test_ingest_bad_payload_ignored(client, payload):
    c, app = client
    assert post(c, payload).status_code == 204
    rows = events(app, "bogus") + events(app, "page_view")
    assert rows == []
    # bad sid / page are sanitized rather than stored
    for r in events(app, "click"):
        assert r["session_id"] is None and r["page"] is None


def test_ingest_invalid_json_and_oversize(client):
    c, app = client
    assert c.post("/analytics/event", data="{not json").status_code == 204
    big = dict(GOOD, target="x" * 10000)
    assert post(c, big).status_code == 204
    assert events(app, "click") == []


def test_rate_limit(client):
    c, app = client
    for _ in range(150):
        assert post(c, GOOD).status_code == 204
    assert len(events(app, "click")) == 120


def test_dnt_ignored(client):
    c, app = client
    assert post(c, GOOD, headers={"DNT": "1"}).status_code == 204
    c.get("/profile", headers={"DNT": "1"})
    assert events(app) == []


def test_server_page_view_and_exclusions(client):
    c, app = client
    c.get("/profile")
    c.get("/analytics")
    c.get("/static/css/style.css")
    pv = events(app, "page_view")
    assert [e["page"] for e in pv] == ["/profile"]
    assert pv[0]["duration_ms"] is not None


def test_chat_text_never_stored(client, monkeypatch):
    c, app = client
    import app.web.routes as r

    class Fake:
        def ask_coach(self, **kw):
            return "ok"
    monkeypatch.setattr(r, "GeminiCLIWrapper", Fake)
    secret = "my knee hurts SECRET-TEXT-123 about sleep"
    assert c.post("/chat", json={"question": secret}).status_code == 200
    ev = events(app, "chat_question")
    assert len(ev) == 1
    props = json.loads(ev[0]["props_json"])
    assert props["length"] == len(secret) and props["topic"] in ("sleep_recovery", "load_safety")
    conn = get_db_connection(app.config["_db"])
    dump = json.dumps([tuple(row) for row in conn.execute("SELECT * FROM analytics_events")])
    conn.close()
    assert "SECRET-TEXT-123" not in dump


def test_topic_bucket():
    assert topic_bucket("how is my sleep") == "sleep_recovery"
    assert topic_bucket("hello") == "other"


def test_plan_and_strength_events(client):
    c, app = client
    c.post("/plan/generate")
    c.post("/plan/discard")
    assert len(events(app, "plan_generated")) == 1
    assert any(e["target"] == "plan_discard" for e in events(app, "feature_used"))


def seed(app):
    for et, page, tgt, props, dur, sid in [
        ("page_view", "/", None, None, 20, None),
        ("page_view", "/", None, None, 30, None),
        ("page_view", "/plan", None, None, 10, None),
        ("page_load_ms", "/", None, None, 100, "sess1234"),
        ("page_load_ms", "/", None, None, 300, "sess5678"),
        ("sync_finished", "/sync", None, {"status": "success"}, 2000, None),
        ("sync_finished", "/sync", None, {"status": "failed"}, 4000, None),
        ("plan_generated", "/plan/generate", None, None, None, None),
        ("session_logged", "/session/update", None, None, None, None),
        ("error", "/plan", "boom", {"message": "boom"}, None, "sess1234"),
    ]:
        store.insert_event(app.config["_db"], et, page=page, target=tgt, props=props,
                           duration_ms=dur, session_id=sid)


def test_dashboard_aggregation(client):
    c, app = client
    seed(app)
    s = store.summarize(app.config["_db"], 30)
    k = s["kpis"]
    assert k["sessions"] == 2 and k["page_views"] == 3 and k["errors"] == 1
    assert k["sync_success_rate"] == 50 and k["avg_sync_s"] == 3.0
    assert k["avg_page_load_ms"] == 200
    assert [f["count"] for f in s["funnel"]] == [2, 1, 1, 1]
    assert s["pages"][0]["page"] == "/" and s["pages"][0]["views"] == 2
    assert s["recent_errors"][0]["message"] == "boom"
    assert len(s["daily"]) == 30
    r = c.get("/analytics?days=7")
    assert r.status_code == 200 and b"USAGE ANALYTICS" in r.data and b"boom" in r.data
    assert c.get("/analytics?days=999").status_code == 200


def test_export_and_delete(client):
    c, app = client
    seed(app)
    csv_resp = c.get("/analytics/export.csv")
    assert csv_resp.mimetype == "text/csv"
    assert csv_resp.data.decode().splitlines()[0].startswith("id,ts,session_id,event_type")
    assert len(csv_resp.data.decode().strip().splitlines()) == 11
    assert len(json.loads(c.get("/analytics/export.json").data)) == 10
    assert c.post("/analytics/delete").status_code == 302
    assert events(app) == []
    assert c.get("/analytics/delete").status_code == 405


def test_optout_and_client_script(client):
    c, app = client
    c.get("/profile?analytics=off")
    assert events(app) == []
    html = c.get("/profile?analytics=off").data.decode()
    assert "js/analytics.js" in html and 'href="/analytics"' in html
    js = c.get("/static/js/analytics.js").data.decode()
    assert "analytics_optout" in js and "doNotTrack" in js and "sessionStorage" in js
    assert "document.cookie" not in js and ".value" not in js


def test_retention_prune(tmp_path):
    db = str(tmp_path / "r.db")
    store.init_schema(db)
    conn = get_db_connection(db)
    conn.execute("INSERT INTO analytics_events (ts, event_type) VALUES ('2000-01-01T00:00:00.000000Z','click')")
    conn.execute("INSERT INTO analytics_events (ts, event_type) VALUES (?, 'click')", (store.utc_now(),))
    conn.commit()
    conn.close()
    store.init_schema(db)
    assert len(store.all_events(db)) == 1
