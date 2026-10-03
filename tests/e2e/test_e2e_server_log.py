"""The structured server log records requests and sync outcomes (what the log checker relies on)."""
import re

from playwright.sync_api import expect


def test_server_log_records_requests_and_sync_outcome(page, server):
    page.goto("/dashboard")
    page.get_by_role("button", name=re.compile("Sync Pending Data")).click(no_wait_after=True)
    page.wait_for_url(re.compile("sync_status=success"), timeout=30_000)
    expect(page.get_by_text("Sync Result:")).to_be_visible()
    text = open(server.log_path, encoding="utf-8").read()
    assert re.search(r"request method=GET path=/dashboard status=200 duration_ms=", text)
    assert re.search(r"request method=POST path=/sync status=302", text)
    assert re.search(r"action_result action=sync_incremental status=success", text)


def test_failed_sync_is_logged_as_warning_not_error(page, server):
    server.set_coros_mode("fail")
    page.goto("/dashboard")
    page.get_by_role("button", name=re.compile("Sync Pending Data")).click(no_wait_after=True)
    page.wait_for_url(re.compile("sync_status=error"), timeout=30_000)
    text = open(server.log_path, encoding="utf-8").read()
    assert re.search(r"\| WARNING \| coach.web \| action_result action=sync_incremental status=error", text)
