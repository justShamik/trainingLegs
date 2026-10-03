"""Unit tests for the e2e log checker and logging_config (no browser needed)."""
import logging

from flask import Flask

from tests.e2e.log_checker import LogChecker, extract_problems

SAMPLE = """2026-09-29 10:00:00,000 | INFO | coach.web | request method=GET path=/ status=200 duration_ms=3.0
2026-09-29 10:00:01,000 | WARNING | coach.web | request method=GET path=/nope status=404 duration_ms=1.0
2026-09-29 10:00:02,000 | ERROR | coach.web | unhandled_exception method=GET path=/x error=ValueError: boom
Traceback (most recent call last):
  File "x.py", line 1, in f
ValueError: boom
2026-09-29 10:00:03,000 | ERROR | coach.web | request method=GET path=/x status=500 duration_ms=2.0
2026-09-29 10:00:04,000 | INFO | coach.web | request method=GET path=/ status=200 duration_ms=3.0
"""


def test_extract_problems_groups_tracebacks_and_ignores_4xx():
    blocks = extract_problems(SAMPLE)
    assert len(blocks) == 2
    assert "Traceback" in blocks[0] and "ValueError: boom" in blocks[0]
    assert "status=500" in blocks[1]


def test_checker_offsets_and_allow_list(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("2026-09-29 09:00:00,000 | ERROR | old | ignored\n", encoding="utf-8")
    checker = LogChecker(str(log))
    with open(log, "a", encoding="utf-8") as f:
        f.write(SAMPLE)
    assert len(checker.problems_since()) == 2
    assert checker.problems_since(allow=[r"boom", r"status=500"]) == []
    checker.snapshot()
    assert checker.problems_since() == []


def test_setup_logging_writes_request_and_exception_lines(tmp_path, monkeypatch):
    from app.logging_config import setup_logging
    log = tmp_path / "app.log"
    app = Flask(__name__)

    @app.route("/ok")
    def ok():
        return "ok"

    @app.route("/boom")
    def boom():
        raise ValueError("kaboom")

    setup_logging(app, log_file=str(log))
    root = logging.getLogger()
    try:
        client = app.test_client()
        client.get("/ok")
        client.get("/boom")
        text = log.read_text(encoding="utf-8")
        assert "request method=GET path=/ok status=200" in text
        assert "unhandled_exception" in text and "kaboom" in text
        assert "status=500" in text and "Traceback" in text
        assert len(extract_problems(text)) >= 1
    finally:
        for h in list(root.handlers):
            if getattr(h, "baseFilename", "") == str(log):
                root.removeHandler(h)
                h.close()
