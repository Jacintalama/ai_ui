"""Closing the App Builder pane must take a deliberate action.

Reported 2026-08-20 with a screenshot: the user was in App Builder with a live
preview running, clicked the sidebar collapse control, and was dropped on a
blank chat with the pane gone and the address bar back at the root.

The cause was a blanket handler — ANY click outside the pane closed it:

    document.addEventListener("click", (e) => {
      if (!isOpen()) return;
      if (wrap.contains(t)) return;
      if (t.closest(NAV_EMBED_SELECTOR)) return;
      closeAiuiEmbed();
    }, true);

The pane is a full work surface — a running preview, an unsent prompt in the
build box — not a dropdown, and it should not be dismissed by a stray click on
the surrounding chrome.

The rule is: a LINK navigates, so following one legitimately leaves the pane;
a BUTTON is chrome, so it must not. The X and Escape remain the deliberate
ways out.

Reported AGAIN on 2026-08-24, unchanged. Two things were wrong and only one
of them was the browser:

1. The fix was never on the server. The repo had it; the host copy, the
   container copy and the bytes served over HTTPS did not. The follow-up
   commit bumped the cache-busting query on a file that had not been
   uploaded, so the version string changed and the code did not.

2. This file could not have caught a bad rule anyway. Its fixture invented
   the chrome: one lone button in the opposite corner of the page, nowhere
   near a link. The real sidebar puts a 30px button flush against an
   `a[href="/"]` that carries `flex flex-1` and eats the rest of the row —
   and "/" is the dashboard the user kept landing on. A link-based rule has
   to be tested next to a link, or the test only says isolated buttons work.

So the fixture is now the real markup from Open WebUI v0.11.0's
Sidebar.svelte, and these run over HTTP rather than file:// so that
history.pushState actually applies and the address bar can be asserted. The
address bar is the thing the user reported; pane presence alone was never
the whole symptom.
"""
import functools
import http.server
import pathlib
import shutil
import socketserver
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"

#: The pane pushes this while it is open. Landing back on "/" is the bug.
PANE_URL = "/cronjobs"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102 - keep pytest output readable
        pass


@pytest.fixture()
def page(tmp_path_factory):
    """A real origin, so pushState applies and location.pathname is truthful.

    file:// silently swallows the pushState this pane depends on, which is
    how a URL bug hid behind four passing tests.
    """
    work = tmp_path_factory.mktemp("dismiss")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    shutil.copy(HERE / "shell_with_chrome.html", work / "index.html")

    handler = functools.partial(_Quiet, directory=str(work))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            httpd.shutdown()
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page()
        pg.goto(base)
        pg.wait_for_selector("[data-aiui-cron-jobs]", timeout=8000)
        pg.locator("[data-aiui-cron-jobs]").click()
        pg.wait_for_selector(OPEN_PANE, timeout=5000)
        yield pg
        browser.close()
    httpd.shutdown()


def test_the_pane_owns_the_address_bar_while_it_is_open(page):
    """Guards every URL assertion below from passing vacuously."""
    assert page.evaluate("location.pathname") == PANE_URL


def test_collapsing_the_sidebar_does_not_dismiss_the_pane(page):
    """The exact reported action: collapse the sidebar while working."""
    page.locator("#sidebar-toggle").click()
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 1, (
        "collapsing the sidebar closed the pane — a running preview and an "
        "unsent prompt are lost to a click on the chrome")


def test_collapsing_the_sidebar_does_not_return_to_the_dashboard(page):
    """The symptom in the user's own words: "its back to dashboard"."""
    page.locator("#sidebar-toggle").click()
    page.wait_for_timeout(400)
    assert page.evaluate("location.pathname") == PANE_URL, (
        "collapsing the sidebar rewound the address bar to the previous page, "
        "which is the dashboard the user keeps being thrown back to")


def test_clicking_the_glyph_inside_the_button_is_also_chrome(page):
    """The click usually lands on the icon, not the button, so the rule has
    to survive closest() walking up through the nested element."""
    page.locator("#toggle-glyph").click()
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 1, (
        "clicking the icon inside the collapse button closed the pane, so the "
        "rule only holds when the button itself is the exact click target")


def test_the_home_link_beside_it_still_dismisses_the_pane(page):
    """The adjacent `a[href="/"]`. Following a link genuinely leaves, so the
    pane must not stay covering the dashboard it went to."""
    page.locator("#home-link").click()
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 0, (
        "clicking the home link left the pane covering the page it went to")


def test_escape_still_closes(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 0, "Escape stopped closing the pane"


def test_clicking_inside_the_pane_never_closes_it(page):
    page.locator("[data-aiui-embed]").click(position={"x": 5, "y": 5})
    page.wait_for_timeout(300)
    assert page.locator(OPEN_PANE).count() == 1
