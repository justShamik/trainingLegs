# End-to-End Browser Test Protocol

Drives real Chrome (Playwright + Chrome DevTools Protocol) through every page and button of the
app, against a **temporary seeded SQLite DB** (never `coach.db`) with COROS and Gemini stubbed.
Every test fails automatically on any unexpected browser error or server-log problem.

## 1. Install
```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt   # playwright 1.63, pytest-playwright 0.9
.\.venv\Scripts\python -m playwright install chromium       # fallback browser
```
Installed Google Chrome is preferred automatically (`channel="chrome"`); Chromium is the fallback.
Force one with `--browser-channel chrome|msedge` or `E2E_CHANNEL`.

## 2. Run
```powershell
.\scripts\run_e2e.ps1                       # headless, whole suite
.\scripts\run_e2e.ps1 -Headed -SlowMo 300   # watch it click
.\scripts\run_e2e.ps1 -Filter sync          # pytest -k
.\scripts\run_e2e.ps1 -Unit                 # unit suite first, then e2e
.\.venv\Scripts\python -m pytest tests/e2e -q   # same thing directly
```
E2E tests are **opt-in**: they only run when `tests/e2e` is targeted (or `E2E=1`), so the normal
`pytest -q --deselect test_gemini.py` stays fast and browser-free (e2e tests show as skipped).

On failure, `tests/e2e/artifacts/` (gitignored) receives, per test: full-page screenshot, list of
recorded browser issues + server-log problems, and a Playwright trace
(`.\.venv\Scripts\python -m playwright show-trace <file>_trace.zip`).

## 3. Manual monitored session
```powershell
.\scripts\run_e2e.ps1 -Manual            # safe: temp DB, COROS stubbed
.\scripts\run_e2e.ps1 -Manual -Real      # real coach.db + real COROS (writes real data!)
```
Opens headed Chrome with DevTools and `--remote-debugging-port=9222`. Click around freely; the terminal
streams, in colour: `[browser]` console errors/warnings, page errors, failed requests, HTTP >= 400
(Playwright events + CDP `Log.entryAdded` / `Network.loadingFailed`), and `[server]` ERROR /
Traceback / 5xx lines, plus WARNINGs and sync results from `logs/app.log`.

## 4. Log checking
`app/logging_config.py` (`setup_logging`, called from `create_app`) writes rotating logs (1 MB x 5) to
`logs/app.log` (override: `COACH_LOG_FILE`):
```
2026-09-29 10:15:02,123 | INFO | coach.web | request method=GET path=/ status=200 duration_ms=12.3
2026-09-29 10:15:09,001 | INFO | coach.web | action_result action=sync_incremental status=success message="..."
2026-09-29 10:15:20,500 | ERROR | coach.web | unhandled_exception method=GET path=/x error=ValueError: boom   (+ traceback)
```
Request lines: 5xx = ERROR, 4xx = WARNING. Failed syncs = WARNING. Nothing is written under pytest
unless `COACH_LOG_FILE` is set (unit tests never pollute the log).

`tests/e2e/log_checker.py`:
* pytest: an autouse fixture snapshots the log offset before each test and, after it, fails the test
  with any new ERROR/CRITICAL, `Traceback` or `status=5xx` block.
* standalone: `python -m tests.e2e.log_checker --follow` (live tail, problems in red, warnings in
  yellow; `--all`, `--from-start`), or `--scan` (whole file once, exit 1 on problems).

## 5. Test matrix
| Page | Action | Expected |
|---|---|---|
| every page (7 start pages) | click each of 6 navbar links | correct URL, h1, link gets `active` |
| any | brand logo | dashboard |
| `/nope`, `/activity/x` | open | 404 friendly page, no traceback, "Return to Dashboard" works |
| navbar | COROS status | "Connected"; "Connect COROS" when unauthenticated |
| `/` | KPIs / charts | headers with windows, 3 charts initialised, last-sync shown |
| `/` | 7 / 30 / 90 / All Time | URL `days=N`, row counts monotonic, window respected, 200-day run only in All |
| `/` | activity names | HTML escaped |
| `/` -> activity | View Details on full-dynamics run | cadence/stride/GCT/VO/power + 10 splits; back link works |
| `/activity/<sparse>` | open | "Not Available" badges, no-splits message |
| `/` | Sync Pending / Sync 365 | `#syncOverlay` shown, button `is-syncing`, then success banner + new data (Chrome blocks Playwright during the POST, so an in-page recorder captures overlay state) |
| `/` | sync while COROS down / unauthenticated | error banner / login-required banner; "Authenticate" button -> login-opened banner |
| back button after sync | | overlay never stuck |
| `/plan` | seeded plan | methodology, compliance |
| `/plan` | Discard (accept / dismiss confirm) | plan removed / kept |
| `/plan` | Generate Build / Deload | plan appears; deload flagged, volume differs |
| `/plan` | Log workout Completed / Skipped / Modified | badge, feedback, adherence rating |
| `/plan` | Auto-Match | reload without error |
| `/block-summary` | open from plan | KPI cards, history section |
| `/strength` | each phase Base/Build/Peak/Taper | phase badge, exercises, complete button |
| `/strength` | Mark Completed | badge; regenerate resets |
| `/strength` | no workout in DB | auto-generated; niggle profile shows safety filter |
| `/profile` | save all fields | success banner, DB values, form re-populated |
| `/chat` | API key save | profile untouched (regression: key-only save must not wipe it) |
| `/chat` | 3 sample questions, free text | coach answer appears, loader hidden, HTML escaped (no img/script/b) |
| `/chat` | blank send | blocked |
| all 7 pages @390px | load | h1 visible, no horizontal page overflow |
| server log | sync | request + `action_result` lines, failed sync = WARNING |

## 6. How it works / adding tests
* `tests/e2e/server_main.py` starts the app in a subprocess; `fake_coros.py` replaces `CorosMCPClient`
  and `GeminiCLIWrapper.ask_coach` (test-only, production code untouched). Switch COROS behaviour in a
  test with `server.set_coros_mode("ok" | "fail" | "unauth")`; `COACH_E2E_SYNC_DELAY` keeps syncs in flight.
* `seed.py` re-seeds the DB before **every** test (activities incl. a full-dynamics run `e2e_full_dynamics`,
  sleep, physiology, sync log, profile, plan, strength workout).
* CDN Chart.js and Google Fonts are served from local stubs so runs are offline-deterministic.
* New test: add `tests/e2e/test_e2e_<area>.py`, take the `page` (or `mobile_page`) fixture, use role/text
  locators. Unexpected console/network/page/log errors fail it automatically. Expected ones:
  `@pytest.mark.allow_errors(r"404")` (regex against `"<kind>: <text> [<url>]"` and server log blocks).
* Test file names must be unique across `tests/` (no `__init__.py`).
