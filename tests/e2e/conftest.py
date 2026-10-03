"""Fixtures for the browser end-to-end suite.

* ``server``   - Flask app in a subprocess on a free port, temp SQLite DB, COROS/Gemini stubbed.
* ``page``     - Chrome page (CDP attached) with a PageObserver; unexpected console/network/page
                 errors fail the test.  Server log problems (ERROR/Traceback/5xx) fail it too.
* Failure artifacts (screenshots, Playwright trace, issue list) go to tests/e2e/artifacts/.

E2E tests only run when tests/e2e is targeted explicitly (or E2E=1), so the normal unit
suite stays fast and browser-free.
"""
import os
import re
import shutil
import sys
from typing import List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.e2e.harness import ServerHandle, install_offline_stubs, launch_browser  # noqa: E402
from tests.e2e.log_checker import LogChecker  # noqa: E402
from tests.e2e.observer import PageObserver  # noqa: E402
from tests.e2e.seed import seed  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS = os.path.join(HERE, "artifacts")


# ------------------------------------------------------------------ opt-in gating
def _e2e_requested(config) -> bool:
    if os.environ.get("E2E") == "1":
        return True
    return any("e2e" in str(a).replace("\\", "/") for a in config.args)


def pytest_collection_modifyitems(config, items):
    if _e2e_requested(config):
        return
    skip = pytest.mark.skip(reason="e2e suite is opt-in: run `pytest tests/e2e` (or set E2E=1)")
    for item in items:
        if "tests/e2e" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)


# ---------------------------------------------------------- outcome -> guard hook
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        guards = getattr(item, "_e2e_guards", [])
        if rep.passed:
            problems: List[str] = []
            for g in guards:
                problems.extend(g())
            if problems:
                rep.outcome = "failed"
                rep.longrepr = "Unexpected errors were recorded during this test:\n  - " + "\n  - ".join(problems)
                item._e2e_problems = problems
        setattr(item, "rep_call", rep)


# ---------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def server(tmp_path_factory):
    handle = ServerHandle(str(tmp_path_factory.mktemp("e2e_server"))).start()
    yield handle
    handle.stop()


@pytest.fixture(scope="session")
def base_url(server):
    return server.base_url


@pytest.fixture(scope="session")
def playwright_instance():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def chrome(playwright_instance, pytestconfig):
    headed = bool(pytestconfig.getoption("headed", default=False)) or os.environ.get("E2E_HEADED") == "1"
    channel = pytestconfig.getoption("browser_channel", default=None) or os.environ.get("E2E_CHANNEL")
    slowmo = int(pytestconfig.getoption("slowmo", default=0) or 0)
    browser = launch_browser(playwright_instance, headless=not headed, channel=channel, slow_mo=slowmo)
    yield browser
    browser.close()


@pytest.fixture(autouse=True)
def fresh_state(request, server):
    """Re-seed the temp DB and reset the COROS stub before every test; guard the server log."""
    seed(server.db_path)
    server.set_coros_mode("ok")
    checker = LogChecker(server.log_path)
    allow = [p for m in request.node.iter_markers("allow_errors") for p in m.args]
    guards = []

    def log_guard():
        return ["server log: " + b for b in checker.problems_since(allow=allow)]

    guards.append(log_guard)
    request.node._e2e_guards = guards
    request.node._e2e_allow = allow
    request.node._e2e_observers = []
    yield checker


def _new_context(request, chrome, server, **kw):
    ctx = chrome.new_context(base_url=server.base_url, **kw)
    ctx.set_default_timeout(10_000)
    install_offline_stubs(ctx)
    ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
    observer = PageObserver(allow=request.node._e2e_allow)
    observer.attach_context(ctx)
    request.node._e2e_observers.append(observer)
    request.node._e2e_guards.append(lambda: ["browser: " + str(i) for i in observer.unexpected()])
    return ctx, observer


def _finish_context(request, ctx, observer):
    rep = getattr(request.node, "rep_call", None)
    failed = bool(rep and rep.failed) or bool(rep is None)
    safe = re.sub(r"[^\w.-]+", "_", request.node.nodeid)
    if failed:
        os.makedirs(ARTIFACTS, exist_ok=True)
        for n, pg in enumerate(ctx.pages):
            try:
                pg.screenshot(path=os.path.join(ARTIFACTS, f"{safe}_{n}.png"), full_page=True)
            except Exception:
                pass
        with open(os.path.join(ARTIFACTS, f"{safe}_issues.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(str(i) for i in observer.issues) or "(no browser issues recorded)")
            f.write("\n\nPROBLEMS:\n" + "\n".join(getattr(request.node, "_e2e_problems", [])))
        try:
            ctx.tracing.stop(path=os.path.join(ARTIFACTS, f"{safe}_trace.zip"))
        except Exception:
            pass
    else:
        try:
            ctx.tracing.stop()
        except Exception:
            pass
    ctx.close()


@pytest.fixture
def observer_ctx(request, chrome, server):
    ctx, observer = _new_context(request, chrome, server)
    yield ctx, observer
    _finish_context(request, ctx, observer)


@pytest.fixture
def observer(observer_ctx):
    return observer_ctx[1]


@pytest.fixture
def page(observer_ctx):
    ctx, _ = observer_ctx
    return ctx.new_page()


@pytest.fixture
def mobile_page(request, chrome, server):
    ctx, observer = _new_context(request, chrome, server, viewport={"width": 390, "height": 844},
                                 device_scale_factor=2, is_mobile=True, has_touch=True)
    yield ctx.new_page()
    _finish_context(request, ctx, observer)


@pytest.fixture(scope="session", autouse=True)
def _clean_artifacts_dir():
    shutil.rmtree(ARTIFACTS, ignore_errors=True)
    yield
