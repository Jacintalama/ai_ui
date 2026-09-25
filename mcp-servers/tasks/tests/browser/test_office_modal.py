"""Watching the office while you ask.

"i want this to be a modal to be able to see in here... like if user ask
something to a specific agent user can view the office and see the agent
doing... or call a meeting, user can able to see everything."

So the office opens over the chat rather than being somewhere you navigate
away to. The point is to keep the conversation and the floor on screen at once
while a round runs: the office polls /agents/activity every five seconds, so
whoever is answering lights up while you watch.
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
    assert page.locator("#office-overlay").is_hidden()
    assert page.locator("#office-overlay iframe").count() == 0


def test_opening_it_shows_the_office_over_the_chat(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(200)
    assert page.locator("#office-overlay").is_visible()
    src = page.locator("#office-overlay iframe").get_attribute("src")
    assert src.startswith("/tasks/office"), src


def test_the_conversation_is_still_there_underneath(page):
    """The whole point of a modal rather than a link: you asked something and
    you want to watch it happen without losing what you typed."""
    page.fill(".ap-composer input[name=message]", "everyone answer: status")
    page.locator("#office-open").click()
    page.wait_for_timeout(200)
    assert page.input_value(".ap-composer input[name=message]") == "everyone answer: status"


def test_escape_closes_it(page):
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.locator("#office-overlay").is_hidden()


def test_reopening_keeps_the_same_frame(page):
    """Rebuilding the frame on every open reloads the whole office and throws
    away what it had already drawn, which is the opposite of watching."""
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    page.evaluate("document.querySelector('#office-overlay iframe').dataset.seen = '1'")
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    assert page.locator("#office-overlay iframe").get_attribute("data-seen") == "1"
    assert page.locator("#office-overlay iframe").count() == 1
