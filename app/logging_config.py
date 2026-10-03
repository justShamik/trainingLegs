"""Structured application logging.

Writes rotating, single-line ``key=value`` logs to ``logs/app.log`` (override the
location with the ``COACH_LOG_FILE`` environment variable):

    2026-09-29 10:15:02,123 | INFO | coach.web | request method=GET path=/ status=200 duration_ms=12.3

Recorded events: every request (line, status, duration), unhandled exceptions
with full traceback, and the outcome of sync / COROS-login actions.

Nothing is written while running under pytest unless COACH_LOG_FILE is set
explicitly, so the unit-test suite never pollutes the real log.
"""
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, parse_qs

from flask import Flask, g, request
from flask.signals import got_request_exception

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "app.log")
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

web_logger = logging.getLogger("coach.web")


class _SkipWerkzeugAccess(logging.Filter):
    """Werkzeug's own access lines duplicate our structured request lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.name == "werkzeug" and record.levelno < logging.WARNING)


def resolve_log_file(log_file: str = None) -> str:
    return log_file or os.environ.get("COACH_LOG_FILE") or DEFAULT_LOG_FILE


def _install_file_handler(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    root = logging.getLogger()
    target = os.path.abspath(path)
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and os.path.abspath(h.baseFilename) == target:
            return
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(_SkipWerkzeugAccess())
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def setup_logging(app: Flask, log_file: str = None) -> None:
    """Attach the rotating file handler and request/exception/sync logging hooks."""
    if "PYTEST_CURRENT_TEST" in os.environ and not (log_file or os.environ.get("COACH_LOG_FILE")):
        return
    if app.extensions.get("coach_logging"):
        return
    app.extensions["coach_logging"] = True
    _install_file_handler(resolve_log_file(log_file))

    @app.before_request
    def _start_timer():
        g._log_start = time.perf_counter()

    @app.after_request
    def _log_request(response):
        start = getattr(g, "_log_start", None)
        duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
        status = response.status_code
        if request.path.startswith("/static/"):
            level = logging.DEBUG
        elif status >= 500:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        web_logger.log(
            level,
            "request method=%s path=%s status=%s duration_ms=%.1f",
            request.method, request.full_path.rstrip("?"), status, duration_ms,
        )
        if request.path in ("/sync", "/coros/login") and request.method == "POST":
            _log_action_outcome(response)
        return response

    def _on_exception(sender, exception, **extra):
        web_logger.error(
            "unhandled_exception method=%s path=%s error=%s: %s",
            request.method, request.path, type(exception).__name__, exception,
            exc_info=exception,
        )

    got_request_exception.connect(_on_exception, app, weak=False)


def _log_action_outcome(response) -> None:
    """Log the sync / COROS-login result carried in the redirect back to the dashboard."""
    query = parse_qs(urlparse(response.headers.get("Location", "")).query)
    status = (query.get("sync_status") or ["unknown"])[0]
    msg = (query.get("sync_msg") or [""])[0]
    action = "coros_login" if request.path == "/coros/login" else "sync"
    if action == "sync":
        action += "_full" if request.form.get("full") == "1" else "_incremental"
    level = logging.INFO if status == "success" else logging.WARNING
    web_logger.log(level, 'action_result action=%s status=%s message="%s"', action, status, msg)
