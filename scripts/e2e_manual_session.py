r"""Manual, monitored click-through session.

Starts the app and a HEADED Chrome (DevTools open, remote debugging on port 9222), then streams
to this terminal, in one place:
  * browser console errors/warnings, uncaught page errors, failed requests, HTTP >= 400 (via Playwright + CDP)
  * server-log problems (ERROR / Traceback / 5xx, and WARNINGs) from the app log

    .venv\Scripts\python scripts\e2e_manual_session.py            # temp DB seeded with fixtures, COROS stubbed (safe)
    .venv\Scripts\python scripts\e2e_manual_session.py --real     # real coach.db + real COROS (careful: it writes)

Close the browser window or press Ctrl+C to end.  Attach other tools at http://127.0.0.1:9222.
"""
import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.e2e.harness import ServerHandle, launch_browser  # noqa: E402
from tests.e2e.log_checker import LogChecker, PROBLEM_RE, TS_RE, WARNING_RE, RED, YELLOW, RESET  # noqa: E402
from tests.e2e.observer import PageObserver  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="store_true", help="use the real coach.db and real COROS instead of the safe fixtures")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--debug-port", type=int, default=9222)
    ap.add_argument("--channel", default=None, help="chrome (default, falls back to chromium) | chromium | msedge")
    args = ap.parse_args()
    if os.name == "nt":
        os.system("")

    workdir = tempfile.mkdtemp(prefix="coach_manual_")
    server = ServerHandle(workdir, port=args.port, seed=not args.real, real_coros=args.real, sync_delay=1.0)
    if args.real:
        server.db_path = os.path.join(ROOT, "coach.db")
        server.log_path = os.path.join(ROOT, "logs", "app.log")
    server.start()
    print(f"[session] app at {server.base_url}  (db: {server.db_path})\n[session] server log: {server.log_path}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = launch_browser(
            pw, headless=False, channel=args.channel,
            args=[f"--remote-debugging-port={args.debug_port}", "--auto-open-devtools-for-tabs"])
        ctx = browser.new_context(base_url=server.base_url, viewport=None)
        obs = PageObserver(on_issue=lambda i: print(f"{RED}[browser] {i}{RESET}", flush=True))
        obs.attach_context(ctx)
        page = ctx.new_page()
        page.goto("/")
        print(f"[session] Chrome DevTools protocol: http://127.0.0.1:{args.debug_port}\n"
              "[session] click around; problems appear below. Close the window or Ctrl+C to stop.\n")

        checker = LogChecker(server.log_path)
        in_block = False
        try:
            while browser.is_connected() and page.context.pages:
                page.wait_for_timeout(400)  # pumps Playwright events
                for line in checker.read_since().splitlines():
                    if TS_RE.match(line):
                        in_block = bool(PROBLEM_RE.search(line))
                        if in_block:
                            print(f"{RED}[server] {line}{RESET}", flush=True)
                        elif WARNING_RE.search(line) or "action_result" in line:
                            print(f"{YELLOW}[server] {line}{RESET}", flush=True)
                    elif in_block:
                        print(f"{RED}[server]   {line}{RESET}", flush=True)
                checker.snapshot()
        except KeyboardInterrupt:
            pass
        except Exception:  # browser window closed by the user
            pass
        finally:
            problems = obs.unexpected()
            print(f"\n[session] ended: {len(problems)} browser issue(s) recorded")
            try:
                browser.close()
            except Exception:
                pass
            server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
