"""Shared helpers for the pytest e2e suite and scripts/e2e_manual_session.py."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHART_STUB = """
window.__chartCount = 0;
window.Chart = function (ctx, cfg) { window.__chartCount += 1; this.config = cfg; };
window.Chart.defaults = { color: '', font: {} };
"""


# Playwright operations wait for a pending (slow) navigation to commit, so the sync overlay cannot be
# inspected from the test while the POST is in flight.  This recorder captures its state in-page instead.
SUBMIT_RECORDER = """
document.addEventListener('submit', function (e) {
  setTimeout(function () {
    try {
      var o = document.getElementById('syncOverlay'), m = document.getElementById('syncOverlayMsg');
      var b = e.target.querySelector ? e.target.querySelector('.sync-btn') : null;
      if (!o) return;
      sessionStorage.setItem('__e2e_sync', JSON.stringify({
        display: getComputedStyle(o).display, width: o.getBoundingClientRect().width,
        btnClass: b ? b.className : '', msg: m ? m.textContent : '' }));
    } catch (err) {}
  }, 60);
}, false);
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerHandle:
    """Flask app in a subprocess (own process => real HTTP, real threading, server log on disk)."""

    def __init__(self, workdir: str, port: Optional[int] = None, seed: bool = True, real_coros: bool = False,
                 sync_delay: float = 3.0) -> None:
        os.makedirs(workdir, exist_ok=True)
        self.workdir = workdir
        self.port = port or free_port()
        self.db_path = os.path.join(workdir, "e2e.db")
        self.log_path = os.path.join(workdir, "app.log")
        self.mode_file = os.path.join(workdir, "coros_mode.txt")
        self.stdout_path = os.path.join(workdir, "server_stdout.log")
        self.seed_on_start = seed
        self.real_coros = real_coros
        self.sync_delay = sync_delay
        self.proc: Optional[subprocess.Popen] = None
        self.base_url = f"http://127.0.0.1:{self.port}"

    def set_coros_mode(self, mode: str) -> None:
        with open(self.mode_file, "w", encoding="utf-8") as f:
            f.write(mode)

    def start(self, timeout: float = 45.0) -> "ServerHandle":
        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1", "PYTHONPATH": ROOT, "COACH_LOG_FILE": self.log_path,
            "COACH_E2E_MODE_FILE": self.mode_file, "COACH_E2E_SYNC_DELAY": str(self.sync_delay),
            "DATABASE_PATH": self.db_path, "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
        })
        self.set_coros_mode("ok")
        cmd: List[str] = [sys.executable, "-m", "tests.e2e.server_main", "--db", self.db_path, "--port", str(self.port)]
        if self.seed_on_start:
            cmd.append("--seed")
        if self.real_coros:
            cmd.append("--real-coros")
        out = open(self.stdout_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"e2e server exited early (code {self.proc.returncode}); see {self.stdout_path}\n"
                                   + open(self.stdout_path, encoding="utf-8", errors="replace").read()[-3000:])
            try:
                urllib.request.urlopen(self.base_url + "/", timeout=2).read()
                return self
            except Exception:
                time.sleep(0.3)
        self.stop()
        raise RuntimeError(f"e2e server did not start within {timeout}s; see {self.stdout_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def launch_browser(playwright, headless: bool = True, channel: Optional[str] = None, slow_mo: int = 0,
                   args: Optional[List[str]] = None):
    """Prefer the installed Google Chrome (channel='chrome'); fall back to bundled Chromium."""
    kw = dict(headless=headless, slow_mo=slow_mo, args=args or [])
    order = [channel] if channel else ["chrome", None]
    last: Optional[Exception] = None
    for ch in order:
        try:
            return playwright.chromium.launch(channel=ch, **kw) if ch else playwright.chromium.launch(**kw)
        except Exception as err:  # channel not installed
            last = err
    raise RuntimeError(f"could not launch Chrome or Chromium: {last}")


def install_offline_stubs(context) -> None:
    """Serve CDN Chart.js and Google Fonts locally so tests are offline-deterministic."""
    def chart(route):
        route.fulfill(status=200, content_type="application/javascript", body=CHART_STUB)

    def empty_css(route):
        route.fulfill(status=200, content_type="text/css", body="")

    context.add_init_script(SUBMIT_RECORDER)
    context.route("**://cdn.jsdelivr.net/**", chart)
    context.route("**://fonts.googleapis.com/**", empty_css)
    context.route("**://fonts.gstatic.com/**", lambda r: r.fulfill(status=200, body=""))
