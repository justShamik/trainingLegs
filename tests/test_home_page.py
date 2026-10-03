"""Home page (/): greeting shell, sync panel per token state, today dials, races, redirects."""
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from app.data.db import get_db_connection, init_db
from app.data.sync import save_activity, save_daily_activity, save_sleep_record
from app.mcp_client import coros_client
from app.races import service as race_service
from app.web.routes import create_app, safe_next

TOKENS = {
    "connected": {"is_authenticated": True, "token_exists": True, "status_code": "CONNECTED",
                  "message": "COROS Account Authenticated & Token Valid", "expires_at": "2026-12-31T00:00:00Z"},
    "expired": {"is_authenticated": False, "token_exists": True, "status_code": "TOKEN_EXPIRED",
                "message": "COROS Token expired or invalid. Please re-authenticate.", "expires_at": None},
    "disconnected": {"is_authenticated": False, "token_exists": False, "status_code": "NOT_CONNECTED",
                     "message": "COROS token missing. Browser authentication required."},
}


def _race(**kw):
    base = {
        "id": "r1", "name": "Test Trail 50K", "distance_km": 50.0, "location": "Gurugram, Haryana",
        "category": "watchlist", "is_watchlist": True, "event_date": "2026-12-13",
        "event_date_display": "13 Dec 2026", "event_date_text": "Sun 13 Dec 2026", "edition_year": 2026,
        "edition_passed": False, "days_until_event": 71, "status": "open", "status_label": "Registration open",
        "status_source": "seed", "confidence": None, "registration_opens": None,
        "registration_opens_display": None, "registration_closes": "2026-11-30",
        "registration_closes_display": "30 Nov 2026",
        "last_registration_closed": {"date": "2025-11-25", "date_display": "25 Nov 2025", "edition_year": 2025,
                                     "source": "https://example.org/faq", "text": "x"},
        "last_checked_at": None, "last_ok_at": None, "status_changed_at": None, "evidence": None,
        "evidence_url": None, "scan_error": None, "source_url": "https://example.org/race",
        "registration_url": None, "notes": None,
    }
    base.update(kw)
    return base


FAKE_RACES = {
    "as_of": "2026-10-03",
    "races": [],
    "watchlist": [
        _race(),
        _race(id="r2", name="Closed Desert Ultra", status="closed", status_label="Registration closed",
              registration_opens_display="15 Sep 2026", registration_closes_display=None,
              last_checked_at="2026-10-02T10:00:00Z", evidence="Registrations are SOLD OUT"),
        _race(id="r3", name="Someday Marathon", status="not_started", status_label="Registration not started",
              event_date=None, days_until_event=None, event_date_text="Sep 2027, dates not announced",
              last_registration_closed=None),
        _race(id="r4", name="Mystery Run", status="unknown", status_label="Status unknown"),
    ],
    "ncr_50k": [_race(id="n1", name="Aravalli Night 50K", category="ncr_50k", is_watchlist=False,
                      last_registration_closed=None)],
    "last_checked_at": None,
    "needs_refresh": True,
}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "home.db")
    init_db(path)
    return path


@pytest.fixture
def token(monkeypatch):
    state = {"value": TOKENS["connected"]}
    monkeypatch.setattr(coros_client.CorosMCPClient, "validate_token_status", lambda self: dict(state["value"]))
    monkeypatch.setattr(coros_client.CorosMCPClient, "trigger_login_flow", lambda self: True)
    return state


@pytest.fixture
def races(monkeypatch):
    calls = {"refresh": 0, "get": 0}

    def fake_get(db_path=None, today=None, seed_path=None):
        calls["get"] += 1
        return FAKE_RACES

    def fake_refresh(db_path=None, fetch=None, seed_path=None, race_ids=None, **kw):
        calls["refresh"] += 1
        return {"checked": 5, "changed": 1, "errors": 2, "results": []}

    monkeypatch.setattr(race_service, "get_races_for_home", fake_get)
    monkeypatch.setattr(race_service, "refresh_races", fake_refresh)
    return calls


@pytest.fixture
def client(db, token, races):
    app = create_app(db_path=db)
    app.testing = True
    return app.test_client()


def _dial_values(html):
    return re.findall(r'class="dial__value">(.*?)</span>\s*<span class="dial__label">(.*?)</span>', html, re.S)


def _text(fragment):
    return re.sub(r"<[^>]+>", "", fragment).strip()


# ------------------------------------------------------------------------------- rendering
def test_home_renders_with_empty_db(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="homeGreeting"' in html and ">Hello<" in html  # no-JS neutral fallback
    vals = {label: _text(v) for v, label in _dial_values(html)}
    assert vals == {"Sleep": "—", "Activity time": "—", "Steps": "—", "Calories": "—"}
    assert "Not synced yet today" in html
    assert 'data-pct="0"' in html
    assert "Never" in html  # last sync
    assert "No sync attempts yet" in html


def test_home_nav_has_home_first_and_active(client):
    html = client.get("/").get_data(as_text=True)
    links = re.findall(r'<a href="([^"]+)" class="nav-link([^"]*)">([^<]+)</a>', html)
    assert links[0][2] == "Home" and links[0][0] == "/" and "active" in links[0][1]
    assert links[1][2] == "Dashboard" and links[1][0] == "/dashboard"
    assert 'class="nav-brand"' in html and '<a href="/" class="nav-brand"' in html


def test_home_dials_show_real_values(client, db):
    day = date.today().isoformat()
    conn = get_db_connection(db)
    save_sleep_record({"id": f"s_{day}", "date": day, "total_sleep_minutes": 452, "deep_sleep_minutes": 80,
                       "light_sleep_minutes": 250, "rem_sleep_minutes": 102, "awake_minutes": 20}, conn)
    save_daily_activity({"date": day, "steps": 8421, "calories_kcal": 1850.0, "exercise_minutes": 42.0}, conn)
    save_activity({"id": "a1", "date": f"{day}T12:00:00", "sport_type": "Run", "name": "Lunch run",
                   "distance_m": 8000.0, "duration_s": 2880.0}, conn)
    conn.commit()
    conn.close()
    html = client.get("/").get_data(as_text=True)
    vals = {label: _text(v) for v, label in _dial_values(html)}
    assert vals["Sleep"] == "7:32h"
    assert vals["Activity time"] == "48min"
    assert vals["Steps"] == "8,421"
    assert vals["Calories"] == "1,850kcal"
    assert "1 activity" in html
    assert "Goal 8:00 h" in html and "Goal 10,000" in html
    assert 'data-pct="94' in html  # sleep 452/480
    assert "Not synced yet today" not in html


@pytest.mark.parametrize("state,pill,locked", [
    ("connected", "Token valid", False),
    ("expired", "Token expired — reconnect", True),
    ("disconnected", "COROS not connected", True),
])
def test_sync_panel_per_token_state(client, token, state, pill, locked):
    token["value"] = TOKENS[state]
    html = client.get("/").get_data(as_text=True)
    assert f'data-state="{state}"' in html
    assert pill in html
    pending = re.search(r'<button[^>]*id="homeSyncPendingBtn"[^>]*>', html).group(0)
    full = re.search(r'<button[^>]*id="homeSyncFullBtn"[^>]*>', html).group(0)
    assert ("disabled" in pending) is locked and ("disabled" in full) is locked
    assert ('id="homeConnectBtn"' in html) is locked
    if state == "connected":
        assert 'data-utc="2026-12-31T00:00:00Z"' in html  # token expiry localised in browser
    if state == "expired":
        assert "token has expired" in html


def test_last_sync_is_localised_via_data_utc(client, db):
    conn = get_db_connection(db)
    conn.execute("INSERT INTO sync_logs (timestamp, sync_type, status, records_fetched, duration_ms)"
                 " VALUES ('2026-10-03 01:15:00', 'INCREMENTAL', 'SUCCESS', 3, 100)")
    conn.commit()
    conn.close()
    html = client.get("/").get_data(as_text=True)
    assert 'id="homeLastSync" class="num" data-utc="2026-10-03T01:15:00Z"' in html
    assert "Succeeded" in html and "incremental" in html


def test_races_section(client):
    html = client.get("/").get_data(as_text=True)
    cards = re.findall(r'<article class="card race-card" data-race-id="([^"]+)" data-status="([^"]+)">', html)
    assert cards == [("r1", "open"), ("r2", "closed"), ("r3", "not_started"), ("r4", "unknown"), ("n1", "open")]
    assert "50K near Delhi NCR (Nov–Jan)" in html
    assert 'chip chip--mint race-card__status">Registration open' in html
    assert 'chip chip--rose race-card__status">Registration closed' in html
    assert 'chip chip--butter race-card__status">Registration not started' in html
    assert 'chip chip--neutral race-card__status">Status unknown' in html
    assert "in 71 days" in html and "50 km" in html
    assert "Registration closes" in html and "30 Nov 2026" in html
    assert "Registration opens" in html and "15 Sep 2026" in html
    assert "Last registration closed" in html and "25 Nov 2025 (2025 edition)" in html
    assert 'href="https://example.org/race" class="link-arrow race-card__source" target="_blank" rel="noopener noreferrer"' in html
    assert "Registrations are SOLD OUT" in html
    assert 'data-utc="2026-10-02T10:00:00Z"' in html
    assert 'id="raceRefreshHint"' in html  # needs_refresh -> subtle hint
    assert 'action="/races/refresh"' in html and "Check race websites now" in html


def test_home_does_not_scan_races_on_load(client, races):
    client.get("/")
    assert races["refresh"] == 0 and races["get"] == 1


def test_home_survives_race_service_failure(client, monkeypatch):
    def boom(**kw):
        raise RuntimeError("seed missing")
    monkeypatch.setattr(race_service, "get_races_for_home", boom)
    res = client.get("/")
    assert res.status_code == 200
    assert "Race list unavailable" in res.get_data(as_text=True)


def test_races_refresh_post_redirects_home_with_message(client, races):
    res = client.post("/races/refresh")
    assert res.status_code == 302 and races["refresh"] == 1
    loc = urlsplit(res.headers["Location"])
    assert loc.path == "/" and loc.fragment == "races"
    q = parse_qs(loc.query)
    assert q["race_status"] == ["success"]
    assert "Checked 5 race websites" in q["race_msg"][0] and "2 sites could not be read" in q["race_msg"][0]
    html = client.get(res.headers["Location"]).get_data(as_text=True)
    assert "Race check:" in html and "Checked 5 race websites" in html
    assert 'id="raceRefreshHint"' not in html  # message replaces the hint


def test_races_refresh_failure_is_reported_not_500(client, monkeypatch):
    def boom(**kw):
        raise OSError("network down")
    monkeypatch.setattr(race_service, "refresh_races", boom)
    res = client.post("/races/refresh")
    assert res.status_code == 302
    assert parse_qs(urlsplit(res.headers["Location"]).query)["race_status"] == ["error"]


def test_races_refresh_requires_post(client):
    assert client.get("/races/refresh").status_code == 405


# ------------------------------------------------------------------------------- redirects
def _fake_sync(monkeypatch):
    import app.web.routes as routes
    monkeypatch.setattr(routes, "perform_sync", lambda full=False, db_path=None: (True, 3, "Sync done", 0.1))


def test_sync_without_next_returns_home(client, monkeypatch):
    _fake_sync(monkeypatch)
    res = client.post("/sync", data={"full": "0"})
    loc = urlsplit(res.headers["Location"])
    assert loc.path == "/" and parse_qs(loc.query)["sync_status"] == ["success"]
    html = client.get(res.headers["Location"]).get_data(as_text=True)
    assert "Sync Result:" in html and "Sync done" in html


def test_sync_next_returns_to_dashboard_and_replaces_old_result(client, monkeypatch):
    _fake_sync(monkeypatch)
    res = client.post("/sync", data={"full": "1", "next": "/dashboard?days=7&sync_msg=old&sync_status=error"})
    loc = urlsplit(res.headers["Location"])
    q = parse_qs(loc.query)
    assert loc.path == "/dashboard" and q["days"] == ["7"]
    assert q["sync_msg"] == ["Sync done"] and q["sync_status"] == ["success"]


@pytest.mark.parametrize("evil", [
    "https://evil.example/", "//evil.example/x", "/\\evil.example", "javascript:alert(1)",
    "http:/evil", "evil.example", "/ok\r\nSet-Cookie: x=1",
])
def test_sync_and_login_reject_external_next(client, monkeypatch, evil):
    _fake_sync(monkeypatch)
    for url in ("/sync", "/coros/login"):
        res = client.post(url, data={"next": evil})
        loc = res.headers["Location"]
        assert urlsplit(loc).netloc in ("", "localhost") and urlsplit(loc).path == "/", (url, evil, loc)


def test_login_returns_to_submitting_page(client):
    res = client.post("/coros/login", data={"next": "/plan"})
    assert urlsplit(res.headers["Location"]).path == "/plan"


def test_safe_next_helper():
    assert safe_next("/dashboard?days=7") == "/dashboard?days=7"
    assert safe_next(None) == "/" and safe_next("") == "/"
    assert safe_next("//x.com", "/home") == "/home"


def test_forms_carry_next_field(client, token):
    html = client.get("/dashboard?days=7").get_data(as_text=True)
    assert html.count('name="next" value="/dashboard?days=7"') >= 2  # both dashboard sync forms
    assert 'id="syncPendingBtn"' in html and 'id="syncFullBtn"' in html
    token["value"] = TOKENS["disconnected"]
    html = client.get("/plan").get_data(as_text=True)
    assert 'name="next" value="/plan"' in html  # navbar connect button


def test_dashboard_moved_and_links_updated(client):
    html = client.get("/dashboard").get_data(as_text=True)
    assert "TRAINING DASHBOARD" in html
    assert 'href="/dashboard?days=7"' in html
    detail_404 = client.get("/activity/nope").get_data(as_text=True)
    assert 'href="/dashboard"' in detail_404 and "Return to Dashboard" in detail_404
