"""The Publish button under a chat reply opens the App Builder (2026-11-16).

Live on 2026-11-13 the main chat answered "how do I put my landing page
online" with "open the App Builder and click Publish" and nothing to click.
The service now puts `[Publish in App Builder](#aiui-open:app-builder)`
under that answer (app_triage.with_buttons), integrations-ui.js turns the
link into a button, and the button asks the shell (task-panel.js,
`window.aiuiOpenPane`) to open the App Builder in its pane exactly as its
sidebar entry would. Where there is no shell, it opens the page in a tab.

Two halves, each against the real file:
  * the shell: sidebar_collapsed_rail.html (the live DOM) with the real
    task-panel.js, as test_open_pane_message.py runs it;
  * the button: the real section of integrations-ui.js, cut out by its
    section markers, on a page holding one reply's link.
"""
import functools
import http.server
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
UI_JS = HERE.parents[2] / "gdrive" / "integrations-ui.js"
OPEN_PANE = "[data-aiui-embed][data-open]"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = b"<!doctype html><title>pane</title>", "text/html"
        else:
            body, ctype = (HERE / "sidebar_collapsed_rail.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def shell(browser, server):
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(f"http://127.0.0.1:{server}/")
    pg.wait_for_selector("#sidebar [data-aiui-office]", timeout=8000)
    yield pg
    pg.close()


# --- the shell ------------------------------------------------------------------

def test_the_shell_opens_the_app_builder_pane_when_asked(shell):
    assert shell.evaluate("() => window.aiuiOpenPane('/app-builder')") is True
    shell.wait_for_selector(OPEN_PANE, timeout=4000)
    shell.wait_for_function("() => location.pathname === '/app-builder'", timeout=4000)
    shown = shell.evaluate(
        "Array.from(document.querySelectorAll('[data-aiui-embed] iframe'))"
        ".filter(f => f.style.display !== 'none').map(f => f.getAttribute('src'))")
    assert len(shown) == 1 and shown[0].startswith("/tasks/app-builder"), shown


def test_the_shell_opens_nothing_it_does_not_know(shell):
    for path in ("/nowhere", "javascript:alert(1)", "", None, 42):
        assert shell.evaluate("p => window.aiuiOpenPane(p)", path) is False
    assert shell.locator(OPEN_PANE).count() == 0


# --- the button -----------------------------------------------------------------

def _section():
    src = UI_JS.read_text(encoding="utf-8")
    start = src.index("  // ===== The assistant's open links =====")
    end = src.index("  function wireAiuiConnectLinks()")
    return src[start:end]


def _reply_page(browser, href, with_shell):
    pg = browser.new_page()
    pg.set_content(
        '<div class="chat-assistant"><p>Click Publish.</p>'
        '<p><a href="%s">Publish in App Builder</a></p></div>' % href)
    pg.evaluate("""(withShell) => {
        window.__opened = []; window.__panes = [];
        window.open = function (u, t, f) { window.__opened.push([u, t, f]); return {}; };
        if (withShell) window.aiuiOpenPane = function (p) { window.__panes.push(p); return true; };
    }""", with_shell)
    pg.add_script_tag(content=_section() + "\nwindow.__wire = wireAiuiOpenLink;")
    pg.evaluate("() => document.querySelectorAll('a').forEach(a => window.__wire(a))")
    return pg


def test_the_link_becomes_a_button_that_opens_the_pane(browser):
    pg = _reply_page(browser, "#aiui-open:app-builder", with_shell=True)
    try:
        btn = pg.locator(".aiui-open-inline button")
        assert btn.inner_text() == "Publish in App Builder"
        btn.click()
        assert pg.evaluate("() => window.__panes") == ["/app-builder"]
        assert pg.evaluate("() => window.__opened") == []
    finally:
        pg.close()


def test_without_the_shell_it_opens_the_page_in_a_tab(browser):
    pg = _reply_page(browser, "#aiui-open:app-builder", with_shell=False)
    try:
        pg.locator(".aiui-open-inline button").click()
        opened = pg.evaluate("() => window.__opened")
        assert len(opened) == 1 and opened[0][0].endswith("/app-builder"), opened
        assert opened[0][1] == "_blank"
    finally:
        pg.close()


def test_a_place_not_on_the_list_stays_a_plain_link(browser):
    for href in ("#aiui-open:cronjobs", "#aiui-open:javascript:alert(1)",
                 "#aiui-open:", "#aiui-open:__proto__"):
        pg = _reply_page(browser, href, with_shell=True)
        try:
            assert pg.locator(".aiui-open-inline").count() == 0, href
            assert pg.locator("a").count() == 1, href
        finally:
            pg.close()
