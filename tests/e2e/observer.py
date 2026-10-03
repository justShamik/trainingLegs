"""PageObserver: records everything that goes wrong in the browser.

Captured per page: console errors/warnings, uncaught page errors, failed
requests, HTTP >= 400 responses and (Chromium only) Chrome DevTools Protocol
events ``Log.entryAdded`` and ``Network.loadingFailed``.

Anything that matches an allow-list regex is ignored.  The regex is matched
against ``"<kind>: <text> [<url>]"``.
"""
import re
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class Issue:
    kind: str
    text: str
    url: str = ""

    def __str__(self) -> str:
        return f"{self.kind}: {self.text}" + (f" [{self.url}]" if self.url else "")


class PageObserver:
    def __init__(self, allow=(), on_issue: Optional[Callable[[Issue], None]] = None, use_cdp: bool = True) -> None:
        self.allow: List[re.Pattern] = [re.compile(a) for a in allow]
        self.issues: List[Issue] = []
        self.on_issue = on_issue
        self.use_cdp = use_cdp
        self._lock = threading.Lock()
        self._seen_cdp = set()

    # ------------------------------------------------------------------ setup
    def allow_pattern(self, pattern: str) -> None:
        self.allow.append(re.compile(pattern))

    def attach_context(self, context) -> None:
        context.on("page", self.attach_page)
        for page in context.pages:
            self.attach_page(page)

    def attach_page(self, page) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", lambda err: self._add("pageerror", str(err), page.url))
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)
        if self.use_cdp:
            try:
                cdp = page.context.new_cdp_session(page)
                cdp.send("Log.enable")
                cdp.send("Network.enable")
                cdp.on("Log.entryAdded", lambda ev: self._on_cdp_log(ev, page))
                cdp.on("Network.loadingFailed", lambda ev: self._on_cdp_net(ev, page))
            except Exception:
                pass  # non-Chromium browser

    # --------------------------------------------------------------- handlers
    def _on_console(self, msg) -> None:
        if msg.type in ("error", "warning"):
            loc = msg.location or {}
            self._add(f"console.{msg.type}", msg.text, loc.get("url", ""))

    def _on_request_failed(self, req) -> None:
        failure = req.failure or ""
        if "ERR_ABORTED" in str(failure):  # navigation replaced by another one
            return
        self._add("requestfailed", f"{req.method} {failure}", req.url)

    def _on_response(self, resp) -> None:
        if resp.status >= 400:
            self._add("http", f"{resp.status} {resp.request.method}", resp.url)

    def _on_cdp_log(self, ev, page) -> None:
        entry = ev.get("entry", {})
        if entry.get("level") in ("error", "warning"):
            key = ("log", entry.get("text"), entry.get("url"))
            if key not in self._seen_cdp:
                self._seen_cdp.add(key)
                self._add(f"cdp.Log.{entry.get('level')}", f"{entry.get('source', '')}: {entry.get('text', '')}", entry.get("url", ""))

    def _on_cdp_net(self, ev, page) -> None:
        if ev.get("canceled") or ev.get("errorText") == "net::ERR_ABORTED":
            return
        self._add("cdp.Network.loadingFailed", ev.get("errorText", ""), ev.get("requestId", ""))

    # ----------------------------------------------------------------- results
    def _add(self, kind: str, text: str, url: str = "") -> None:
        issue = Issue(kind, text, url)
        with self._lock:
            self.issues.append(issue)
        if self.on_issue and not self.is_allowed(issue):
            self.on_issue(issue)

    def is_allowed(self, issue: Issue) -> bool:
        s = str(issue)
        return any(a.search(s) for a in self.allow)

    def unexpected(self) -> List[Issue]:
        with self._lock:
            return [i for i in self.issues if not self.is_allowed(i)]

    def clear(self) -> None:
        with self._lock:
            self.issues.clear()
