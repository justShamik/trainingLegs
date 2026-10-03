"""Best-effort discovery of 50 km races in/near Delhi NCR in Nov-Jan from public race-listing pages.

Results are *candidates* flagged ``unverified: True``; they are never added to the watchlist automatically.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from app.races.scanner import FetchResult, _coerce, http_fetch
from app.races.textutil import extract_dates, parse_html, snippet

logger = logging.getLogger(__name__)

DEFAULT_LISTING_URLS = [
    "https://www.indiarunning.com/delhi-ncr",
    "https://www.indiarunning.com/running-events-in-delhi",
    "https://www.townscript.com/discover/running-events/delhi",
    "https://www.ifinish.in/running-calendar",
    "https://www.myraceindia.com/Race_Calendar.asp",
]
RESEARCH_DOC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "RACE_RESEARCH.md")

_DIST = re.compile(r"\b50\s*(?:k\b|km\b|kms\b|kilomet(?:er|re)s?\b)", re.I)
_NCR = re.compile(r"\b(delhi|new\s+delhi|ncr|gurugram|gurgaon|noida|greater\s+noida|faridabad|ghaziabad|aravalli|aravali|sohna|damdama|manesar)\b", re.I)
_MONTH = re.compile(r"\b(nov(?:ember)?|dec(?:ember)?|jan(?:uary)?)\b\.?(?:\s*,?\s*\d{4})?", re.I)
_BEFORE, _AFTER = 2, 4  # lines of context around a "50K" line that form one listing card


def listing_urls_from_research(path: str = RESEARCH_DOC) -> List[str]:
    """URLs mentioned on lines about listings/calendars/discovery in docs/RACE_RESEARCH.md (if present)."""
    if not os.path.exists(path):
        return []
    urls: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if re.search(r"listing|calendar|discover|aggregat|event\s+portal", line, re.I):
                    for u in re.findall(r"https?://[^\s)>\]\"'`]+", line):
                        u = u.rstrip(".,;")
                        if u not in urls:
                            urls.append(u)
    except OSError:
        return []
    return urls


def candidates_from_html(html: str, page_url: str = "") -> List[Dict[str, Any]]:
    """Extract 50K-in-NCR-in-Nov/Dec/Jan candidates from one listing page.

    Works on text lines (block elements): a line mentioning 50K plus a few neighbouring lines form the
    "card" that must also mention an NCR place and a Nov/Dec/Jan month or date.
    """
    text, links, _ = parse_html(html)
    lines = text.split("\n")
    titles = {str(l.get("text") or "").strip() for l in links if len(str(l.get("text") or "").strip()) > 3}
    out: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        m = _DIST.search(line)
        if not m:
            continue
        # Card = [title line] + 50K line + following lines, bounded by the next linked title (next card).
        name = line.strip()
        card_lines = [line]
        if name not in titles:
            for j in range(i - 1, max(-1, i - 1 - _BEFORE), -1):
                card_lines.insert(0, lines[j])
                if lines[j].strip() in titles:
                    name = lines[j].strip()
                    break
        for j in range(i + 1, min(len(lines), i + 1 + _AFTER)):
            if lines[j].strip() in titles:
                break
            card_lines.append(lines[j])
        window = "\n".join(card_lines)
        loc = _NCR.search(window)
        if not loc:
            continue
        all_dates = extract_dates(window)
        dates = [d for d in all_dates if int(d["date"][5:7]) in (11, 12, 1)]
        month = _MONTH.search(window)
        if not dates and (all_dates or not month):
            continue  # explicit dates exist but none in Nov-Jan, or no date info at all
        url = None
        for link in links:
            lt = str(link.get("text") or "").strip()
            if lt and len(lt) > 3 and link.get("href") and any(lt in cl for cl in card_lines):
                url = urljoin(page_url, str(link["href"]))
                if lt in name or name in lt:
                    break
        pos = window.find(line)
        out.append({
            "name": name[:120],
            "url": url or page_url,
            "date_text": dates[0]["raw"] if dates else month.group(0),
            "date": dates[0]["date"] if dates else None,
            "location_match": loc.group(0),
            "evidence": snippet(window, pos + m.start(), pos + m.end()),
            "source_page": page_url,
            "unverified": True,
        })
    return out


def discover_ncr_50k(fetch: Optional[Callable[[str], Any]] = None, urls: Optional[List[str]] = None,
                     budget_s: float = 60.0, report: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Scan listing pages and return unverified candidate dicts
    {name, url, date_text, date, location_match, evidence, source_page, unverified=True}.
    Per-page fetch outcomes ({url, http_status, error, found}) are appended to ``report`` if given."""
    fetch = fetch or http_fetch
    urls = urls or listing_urls_from_research() or DEFAULT_LISTING_URLS
    started = time.monotonic()
    pages, found, seen = [], [], set()
    for url in urls:
        if time.monotonic() - started > budget_s:
            pages.append({"url": url, "http_status": None, "error": "skipped (time budget)", "found": 0})
            continue
        try:
            fr = _coerce(url, fetch(url))
        except Exception as exc:
            fr = FetchResult(url, None, "", f"{type(exc).__name__}: {exc}"[:300])
        err = fr.error or (f"HTTP {fr.status_code}" if fr.status_code and fr.status_code >= 400 else None)
        n = 0
        if not err and fr.text:
            for c in candidates_from_html(fr.text, url):
                key = (c["name"].lower(), c["url"])
                if key not in seen:
                    seen.add(key)
                    found.append(c)
                    n += 1
        pages.append({"url": url, "http_status": fr.status_code, "error": err, "found": n})
    if report is not None:
        report.extend(pages)
    return found
