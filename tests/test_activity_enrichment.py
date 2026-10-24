"""Tests for activity detail enrichment (lap/detail parsing, sync enrichment) and navbar auth badge."""
import json
import os
import pytest
from app.mcp_client.coros_client import CorosMCPClient
from app.data.db import init_db, get_db_connection
from app.data.sync import save_activity, enrich_running_activities, perform_sync
from app.web.routes import create_app

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_parse_lap_data_real_output():
    d = CorosMCPClient()._parse_lap_data(_read("coros_lap_data_run.json"))
    assert d["avg_cadence"] == 176
    assert d["stride_length_cm"] == 90.0
    assert d["avg_power_w"] == 224.0
    assert d["gap_s_km"] == 378.0
    assert d["max_hr"] == 172
    assert d["elevation_gain_m"] == 4.0 and d["elevation_loss_m"] == 6.0
    assert 240 < d["ground_contact_time_ms"] < 300
    assert 75 < d["vertical_oscillation_mm"] < 95
    assert len(d["splits"]) >= 10
    assert d["splits"][0]["distance_m"] == pytest.approx(719.6, abs=0.1)


def test_parse_lap_data_never_fabricates_zero_metrics():
    data = json.loads(_read("coros_lap_data_run.json"))
    for g in data["lapGroups"]:
        for lap in g["laps"]:
            lap.update(groundTime=0, strideHeight=0, avgPower=0, avgCadence=0)
    d = CorosMCPClient()._parse_lap_data(json.dumps(data))
    for k in ("ground_contact_time_ms", "vertical_oscillation_mm", "avg_power_w", "avg_cadence"):
        assert k not in d


def test_parse_activity_detail_text_and_hybrid():
    c = CorosMCPClient()
    d = c._parse_activity_detail_text(_read("coros_activity_detail_run.txt"))
    assert d["avg_cadence"] == 176 and d["stride_length_cm"] == 90.0
    assert d["avg_power_w"] == 224.0 and d["gap_s_km"] == 378
    assert d["elevation_gain_m"] == 4.0 and d["elevation_loss_m"] == 6.0
    hybrid = c._parse_activity_detail_text(_read("coros_activity_detail_hybrid.txt"))
    assert "avg_cadence" not in hybrid and "avg_power_w" not in hybrid


def test_running_sport_code():
    assert CorosMCPClient.running_sport_code("Outdoor Run") == 100
    assert CorosMCPClient.running_sport_code("Indoor Run") == 101
    assert CorosMCPClient.running_sport_code("Trail Run") == 102
    assert CorosMCPClient.running_sport_code("Hybrid Fitness") is None


class FakeClient(CorosMCPClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _call_cli_tool(self, tool, args):
        self.calls.append((tool, args))
        if tool == "queryActivityLapData":
            return _read("coros_lap_data_run.json")
        return None


def _seed(db, n_runs=3):
    init_db(db)
    conn = get_db_connection(db)
    for i in range(n_runs):
        save_activity({"id": str(1000 + i), "date": f"2026-09-{10 + i}T08:00:00Z", "sport_type": "Outdoor Run",
                       "distance_m": 8000.0, "duration_s": 2900.0, "avg_hr": 150}, conn)
    save_activity({"id": "2000", "date": "2026-09-20T08:00:00Z", "sport_type": "Hybrid Fitness",
                   "distance_m": 0.0, "duration_s": 2400.0}, conn)
    conn.commit()
    conn.close()


def test_enrichment_populates_columns_caps_and_skips_hybrid(tmp_path):
    db = str(tmp_path / "e.db")
    _seed(db)
    client = FakeClient()
    assert enrich_running_activities(client, db, limit=2) == 2
    conn = get_db_connection(db)
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM activities")}
    assert rows["1002"]["avg_cadence"] == 176 and rows["1002"]["details_synced_at"]
    assert rows["1001"]["avg_power_w"] == 224.0
    assert rows["1000"]["details_synced_at"] is None  # over the cap, next sync
    assert rows["2000"]["details_synced_at"] is None and rows["2000"]["avg_cadence"] is None
    assert rows["1002"]["avg_hr"] == 150  # existing value kept (COALESCE)
    assert conn.execute("SELECT COUNT(*) FROM activity_splits WHERE activity_id='1002'").fetchone()[0] >= 10
    conn.close()
    # Second run only enriches what is left, and re-running does not duplicate splits
    assert enrich_running_activities(client, db, limit=15) == 1
    assert enrich_running_activities(client, db, limit=15) == 0


def test_enrichment_tolerates_failures_and_keeps_data(tmp_path):
    db = str(tmp_path / "f.db")
    _seed(db, 1)
    client = FakeClient()
    client._call_cli_tool = lambda tool, args: (client.call_failures.append(tool + ": boom"), None)[1]
    assert enrich_running_activities(client, db) == 0
    conn = get_db_connection(db)
    assert conn.execute("SELECT details_synced_at FROM activities WHERE id='1000'").fetchone()[0] is None
    conn.close()
    assert client.call_failures


def test_resync_summary_does_not_null_out_details(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db, 1)
    enrich_running_activities(FakeClient(), db)
    conn = get_db_connection(db)
    save_activity({"id": "1000", "date": "2026-09-10T08:00:00Z", "sport_type": "Outdoor Run",
                   "distance_m": 8000.0, "duration_s": 2900.0}, conn)
    conn.commit()
    row = conn.execute("SELECT avg_cadence, avg_power_w, details_synced_at FROM activities WHERE id='1000'").fetchone()
    conn.close()
    assert row["avg_cadence"] == 176 and row["avg_power_w"] == 224.0 and row["details_synced_at"]


def test_activity_page_shows_values_and_reasons(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, 2)
    enrich_running_activities(FakeClient(), db, limit=1)  # enrich only newest (1001)
    app = create_app(db)
    app.testing = True
    client = app.test_client()
    html = client.get("/activity/1001").get_data(as_text=True)
    assert "176" in html and "224" in html and "6:18 /km" in html
    html2 = client.get("/activity/1000").get_data(as_text=True)
    assert "Not Available" in html2 and "Detail data not synced yet" in html2


@pytest.mark.parametrize("path", ["/activity/1000", "/chat", "/profile", "/strength", "/plan?tab=history", "/zones"])
def test_navbar_badge_connected_on_all_pages(tmp_path, monkeypatch, path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "x"}), encoding="utf-8")
    monkeypatch.setattr("app.mcp_client.coros_client.CACHE_TOKEN_PATH", str(token))
    db = str(tmp_path / "n.db")
    _seed(db, 1)
    app = create_app(db)
    app.testing = True
    html = app.test_client().get(path).get_data(as_text=True)
    assert "COROS Connected" in html
    assert "Connect COROS Account" not in html


def test_navbar_badge_disconnected_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr("app.mcp_client.coros_client.CACHE_TOKEN_PATH", str(tmp_path / "missing.json"))
    monkeypatch.delenv("COROS_MCP_AUTH_TOKEN", raising=False)
    db = str(tmp_path / "d.db")
    _seed(db, 1)
    app = create_app(db)
    app.testing = True
    assert "Connect COROS Account" in app.test_client().get("/chat").get_data(as_text=True)
