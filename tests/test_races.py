"""Unit tests for app/races: seed loading, scanner signals, dates, persistence, home view, discovery.

No network: every fetch is injected.
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from app.races import store
from app.races.discover import candidates_from_html, discover_ncr_50k
from app.races.scanner import FetchResult, find_signals, scan_race
from app.races.service import (get_races_for_home, last_registration_closed, needs_refresh,
                               refresh_races, discover_candidates)
from app.races.textutil import extract_dates, parse_html
from app.races.watchlist import load_seed, merge_state

SEED = os.path.join(os.path.dirname(__file__), "fixtures", "race_watchlist_sample.json")
TODAY = date(2026, 10, 3)


def page(body: str) -> str:
    return f"<html><head><title>t</title><script>var x=1;</script></head><body>{body}</body></html>"


def race(status="unknown", urls=("https://x.test/a",)):
    return {"id": "r1", "name": "R1", "registration_status": status, "scrape_urls": list(urls)}


def fetch_map(mapping):
    def _fetch(url):
        v = mapping[url]
        if isinstance(v, Exception):
            raise v
        return v
    return _fetch


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "races.db")


# ------------------------------------------------------------------ seed
def test_load_seed_normalizes_and_skips_invalid():
    seed = load_seed(SEED)
    ids = [r["id"] for r in seed["races"]]
    assert seed["as_of"] == "2026-10-01"
    assert "ladakh-marathon-42" in ids and len(ids) == 5  # entry without id skipped
    auroville = next(r for r in seed["races"] if r["id"] == "auroville-marathon")
    assert auroville["registration_opens"] is None and auroville["registration_url"] is None
    assert auroville["sources"] == [] and auroville["notes"] == ""
    assert auroville["previous_registrations"][0]["opened"] is None


def test_load_seed_missing_file_is_empty(tmp_path):
    assert load_seed(str(tmp_path / "nope.json"))["races"] == []


def test_load_seed_bad_status_becomes_unknown(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"races": [{"id": "a", "name": "A", "registration_status": "maybe", "category": "x"}]}))
    r = load_seed(str(p))["races"][0]
    assert r["registration_status"] == "unknown" and r["category"] == "watchlist"


def test_merge_state_ignores_unknown_and_low_confidence():
    r = load_seed(SEED)["races"][0]  # seed not_started
    assert merge_state(r, {"status": "unknown", "confidence": "low"})["status"] == "not_started"
    assert merge_state(r, {"status": "open", "confidence": "low"})["status"] == "not_started"
    m = merge_state(r, {"status": "open", "confidence": "medium"})
    assert m["status"] == "open" and m["status_source"] == "scan"


# ------------------------------------------------------------------ dates
@pytest.mark.parametrize("text,iso", [
    ("on 12 September 2027.", "2027-09-12"),
    ("Sep 12, 2027", "2027-09-12"),
    ("12/09/2027", "2027-09-12"),
    ("12th Sept 2027", "2027-09-12"),
    ("1st of March, 2027", "2027-03-01"),
    ("2027-09-12", "2027-09-12"),
    ("September 12th 2027", "2027-09-12"),
    ("12.09.2027", "2027-09-12"),
])
def test_extract_date_variants(text, iso):
    assert [d["date"] for d in extract_dates(text)] == [iso]


def test_extract_dates_ignores_yearless_and_invalid():
    assert extract_dates("opens 12 September") == []
    assert extract_dates("31/02/2027") == []


# ------------------------------------------------------------------ html
def test_parse_html_skips_scripts_and_keeps_links():
    text, links, meta = parse_html(page('<p>Hello <b>runner</b></p><a href="https://t.test">Go</a><style>p{}</style>'))
    assert "var x" not in text and "Hello runner" in text
    assert links == [{"href": "https://t.test", "text": "Go"}] and meta["script_count"] == 1


# ------------------------------------------------------------------ signals
def scan_html(body, status="unknown"):
    return scan_race(race(status), fetch=lambda u: FetchResult(u, 200, page(body)), today=TODAY)


def test_signal_open():
    r = scan_html("<h2>Registrations are now open!</h2><a href='/r'>Register Now</a>")
    assert r.status == "open" and r.confidence == "high" and "open" in r.evidence.lower()


def test_signal_open_book_slot_medium():
    r = scan_html("<p>Hurry, book your slot for the 2027 edition</p>")
    assert r.status == "open" and r.confidence == "medium"


def test_signal_closed():
    r = scan_html("<div>Registrations closed. Thank you!</div><p>The 50K category is SOLD OUT</p>")
    assert r.status == "closed" and r.confidence == "high"


def test_signal_closed_with_date():
    r = scan_html("<p>Registration closed on 10 August 2026.</p>")
    assert r.status == "closed" and r.detected_dates[0]["date"] == "2026-08-10"


def test_signal_not_started_opens_on_date():
    r = scan_html("<p>Registrations open on 15th Jan 2027 at 10 AM.</p>")
    assert r.status == "not_started" and r.confidence == "high"
    assert r.detected_dates == [{"date": "2027-01-15", "raw": "15th Jan 2027", "kind": "opens", "url": "https://x.test/a"}]


def test_signal_not_started_soon():
    r = scan_html("<h3>Registrations opening soon</h3>")
    assert r.status == "not_started" and r.confidence == "medium"


def test_signal_coming_soon_is_weak():
    r = scan_html("<p>Coming soon</p>")
    assert r.status == "not_started" and r.confidence == "low"


def test_opens_on_past_date_is_not_not_started():
    r = scan_html("<p>Registrations opened on 1 March 2026.</p><p>Register now</p>")
    assert r.status == "open"


def test_closes_on_future_date_means_open():
    r = scan_html("<p>Registration closes on Nov 20, 2026</p>")
    assert r.status == "open" and r.detected_dates[0]["kind"] == "closes"


def test_platform_link_is_weak_open():
    sigs = find_signals("x", [{"href": "https://www.townscript.com/e/goa-ultra", "text": "Register here"}])
    assert sigs and sigs[0]["status"] == "open" and sigs[0]["strength"] == "weak"
    r = scan_html('<p>Details</p><a href="https://www.townscript.com/e/goa">Register</a>')
    assert r.status == "open" and r.confidence == "low"


def test_evidence_snippet_capped():
    r = scan_html("<p>" + "lorem ipsum " * 50 + "Registrations closed" + " dolor" * 60 + "</p>")
    assert r.evidence and len(r.evidence) <= 200 and "Registrations closed" in r.evidence


def test_conflicting_signals_keep_seed_low():
    r = scan_html("<p>Registrations are open</p><p>Registration closed</p>", status="not_started")
    assert r.conflict and r.status == "not_started" and r.confidence == "low"


def test_no_signal_is_unknown():
    r = scan_html("<p>" + "Welcome to the race. " * 20 + "</p>")
    assert r.status == "unknown" and r.error is None


# ------------------------------------------------------------------ errors
def test_network_error_unknown():
    r = scan_race(race("open"), fetch=fetch_map({"https://x.test/a": ConnectionError("boom")}))
    assert r.status == "unknown" and "boom" in r.error


def test_blocked_and_js_pages():
    r = scan_race(race(), fetch=lambda u: FetchResult(u, 403, "<html>Access denied</html>"))
    assert r.status == "unknown" and "blocked" in r.error and r.http_status == 403
    js = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'
    r = scan_race(race(), fetch=lambda u: (200, js))
    assert r.status == "unknown" and "JavaScript" in r.error


def test_partial_failure_still_classifies():
    f = fetch_map({"https://x.test/a": ConnectionError("down"),
                   "https://x.test/b": FetchResult("https://x.test/b", 200, page("<p>Registrations closed</p>"))})
    r = scan_race(race(urls=("https://x.test/a", "https://x.test/b")), fetch=f)
    assert r.status == "closed" and "down" in r.error


def test_no_urls():
    r = scan_race({"id": "z", "name": "Z", "scrape_urls": []}, fetch=lambda u: 1 / 0)
    assert r.status == "unknown" and r.error == "no URLs to scan"


# ------------------------------------------------------------------ persistence
def _all_open(url):
    return FetchResult(url, 200, page("<p>Registrations are now open. Register now!</p>"))


def test_refresh_persists_and_upserts(db):
    s = refresh_races(db_path=db, fetch=_all_open, seed_path=SEED)
    assert s["checked"] == 4  # ncr-past-50k has no URLs -> skipped
    # ladakh seed not_started -> open = changed; goa + delhi already open; auroville seed unknown
    assert s["changed"] == 1 and s["errors"] == 0
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT race_id, status, confidence, checked_at FROM race_watch_status").fetchall()
    assert len(rows) == 4 and all(r[1] == "open" for r in rows)
    s2 = refresh_races(db_path=db, fetch=_all_open, seed_path=SEED)
    assert s2["changed"] == 0
    assert conn.execute("SELECT COUNT(*) FROM race_watch_status").fetchone()[0] == 4
    conn.close()


def test_refresh_network_error_does_not_clobber(db):
    refresh_races(db_path=db, fetch=_all_open, seed_path=SEED, race_ids=["ladakh-marathon-42"])

    def boom(url):
        raise TimeoutError("timed out")
    s = refresh_races(db_path=db, fetch=boom, seed_path=SEED, race_ids=["ladakh-marathon-42"])
    assert s["errors"] == 1 and s["changed"] == 0
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM race_watch_status WHERE race_id='ladakh-marathon-42'").fetchone()
    conn.close()
    assert row["status"] == "open" and row["confidence"] == "high" and "timed out" in row["error"]
    assert row["evidence"] and "open" in row["evidence"].lower()
    home = get_races_for_home(db_path=db, today=TODAY, seed_path=SEED)
    ladakh = next(r for r in home["races"] if r["id"] == "ladakh-marathon-42")
    assert ladakh["status_label"] == "Registration open" and ladakh["scan_error"]


def test_unknown_scan_on_fresh_row_keeps_seed_status(db):
    refresh_races(db_path=db, fetch=lambda u: 1 / 0, seed_path=SEED, race_ids=["goa-river-ultra"])
    home = get_races_for_home(db_path=db, today=TODAY, seed_path=SEED)
    goa = next(r for r in home["races"] if r["id"] == "goa-river-ultra")
    assert goa["status"] == "open" and goa["status_source"] == "seed" and goa["last_checked_at"]


def test_weak_scan_does_not_replace_confident_row(db):
    refresh_races(db_path=db, fetch=_all_open, seed_path=SEED, race_ids=["goa-river-ultra"])
    refresh_races(db_path=db, fetch=lambda u: (200, page("<p>Coming soon</p>")), seed_path=SEED,
                  race_ids=["goa-river-ultra"])
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status, confidence FROM race_watch_status").fetchone() == ("open", "high")
    conn.close()


def test_init_db_creates_race_table(db):
    from app.data.db import init_db
    init_db(db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(race_watch_status)")}
    conn.close()
    assert {"race_id", "status", "confidence", "evidence", "detected_dates", "http_status", "error", "checked_at"} <= cols


# ------------------------------------------------------------------ home view
def test_home_sorting_and_past_filter(db):
    home = get_races_for_home(db_path=db, today=TODAY, seed_path=SEED)
    ids = [r["id"] for r in home["races"]]
    assert "ncr-past-50k" not in ids
    assert ids == ["ncr-upcoming-50k", "goa-river-ultra", "ladakh-marathon-42", "auroville-marathon"]
    assert [r["id"] for r in home["ncr_50k"]] == ["ncr-upcoming-50k"]
    assert len(home["watchlist"]) == 3
    goa = home["races"][1]
    assert goa["days_until_event"] == (date(2026, 12, 6) - TODAY).days
    assert goa["status_label"] == "Registration open" and goa["registration_closes"] == "2026-11-20"
    ladakh = home["races"][2]
    assert ladakh["status_label"] == "Registration not started"
    assert home["races"][3]["days_until_event"] is None
    assert home["races"][3]["status_label"] == "Status unknown"
    assert home["needs_refresh"] is True


def test_home_keeps_watchlist_race_whose_edition_passed(db):
    home = get_races_for_home(db_path=db, today=date(2026, 12, 10), seed_path=SEED)
    goa = next(r for r in home["races"] if r["id"] == "goa-river-ultra")
    assert goa["edition_passed"] and goa["event_date"] is None and goa["status"] == "unknown"
    assert "not announced" in goa["event_date_text"]
    assert "ncr-upcoming-50k" not in [r["id"] for r in home["races"]]


def test_last_registration_closed_selection():
    seed = load_seed(SEED)
    ladakh = seed["races"][0]
    lrc = last_registration_closed(ladakh["previous_registrations"])
    assert lrc["date"] == "2026-08-10" and lrc["edition_year"] == 2026
    assert "2026 edition" in lrc["text"]
    assert last_registration_closed([]) is None
    assert last_registration_closed([{"edition_year": 2024, "closed": None}]) is None


def test_needs_refresh(db):
    assert needs_refresh(db_path=db, seed_path=SEED) is True
    refresh_races(db_path=db, fetch=_all_open, seed_path=SEED)
    assert needs_refresh(db_path=db, seed_path=SEED) is False
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert needs_refresh(db_path=db, seed_path=SEED, now=later) is True


# ------------------------------------------------------------------ discovery
LISTING = """
<html><body>
<div class="card"><a href="/events/aravalli-50k">Aravalli Trail Run 50K</a>
  <p>Gurugram, Haryana</p><p>Sun, 14 Dec 2026</p></div>
<div class="card"><a href="/events/mumbai-50k">Mumbai Coastal 50 km</a><p>Mumbai</p><p>14 Dec 2026</p></div>
<div class="card"><a href="/events/noida-hm">Noida Half Marathon 21.1 km</a><p>Noida</p><p>Nov 2026</p></div>
<div class="card"><a href="/events/delhi-50k-apr">Delhi Spring 50K</a><p>New Delhi</p><p>12 April 2027</p></div>
<div class="card"><a href="https://ext.test/sohna">Sohna Hills 50 KM Ultra</a><p>Sohna, NCR</p><p>January 2027</p></div>
</body></html>
"""


def test_discovery_filter():
    c = candidates_from_html(LISTING, "https://list.test/races")
    names = [x["name"] for x in c]
    assert names == ["Aravalli Trail Run 50K", "Sohna Hills 50 KM Ultra"]
    assert c[0]["url"] == "https://list.test/events/aravalli-50k" and c[0]["date"] == "2026-12-14"
    assert c[1]["url"] == "https://ext.test/sohna" and c[1]["date"] is None and "January" in c[1]["date_text"]
    assert all(x["unverified"] for x in c)


def test_discover_ncr_50k_injected_fetch_and_errors():
    report = []
    f = fetch_map({"https://a.test": (200, LISTING), "https://b.test": ConnectionError("x")})
    c = discover_ncr_50k(fetch=f, urls=["https://a.test", "https://b.test"], report=report)
    assert len(c) == 2
    assert report[1]["error"] and report[0]["found"] == 2


def test_discover_candidates_excludes_watchlist(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"races": [{"id": "a", "name": "Aravalli Trail Run 50K", "category": "ncr_50k"}]}))
    import app.races.discover as d
    monkeypatch.setattr(d, "DEFAULT_LISTING_URLS", ["https://a.test"])
    monkeypatch.setattr(d, "listing_urls_from_research", lambda *a, **k: [])
    c = discover_candidates(fetch=lambda u: (200, LISTING), seed_path=str(p))
    assert [x["name"] for x in c] == ["Sohna Hills 50 KM Ultra"]


# ------------------------------------------------------------------ scanner rules (false "open" hardening)
LADAKH_HTML = page(
    '<nav><a href="/sign-up/">Register Now</a></nav>'
    "<p>Registration Closed</p><p>Registration Closed</p>"
    "<p>Registrations for the 14th edition of the Ladakh Marathon will open on Monday 19 <sup>th</sup> "
    "January 2027 and close on 31 <sup>st</sup> July 2027.</p>")

KONFHUB_SOLD_OUT = (
    '<html><body><h1>THE BORDER 2026</h1><a href="#">Register now</a><script id="__NEXT_DATA__">{"tickets":['
    '{"ticket_name":"100 MILES - THE BATTLEFRONT","start_timestamp":"2026-07-01 06:30:00",'
    '"end_timestamp":"2026-12-20 10:30:00","hidden_ticket":false,"sold_out":false},'
    '{"ticket_name":"50 KM - THE FRONTLINE DASH","start_timestamp":"2026-07-01 06:30:00",'
    '"end_timestamp":"2026-12-20 10:30:00","hidden_ticket":false,"sold_out":true}]}</script></body></html>')
NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def _ladakh(**rules):
    return {"id": "ladakh", "name": "Ladakh", "registration_status": "not_started",
            "scrape_urls": ["https://ladakhmarathon.com/race-information/"], **rules}


def test_ladakh_year_round_register_now_is_ignored():
    f = lambda u: (200, page('<nav><a href="/sign-up/">Register Now</a></nav><p>' + "Info. " * 60 + "</p>"))
    r = scan_race(_ladakh(ignore_phrases=["register now"]), fetch=f, today=TODAY)
    assert r.status == "unknown"  # nothing left after the ignored nav button -> seed kept on merge
    unruled = scan_race(_ladakh(), fetch=f, today=TODAY)
    assert unruled.status == "open"  # demonstrates why the rule is needed


def test_ladakh_full_page_stays_not_started():
    r = scan_race(_ladakh(ignore_phrases=["register now"]), fetch=lambda u: (200, LADAKH_HTML), today=TODAY)
    assert r.status == "not_started" and r.confidence in ("high", "medium")
    assert any(d["date"] == "2027-01-19" and d["kind"] == "opens" for d in r.detected_dates)


def test_ladakh_seed_rules_via_refresh(db, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"races": [{"id": "ladakh", "name": "Ladakh", "registration_status": "not_started",
                                        "ignore_phrases": ["register now"], "category": "watchlist",
                                        "scrape_urls": ["https://ladakhmarathon.com/sign-up/"]}]}))
    f = lambda u: (200, page('<a href="/x">Register Now</a><p>' + "Info. " * 60 + "</p>"))
    refresh_races(db_path=db, fetch=f, seed_path=str(p))
    home = get_races_for_home(db_path=db, today=TODAY, seed_path=str(p))
    assert home["races"][0]["status_label"] == "Registration not started"


def test_konfhub_sold_out_beats_register_now():
    border = {"id": "border", "name": "The Border", "registration_status": "closed",
              "ignore_phrases": ["register now"], "trusted_urls": ["https://konfhub.com/"],
              "ticket_filter": r"50\s*K|FRONTLINE",
              "scrape_urls": ["https://konfhub.com/the-border-2026", "https://thehellrace.com/the-border/"]}
    hell = page("<p>THE BORDER</p><a href='https://konfhub.com/the-border-2026'>REGISTER NOW</a>"
                "<p>Registrations are open</p>")
    f = fetch_map({"https://konfhub.com/the-border-2026": (200, KONFHUB_SOLD_OUT),
                   "https://thehellrace.com/the-border/": (200, hell)})
    r = scan_race(border, fetch=f, today=TODAY, now=NOW)
    assert r.status == "closed" and r.confidence == "high" and "sold out" in r.evidence
    # Even without any seed rules, ticket data outranks page text.
    plain = {**border, "ignore_phrases": [], "trusted_urls": [], "ticket_filter": r"50\s*K"}
    assert scan_race(plain, fetch=f, today=TODAY, now=NOW).status == "closed"
    # Without the ticket filter, an unsold 100-mile ticket makes the event "open".
    nofilter = {**plain, "ticket_filter": None}
    assert scan_race(nofilter, fetch=f, today=TODAY, now=NOW).status == "open"


def test_ticketing_windows():
    from app.races.scanner import ticketing_signals
    tpl = '{"ticket_name":"50K","start_timestamp":"%s","end_timestamp":"%s","sold_out":false}'
    future = tpl % ("2027-01-10 00:00:00", "2027-03-01 00:00:00")
    s = ticketing_signals(future, now=NOW)
    assert s[0]["status"] == "not_started" and s[0]["dates"][0] == {"date": "2027-01-10", "raw": "2027-01-10T00:00:00+00:00", "kind": "opens"}
    assert ticketing_signals(tpl % ("2026-01-01 00:00:00", "2026-02-01 00:00:00"), now=NOW)[0]["status"] == "closed"
    assert ticketing_signals(tpl % ("2026-09-01 00:00:00", "2026-11-01 00:00:00"), now=NOW)[0]["status"] == "open"
    assert ticketing_signals("<p>no tickets</p>", now=NOW) == []


def test_ignore_signals_and_trusted_tier():
    html = page("<p>Registrations are now open</p>")
    r = scan_race({**race("not_started"), "ignore_signals": ["open"]}, fetch=lambda u: (200, html), today=TODAY)
    assert r.status == "unknown"
    f = fetch_map({"https://off.test/a": (200, page("<p>Registration closed</p>")),
                   "https://agg.test/b": (200, page("<p>Registrations are now open</p>"))})
    base = {**race("open", urls=("https://off.test/a", "https://agg.test/b"))}
    assert scan_race(base, fetch=f, today=TODAY).conflict
    r = scan_race({**base, "trusted_urls": ["https://off.test/"]}, fetch=f, today=TODAY)
    assert r.status == "closed" and r.confidence == "high"


def test_new_date_and_close_phrasings():
    assert extract_dates("Monday 19 th January 2027")[0]["date"] == "2027-01-19"
    assert extract_dates("START: 06:00 AM, 07 Feb, 2027")[0]["date"] == "2027-02-07"
    r = scan_html("<p>Registration closes: Wednesday, October 28, 2026 23:59 (GMT+5:30)</p>")
    assert r.status == "open" and r.detected_dates[0]["date"] == "2026-10-28"
    r = scan_html("<p>Registration Open</p><p>Registrations close 24th Oct 2026 or earlier if slots fill</p>")
    assert r.status == "open" and r.confidence == "high"


def test_real_seed_loads_with_rules():
    seed = load_seed()
    if not seed["races"]:
        pytest.skip("real seed not present")
    by_id = {r["id"]: r for r in seed["races"]}
    assert "register now" in by_id["ladakh-marathon-42k"]["ignore_phrases"]
    assert by_id["hell-race-the-border-50k"]["ticket_filter"]


def test_previous_edition_closed_does_not_flip_next_edition():
    html = page("<p>Thursday 10 September 2026 Silk Route Ultra 122 Km Registration Closed</p>"
                "<p>Full Marathon Registration Closed</p>" + "<p>Route info.</p>" * 30)
    r = scan_race(_ladakh(ignore_phrases=["register now"], edition_year=2027), fetch=lambda u: (200, html), today=TODAY)
    assert r.status == "unknown"
    # same page while tracking an already-open edition -> closed is a real change
    r = scan_race({**_ladakh(edition_year=2026), "registration_status": "open"}, fetch=lambda u: (200, html), today=TODAY)
    assert r.status == "closed"


def test_konfhub_page_with_no_visible_text_still_reads_tickets():
    html = ('<html><body><div id="__next"></div><script>window.__D={"ticket_name":"50 KM",'
            '"start_timestamp":"2026-07-01 06:30:00","end_timestamp":"2026-12-20 10:30:00","sold_out":true}'
            '</script></body></html>')
    r = scan_race(race("open", urls=("https://konfhub.com/x",)), fetch=lambda u: (200, html), now=NOW)
    assert r.status == "closed" and r.error is None
