"""The admin tasks launcher: top right, out of a pane's way, and hideable.

"remove or hide the task in the right bottom of the page that is floating..
instead of bottom right corner it will put top right corner instead so its
clean and can chat in the office" (2026-10-16). The launcher sat on the chat
composer and the office's buttons. Now it is top right, it is hidden while
an AIUI pane is open (the pane has its own top-right controls), and the
panel's header has a button that hides it for good per browser; the Tasks
entry in the + menu still opens the panel.

Same shell as test_open_pane_message.py (the live v0.11.4 sidebar DOM), with
the auth route answered as an admin so the launcher is drawn at all.
"""
import functools
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
STUB = b"<!doctype html><html><body>stub pane</body></html>"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
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
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    # The panel asks who is signed in only when Open WebUI has left a token.
    pg.add_init_script("try { localStorage.setItem('token', 'test-token'); } catch (e) {}")

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            r.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"id": "u1", "email": "me@example.com",
                                       "name": "Me", "role": "admin"}))
        elif "/api/" in url:
            r.fulfill(status=200, content_type="application/json", body="[]")
        else:
            r.continue_()

    pg.route("**/api/**", route)
    pg.goto(f"http://127.0.0.1:{server}/")
    pg.wait_for_selector("#sidebar [data-aiui-office]", timeout=8000)
    pg.wait_for_selector(".aiui-tp-fab:not(.hidden)", timeout=8000)
    yield pg
    pg.close()


def test_the_launcher_sits_top_right(page):
    got = page.locator(".aiui-tp-fab").evaluate(
        "el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();"
        " return { top: s.top, bottom: s.bottom, y: r.top, right: innerWidth - r.right }; }")
    # Within the top-right corner of the window, not the bottom.
    assert got["y"] < 60 and got["right"] < 60, got


def test_the_launcher_hides_while_a_pane_is_open(page):
    fab = page.locator(".aiui-tp-fab")
    assert fab.is_visible()
    page.locator("#sidebar [data-aiui-office]").click()
    page.wait_for_selector("[data-aiui-embed][data-open]", timeout=4000)
    page.wait_for_timeout(100)
    assert fab.is_hidden()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert fab.is_visible()


def test_hide_button_is_remembered_and_the_panel_still_opens(page):
    page.locator(".aiui-tp-fab").click()
    page.wait_for_selector(".aiui-tp:not(.hidden)", timeout=4000)
    page.locator('.aiui-tp [data-act="hide-fab"]').click()
    page.locator('.aiui-tp [data-act="close"]').click()
    page.wait_for_timeout(100)
    assert page.locator(".aiui-tp-fab").is_hidden()
    page.reload()
    page.wait_for_selector("#sidebar [data-aiui-office]", timeout=8000)
    page.wait_for_timeout(600)
    assert page.locator(".aiui-tp-fab").is_hidden()
    # The panel itself is still there to open, and can bring the button back.
    page.evaluate("() => { const b = document.querySelector('.aiui-tp-fab'); b.classList.remove('hidden'); b.click(); }")
    page.wait_for_selector(".aiui-tp:not(.hidden)", timeout=4000)
    assert "Show button" in page.locator('.aiui-tp [data-act="hide-fab"]').inner_text()
    page.locator('.aiui-tp [data-act="hide-fab"]').click()
    page.locator('.aiui-tp [data-act="close"]').click()
    page.wait_for_timeout(100)
    assert page.locator(".aiui-tp-fab").is_visible()
