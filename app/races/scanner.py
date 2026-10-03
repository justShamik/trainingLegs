"""Scan a race's web pages for registration-status signals.

Conservative by design:
  * only explicit phrases count; dates are only reported if literally present (with a year);
  * conflicting strong signals -> keep the seed status at low confidence;
  * fetch failures / blocked / JS-only pages -> status "unknown" with the error noted (callers never
    let "unknown" overwrite a known status).
All network access goes through an injectable ``fetch(url)`` callable.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from app.races.textutil import extract_dates, parse_html, snippet

logger = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
DEFAULT_TIMEOUT = 10
DEFAULT_RACE_BUDGET_S = 30.0
MAX_BYTES = 2_000_000

# Hosts of ticketing/registration platforms commonly used by Indian races.
REGISTRATION_PLATFORMS = (
    "townscript.com", "ifinish.in", "myraceindia.com", "youtoocanrun.com", "bookmyshow.com",
    "allevents.in", "indiarunning.com", "raceregistrations.in", "procamrunning.in", "eventbrite.",
    "insider.in", "konfhub.com", "sportskeeda", "timingindia.com", "hipcask", "zomato.com/events",
)


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int] = None
    text: str = ""
    error: Optional[str] = None


def http_fetch(url: str, timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    """Single read-only GET (no retries) with a browser User-Agent and a size cap."""
    import requests
    try:
        resp = requests.get(url, timeout=timeout, stream=True, allow_redirects=True, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BYTES:
                break
        resp.close()
        enc = resp.encoding or "utf-8"
        if enc.lower() == "iso-8859-1":  # requests' default when header lacks charset
            enc = "utf-8"
        return FetchResult(url, resp.status_code, b"".join(chunks).decode(enc, errors="replace"))
    except Exception as exc:  # requests.RequestException and decoding issues
        return FetchResult(url, None, "", f"{type(exc).__name__}: {exc}"[:300])


def _coerce(url: str, raw: Any) -> FetchResult:
    """Accept FetchResult, requests-like objects, (status, text) tuples or plain strings from fetch()."""
    if isinstance(raw, FetchResult):
        return raw
    if isinstance(raw, str):
        return FetchResult(url, 200, raw)
    if isinstance(raw, tuple) and len(raw) == 2:
        return FetchResult(url, raw[0], raw[1] or "")
    return FetchResult(url, getattr(raw, "status_code", None), getattr(raw, "text", "") or "",
                       getattr(raw, "error", None))


# ------------------------------------------------------------------ signal patterns
_REG = r"registrations?"
# (status, strength, kind, regex). kind drives date handling.
_PATTERNS = [
    ("not_started", "strong", "opens_on", rf"\b{_REG}\s+(?:will\s+)?(?:open(?:s|ing)?|go(?:es)?\s+live|start(?:s|ing)?|begin(?:s|ning)?)\s+(?:on|from)\b"),
    # "Registrations for the 14th edition of the Ladakh Marathon will open on <date>"
    ("not_started", "strong", "opens_on", rf"\b{_REG}\s+for\s+[^.\n]{{0,80}}?\bwill\s+(?:open|start|begin)\s+(?:on|from)\b"),
    ("not_started", "strong", "soon", rf"\b{_REG}\s+(?:are\s+|is\s+)?(?:will\s+)?(?:open(?:s|ing)?|start(?:s|ing)?)\s+(?:soon|shortly)\b"),
    ("not_started", "strong", "soon", rf"\b{_REG}\s+(?:opening|coming)\s+soon\b"),
    ("not_started", "strong", "soon", rf"\b{_REG}\s+(?:(?:are|is|have|has)\s+)?(?:not\s+yet|yet\s+to|not)\s+(?:open(?:ed)?|start(?:ed)?|begun)\b"),
    ("not_started", "weak", "soon", r"\bcoming\s+soon\b"),
    ("not_started", "weak", "soon", r"\bstay\s+tuned\b"),
    ("not_started", "weak", "soon", r"\bnotify\s+me\b"),
    ("not_started", "weak", "soon", r"\b(?:pre[- ]?register|expression\s+of\s+interest)\b"),
    ("closed", "strong", "closed", rf"\b{_REG}\s+(?:(?:are|is|has|have|been|now|officially)\s+)*closed\b"),
    ("closed", "strong", "closed", rf"\b{_REG}\s+(?:has|have)\s+ended\b"),
    ("closed", "strong", "closed", r"\bsold\s*[- ]?out\b"),
    ("closed", "strong", "closed", r"\bentries\s+(?:are\s+|now\s+)*closed\b"),
    ("open", "strong", "open", r"\bregister\s+now\b"),
    ("open", "strong", "open", rf"\b{_REG}\s+(?:(?:are|is|now)\s+)*(?:open|live)\b(?!\s+(?:on|from|soon|shortly|in|after|for\s+the\s+\d{{4}}\s+edition\s+(?:on|from)))"),
    ("open", "strong", "open", r"\bbook\s+your\s+(?:slot|spot|bib|place)\b"),
    ("open", "strong", "open", r"\bentries\s+(?:are\s+|now\s+)*open\b(?!\s+(?:on|from|soon))"),
    ("open", "strong", "closes_on", rf"\b{_REG}\s+(?:will\s+)?(?:close[sd]?|ends?)(?:\s*:|\s+on\b|\s+by\b|(?=\s+\d))"),
    ("open", "strong", "closes_on", r"\blast\s+date\s+(?:to|for|of)\s+regist(?:er|ration)\b"),
]
_COMPILED = [(s, st, k, re.compile(p, re.I)) for s, st, k, p in _PATTERNS]
_LINK_TEXT = re.compile(r"\b(register|registration|sign\s*up|book\s+(?:now|your)|enter\s+now|buy\s+tickets?)\b", re.I)
_BLOCK_MARKERS = ("just a moment", "cf-chl", "attention required", "access denied", "captcha")
_JS_MARKERS = ("enable javascript", "you need to enable javascript", "javascript is required")
_DATE_KIND = {"opens_on": "opens", "closes_on": "closes", "closed": "closed"}


def _signal(url, status, strength, kind, text, m, dates, phrase=None):
    return {"url": url, "status": status, "strength": strength, "kind": kind,
            "phrase": phrase or m.group(0), "evidence": snippet(text, m.start(), m.end()), "dates": dates}


def find_signals(text: str, links: List[Dict[str, Any]], url: str = "", today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Detect registration signals in page text (+ registration-platform links)."""
    today = today or date.today()
    taken: List[tuple] = []
    signals: List[Dict[str, Any]] = []
    for status, strength, kind, rx in _COMPILED:
        for m in rx.finditer(text):
            if any(not (m.end() <= s or m.start() >= e) for s, e in taken):
                continue  # earlier (more specific) pattern already owns this span
            taken.append((m.start(), m.end()))
            # Dates: after the phrase for "opens on/closes on", otherwise a small window around it.
            if kind in ("opens_on", "closes_on"):
                window = text[m.end(): m.end() + 60]
                hits = extract_dates(window)[:1]
            else:
                window = text[max(0, m.start() - 50): m.end() + 80]
                hits = extract_dates(window)
            dates = [{"date": h["date"], "raw": h["raw"], "kind": _DATE_KIND.get(kind, "mentioned")} for h in hits]
            st, sg = status, strength
            if kind == "opens_on" and dates and date.fromisoformat(dates[0]["date"]) < today:
                st, sg = "open", "weak"          # "registrations opened on <past date>"
            elif kind == "closes_on":
                if dates and date.fromisoformat(dates[0]["date"]) < today:
                    st, sg = "closed", "weak"    # deadline already passed
                elif not dates:
                    sg = "weak"
            signals.append(_signal(url, st, sg, kind, text, m, dates))

    for link in links or []:
        href = str(link.get("href") or "")
        host = urlparse(href).netloc.lower()
        label = str(link.get("text") or "")
        if host and any(p in host + urlparse(href).path.lower() for p in REGISTRATION_PLATFORMS) and _LINK_TEXT.search(label):
            signals.append({"url": url, "status": "open", "strength": "weak", "kind": "platform_link",
                            "phrase": label[:80], "evidence": f"Link '{label[:80]}' -> {href}"[:200], "dates": []})
    return signals


def _page_problem(fr: FetchResult, text: str, meta: Dict[str, Any]) -> Optional[str]:
    if fr.error:
        return fr.error
    if fr.status_code is not None and fr.status_code >= 400:
        if fr.status_code in (401, 403, 429, 503):
            return f"blocked (HTTP {fr.status_code})"
        return f"HTTP {fr.status_code}"
    return None


def _content_problem(fr: FetchResult, text: str, meta: Dict[str, Any]) -> Optional[str]:
    """Only consulted when a fetched page yielded no signals at all."""
    low = (fr.text[:20000] or "").lower()
    if len(text) < 400 and any(b in low for b in _BLOCK_MARKERS):
        return "blocked (bot challenge page)"
    if not text.strip() or _looks_js_rendered(fr, text, meta):
        return "JavaScript-rendered page (no readable text)" if _looks_js_rendered(fr, text, meta) else "empty page"
    return None


def _looks_js_rendered(fr: FetchResult, text: str, meta: Dict[str, Any]) -> bool:
    """Little readable text plus scripts (or an explicit 'enable JavaScript' notice)."""
    low = (fr.text[:20000] or "").lower()
    return len(text) < 300 and (meta.get("script_count", 0) > 0 or any(j in low for j in _JS_MARKERS))


_TICKET_RE = re.compile(r'"ticket_name"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _ticket_field(chunk: str, key: str) -> Optional[str]:
    m = re.search(rf'"{key}"\s*:\s*("(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)', chunk)
    if not m:
        return None
    v = m.group(1)
    return v[1:-1] if v.startswith('"') else v


def _ts(value: Optional[str]) -> Optional[datetime]:
    """KonfHub timestamps: 'YYYY-MM-DD HH:MM:SS' (UTC) or epoch seconds/ms."""
    if not value or value == "null":
        return None
    try:
        if re.fullmatch(r"\d{10,13}", value):
            n = int(value)
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, tz=timezone.utc)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def ticketing_signals(raw_html: str, url: str = "", now: Optional[datetime] = None,
                      ticket_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Structured signals from ticket JSON embedded in ticketing pages (KonfHub-style).

    Per visible ticket: sold_out=true -> closed; sale window ended -> closed; window not yet started ->
    not_started; inside window and not sold out -> open. Aggregated: any open ticket -> open; else any
    upcoming -> not_started; else (all sold out / ended) -> closed. Strength "ticketing" outranks page text.
    """
    if not raw_html or '"ticket_name"' not in raw_html or '"sold_out"' not in raw_html:
        return []
    now = now or datetime.now(timezone.utc)
    flt = re.compile(ticket_filter, re.I) if ticket_filter else None
    matches = list(_TICKET_RE.finditer(raw_html))
    states = []
    for i, m in enumerate(matches):
        chunk = raw_html[m.start(): matches[i + 1].start() if i + 1 < len(matches) else m.start() + 4000]
        name = m.group(1)
        if flt and not flt.search(name):
            continue
        if _ticket_field(chunk, "hidden_ticket") == "true" or _ticket_field(chunk, "is_deleted") == "true":
            continue
        sold = _ticket_field(chunk, "sold_out")
        start, end = _ts(_ticket_field(chunk, "start_timestamp")), _ts(_ticket_field(chunk, "end_timestamp"))
        if sold == "true":
            st = "closed"
        elif end and end < now:
            st = "closed"
        elif start and start > now:
            st = "not_started"
        elif sold == "false":
            st = "open"
        else:
            continue
        states.append((st, name, start, end, sold))
    if not states:
        return []
    found = {s[0] for s in states}
    status = "open" if "open" in found else "not_started" if "not_started" in found else "closed"
    picked = [s for s in states if s[0] == status]
    dates = []
    for st, _, start, end, _ in picked:
        if status == "not_started" and start:
            dates.append({"date": start.date().isoformat(), "raw": start.isoformat(), "kind": "opens"})
        if status == "open" and end:
            dates.append({"date": end.date().isoformat(), "raw": end.isoformat(), "kind": "closes"})
    detail = ", ".join(f"{n[:40]}: {'sold out' if so == 'true' else st}" for st, n, _, _, so in states)
    return [{"url": url, "status": status, "strength": "ticketing", "kind": "ticketing",
             "phrase": f"ticket data ({len(states)} tickets)",
             "evidence": f"Ticket data - {detail}"[:200], "dates": dates[:1]}]


def apply_rules(signals: List[Dict[str, Any]], race: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply optional per-race seed rules (ignore_phrases / ignore_signals / trusted_urls)."""
    phrases = [p.lower() for p in (race.get("ignore_phrases") or []) if p]
    ignore_st = set(race.get("ignore_signals") or [])
    trusted = [u for u in (race.get("trusted_urls") or []) if u]
    edition = race.get("edition_year")
    current = race.get("registration_status")
    out = []
    for s in signals:
        if s["strength"] != "ticketing":
            if s["status"] in ignore_st:
                continue
            if any(p in s["phrase"].lower() for p in phrases):
                continue
            if isinstance(edition, int):
                years = [int(d["date"][:4]) for d in s["dates"]]
                # Dated text that only refers to earlier editions is stale.
                if years and max(years) < edition:
                    continue
                # "Registration closed" (undated or old-dated) while we track a not-yet-open next
                # edition describes the previous edition, not a change.
                if s["status"] == "closed" and current == "not_started" and not any(y >= edition for y in years):
                    continue
            if s["strength"] == "strong" and any(s["url"].startswith(t) for t in trusted):
                s = {**s, "strength": "trusted"}
        out.append(s)
    return out


_TIER = {"ticketing": 4, "trusted": 3, "strong": 2, "weak": 1}


def _aggregate(res: "ScanResult", signals: List[Dict[str, Any]], seed_status: str, today: date) -> None:
    """Pick a status from the highest-priority tier of signals present; conservative on conflicts."""
    if not signals:
        res.status, res.confidence, res.evidence = "unknown", "low", None
        return
    top = max(_TIER[s["strength"]] for s in signals)
    pool = [s for s in signals if _TIER[s["strength"]] == top]
    lower = [s for s in signals if _TIER[s["strength"]] < top]
    statuses = {s["status"] for s in pool}

    def pick(st):
        best = next((s for s in pool if s["status"] == st and s["dates"]), None) or \
            next(s for s in pool if s["status"] == st)
        res.evidence, res.evidence_url = best["evidence"][:200], best["url"]
        dates, seen = [], set()
        for s in pool:
            if s["status"] == st:
                for d in s["dates"]:
                    if (d["date"], d["kind"]) not in seen:
                        seen.add((d["date"], d["kind"]))
                        dates.append({**d, "url": s["url"]})
        res.detected_dates = dates

    if len(statuses) > 1:
        res.conflict = True
        # Tie-break: exactly one status backed by a forward-looking dated phrase
        # ("will open on <future date>", "closes on <future date>") wins at medium confidence.
        forward = {s["status"] for s in pool if s["kind"] in ("opens_on", "closes_on")
                   and any(d["date"] >= today.isoformat() for d in s["dates"])}
        if top >= 2 and len(forward) == 1:
            st = forward.pop()
            pick(st)
            res.status, res.confidence = st, "medium"
            return
        firsts = []
        for st in sorted(statuses):
            s = next(x for x in pool if x["status"] == st)
            firsts.append(f"{st}: \"{s['phrase']}\"")
        res.status, res.confidence = seed_status, "low"
        res.evidence = ("Conflicting signals - " + "; ".join(firsts))[:200]
        res.evidence_url = pool[0]["url"]
        return

    st = statuses.pop()
    pick(st)
    res.status = st
    if top >= 3:
        res.confidence = "high"
    elif top == 2:
        support = [s for s in pool if s["status"] == st]
        contradicted = any(s["status"] != st for s in lower)
        high = len(support) >= 2 or any(s["dates"] for s in support)
        res.confidence = "high" if high and not contradicted else "medium"
    else:
        res.confidence = "low"


@dataclass
class ScanResult:
    race_id: str
    status: str = "unknown"
    confidence: str = "low"
    evidence: Optional[str] = None
    evidence_url: Optional[str] = None
    detected_dates: List[Dict[str, Any]] = field(default_factory=list)
    http_status: Optional[int] = None
    error: Optional[str] = None
    conflict: bool = False
    pages: List[Dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _urls_for(race: Dict[str, Any]) -> List[str]:
    urls = list(race.get("scrape_urls") or [])
    if not urls:
        urls = [u for u in (race.get("registration_url"), race.get("official_url")) if u]
    seen, out = set(), []
    for u in urls:
        if u not in seen and str(u).startswith(("http://", "https://")):
            seen.add(u)
            out.append(u)
    return out


def scan_race(race: Dict[str, Any], fetch: Optional[Callable[[str], Any]] = None,
              budget_s: float = DEFAULT_RACE_BUDGET_S, today: Optional[date] = None,
              now: Optional[datetime] = None) -> ScanResult:
    """Fetch each scrape URL of ``race`` and classify registration status.

    ``fetch(url)`` may return a FetchResult, a requests.Response-like object, a (status, text) tuple,
    or an HTML string; exceptions are caught and recorded.

    Optional per-race seed keys (see docs/RACE_RESEARCH.md, "Scanner rules"):
      ignore_phrases  - case-insensitive substrings; matching text signals are dropped (e.g. "register now")
      ignore_signals  - statuses whose *text* signals are dropped for this race (ticketing data still counts)
      trusted_urls    - URL prefixes whose strong signals outrank generic page text
      ticket_filter   - regex; only ticketing entries whose ticket_name matches are considered
    Signal priority: ticketing data (KonfHub sold_out/timestamps) > trusted-URL text > strong text > weak text.
    """
    fetch = fetch or http_fetch
    seed_status = race.get("registration_status") or race.get("status") or "unknown"
    res = ScanResult(race_id=race.get("id", ""), checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    urls = _urls_for(race)
    if not urls:
        res.error = "no URLs to scan"
        return res

    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    started = time.monotonic()
    signals: List[Dict[str, Any]] = []
    ok_pages, errors = 0, []
    for url in urls:
        if time.monotonic() - started > budget_s:
            errors.append(f"{url}: skipped (time budget exhausted)")
            res.pages.append({"url": url, "http_status": None, "error": "skipped (time budget)"})
            continue
        try:
            fr = _coerce(url, fetch(url))
        except Exception as exc:
            fr = FetchResult(url, None, "", f"{type(exc).__name__}: {exc}"[:300])
        text, links, meta = parse_html(fr.text) if fr.text else ("", [], {})
        problem = _page_problem(fr, text, meta)
        if res.http_status is None and fr.status_code is not None:
            res.http_status = fr.status_code
        page = {"url": url, "http_status": fr.status_code, "error": problem, "signals": 0}
        sigs = []
        if not problem:
            sigs = ticketing_signals(fr.text, url, now=now, ticket_filter=race.get("ticket_filter")) + \
                find_signals(text, links, url, today=today)
            sigs = apply_rules(sigs, race)
        if not problem and not sigs:
            problem = page["error"] = _content_problem(fr, text, meta)
        if problem:
            errors.append(f"{url}: {problem}")
        else:
            ok_pages += 1
            page["signals"] = len(sigs)
            signals.extend(sigs)
        res.pages.append(page)

    if errors:
        res.error = "; ".join(errors)[:500]
    if ok_pages == 0:
        res.status, res.confidence = "unknown", "low"
        return res

    _aggregate(res, signals, seed_status, today or date.today())
    return res
