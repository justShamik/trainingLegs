"""Stdlib-only helpers shared by the race scanner and discovery: HTML -> text, date extraction."""
from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "li", "ul", "ol",
    "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "form", "button",
    "dd", "dt", "dl", "figure", "figcaption", "blockquote", "option", "label",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.links: List[Dict[str, object]] = []   # {"href", "text"}
        self.script_count = 0
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self._link_stack: List[Dict[str, object]] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "script":
            self.script_count += 1
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._link_stack.append({"href": href.strip(), "text": ""})
        elif tag in ("input", "button"):
            val = dict(attrs).get("value")
            if val and tag == "input" and (dict(attrs).get("type") or "").lower() in ("submit", "button"):
                self.parts.append(f" {val} ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a" and self._link_stack:
            link = self._link_stack.pop()
            link["text"] = re.sub(r"\s+", " ", str(link["text"])).strip()
            self.links.append(link)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip_depth:
            return
        self.parts.append(data)
        for link in self._link_stack:
            link["text"] = str(link["text"]) + data


def parse_html(html: str) -> Tuple[str, List[Dict[str, object]], Dict[str, object]]:
    """Return (text, links, meta). Text keeps block boundaries as newlines, whitespace collapsed per line."""
    p = _TextExtractor()
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    raw = "".join(p.parts)
    lines = [re.sub(r"[ \t\r\f\v\xa0]+", " ", ln).strip() for ln in raw.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text, p.links, {"script_count": p.script_count, "title": p.title.strip()}


def html_to_text(html: str) -> str:
    return parse_html(html)[0]


def snippet(text: str, start: int, end: int, limit: int = 200) -> str:
    """Whitespace-collapsed context around [start, end), at most `limit` chars."""
    match_len = end - start
    pad = max(0, (limit - match_len) // 2)
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    out = re.sub(r"\s+", " ", text[s:e]).strip()
    if len(out) > limit:
        out = out[:limit].rstrip()
    return out


# ---------------------------------------------------------------- dates
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORD = r"(?:\s?(?:st|nd|rd|th)\b)?"  # tolerates "19 th" from <sup>th</sup>
_DMY_WORD = re.compile(rf"\b(\d{{1,2}}){_ORD}\s*(?:of\s+)?{_MON}\.?,?\s+(\d{{4}})\b", re.I)
_MDY_WORD = re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})\b", re.I)
_NUMERIC = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_dates(text: str) -> List[Dict[str, object]]:
    """Find explicit calendar dates (with a year) in text. Day-first for numeric dates (Indian convention).

    Returns [{"date": ISO, "raw": matched text, "pos": offset}] sorted by position, de-duplicated by span.
    Dates without a year are ignored on purpose (never guess a year).
    """
    found: List[Tuple[int, int, date, str]] = []

    def add(m, dt):
        if dt is None:
            return
        if any(not (m.end() <= s or m.start() >= e) for s, e, _, _ in found):
            return
        found.append((m.start(), m.end(), dt, m.group(0)))

    for m in _ISO.finditer(text):
        add(m, _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DMY_WORD.finditer(text):
        add(m, _mk(int(m.group(3)), _MONTHS[m.group(2).lower().rstrip(".")], int(m.group(1))))
    for m in _MDY_WORD.finditer(text):
        add(m, _mk(int(m.group(3)), _MONTHS[m.group(1).lower().rstrip(".")], int(m.group(2))))
    for m in _NUMERIC.finditer(text):
        add(m, _mk(int(m.group(3)), int(m.group(2)), int(m.group(1))))
    found.sort(key=lambda t: t[0])
    return [{"date": dt.isoformat(), "raw": raw.strip(), "pos": s} for s, _, dt, raw in found]


def parse_date(value) -> Optional[date]:
    """Lenient single-date parse: ISO first, then any explicit date format above. None if no full date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    hits = extract_dates(s)
    return date.fromisoformat(hits[0]["date"]) if hits else None
