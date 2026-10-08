"""Send to COROS: preview writes nothing, confirm sends exactly the ticked runs, no duplicates, outage blocks."""
import json
import os
import re

from playwright.sync_api import expect


def _calendar(server):
    path = server.mode_file + ".calendar.json"
    if not os.path.exists(path):
        return {"writes": 0, "days": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_preview_from_plan_writes_nothing(page, server):
    page.goto("/plan")
    page.locator("#sendToCorosBtn").click()
    expect(page).to_have_url(re.compile(r"/plan/push$"))
    expect(page.get_by_role("heading", name="Put your plan on the watch")).to_be_visible()
    expect(page.locator('.push-item[data-state="new"]').first).to_be_visible()
    expect(page.locator('.push-item[data-state="new"] ol li').first).to_contain_text("@")
    assert _calendar(server)["writes"] == 0


def test_confirm_sends_ticked_runs_once(page, server):
    page.goto("/plan/push")
    boxes = page.locator('input[name="session"]')
    n = boxes.count()
    assert n >= 2
    boxes.nth(0).uncheck()
    page.locator("#pushConfirmBtn").click()
    expect(page.locator("#pushResults")).to_contain_text(f"{n - 1} of {n - 1} sent")
    cal = _calendar(server)
    assert cal["writes"] == n - 1 and all(len(ws) == 1 for ws in cal["days"].values())
    # the unticked one is still offered; everything else is already on COROS
    expect(page.locator('input[name="session"]')).to_have_count(1)
    expect(page.locator('.push-item[data-state="unchanged"]')).to_have_count(n - 1)
    page.goto("/plan")
    expect(page.locator(".coros-chip", has_text="On COROS").first).to_be_visible()


def test_resubmitting_old_preview_does_not_duplicate(page, server):
    page.goto("/plan/push")
    page.locator("#pushConfirmBtn").click()
    expect(page.locator("#pushResults")).to_be_visible()
    sent = _calendar(server)["writes"]
    page.go_back()
    page.reload()
    expect(page.locator("#pushNothing")).to_be_visible()
    assert _calendar(server)["writes"] == sent


def test_coros_outage_blocks_sending(page, server):
    server.set_coros_mode("fail")
    page.goto("/plan/push")
    expect(page.locator("#corosReadError")).to_contain_text("checked for duplicates")
    expect(page.locator("#pushConfirmBtn")).to_have_count(0)
    expect(page.locator('input[name="session"]')).to_have_count(0)
    assert _calendar(server)["writes"] == 0
