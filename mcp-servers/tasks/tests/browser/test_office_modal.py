"""Watching the office while you ask.

"i want this to be a modal to be able to see in here... like if user ask
something to a specific agent user can view the office and see the agent
doing... or call a meeting, user can able to see everything."

"insteaD THE OFFICE IS NEW PAGE CAN YOU PUT IT INSIDE THE AGENT PAGE WHERE
ITS POPUP THAT CAN RESIZE IN THERE SO USER CAN ALSO SEE AGENTS THERE FLOATING"

So it is a floating window, not a modal. A modal blocks the page behind it,
which is exactly wrong here: the point is to keep typing while the floor is
up. It can be dragged and resized, and where it was put is remembered, because
a window you have to place again every time is one you stop opening.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def server():
    html = (STATIC / "agents.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            body = html if self.path.startswith("/agents") else b"<!doctype html><title>office</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    def route(r):
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"items": [], "total": 0}))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.wait_for_selector("#office-open", state="attached")
    pg.wait_for_timeout(250)
    yield pg
    pg.close()


def test_the_chat_offers_the_office(page):
    assert page.locator("#office-open").count() == 1


def test_the_office_is_closed_until_asked_for(page):
    """It is a whole second page in a frame. Loading it for everybody who
    opens the chat spends a fetch nobody asked for."""
    assert page.locator("#office-window").is_hidden()
    assert page.locator("#office-window iframe").count() == 0


def test_opening_it_floats_the_office_over_the_page(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(200)
    win = page.locator("#office-window")
    assert win.is_visible()
    src = page.locator("#office-window iframe").get_attribute("src")
    assert src.startswith("/tasks/office"), src
    assert win.evaluate("el => getComputedStyle(el).position") == "fixed"


def test_it_does_not_block_the_page_behind_it(page):
    """The difference between a floating window and a modal, and the whole
    reason for the change: a backdrop over the chat would stop the typing
    this exists to accompany."""
    page.locator("#office-open").click()
    page.wait_for_timeout(200)
    page.fill(".ap-composer input[name=message]", "everyone answer: status")
    assert page.input_value(".ap-composer input[name=message]") == "everyone answer: status"
    assert page.locator(".modal-overlay#office-window").count() == 0


def test_it_can_be_resized(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    assert page.locator("#office-window").evaluate(
        "el => getComputedStyle(el).resize") == "both"


def test_it_can_be_dragged_by_its_header(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    before = page.locator("#office-window").bounding_box()
    head = page.locator("#office-drag").bounding_box()
    page.mouse.move(head["x"] + 40, head["y"] + 10)
    page.mouse.down()
    page.mouse.move(head["x"] + 40 - 120, head["y"] + 10 + 60, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    after = page.locator("#office-window").bounding_box()
    assert abs(after["x"] - before["x"]) > 40, (before, after)


def test_where_you_put_it_is_remembered(page):
    """A window you have to place again every time is one you stop opening.
    Per-viewer convenience, so localStorage is the right home for it, and it
    is read in a try/catch because a private window throws."""
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    head = page.locator("#office-drag").bounding_box()
    page.mouse.move(head["x"] + 40, head["y"] + 10)
    page.mouse.down()
    page.mouse.move(head["x"] + 40 - 150, head["y"] + 10 + 80, steps=8)
    page.mouse.up()
    page.wait_for_timeout(200)
    saved = page.evaluate("() => localStorage.getItem('aiuiOfficeWindow')")
    assert saved and "left" in saved, saved


def test_the_close_button_puts_it_away(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    page.locator("#office-close").click()
    page.wait_for_timeout(150)
    assert page.locator("#office-window").is_hidden()


def test_reopening_keeps_the_same_frame(page):
    """Rebuilding the frame on every open reloads the whole office and throws
    away what it had already drawn, which is the opposite of watching."""
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    page.evaluate("document.querySelector('#office-window iframe').dataset.seen = '1'")
    page.locator("#office-close").click()
    page.wait_for_timeout(120)
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    assert page.locator("#office-window iframe").get_attribute("data-seen") == "1"
    assert page.locator("#office-window iframe").count() == 1
