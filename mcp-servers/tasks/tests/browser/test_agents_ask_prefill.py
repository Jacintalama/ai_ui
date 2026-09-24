"""Arriving at the agents page with something to ask.

The Agent Office lists what each agent can be asked for, because 67 skills
ship with the image and the only place one was ever visible is a collapsed
section of the edit form. Those are links, so the page they land on has to do
something with what they carry.

It fills the box and stops. It does NOT send: a turn costs money, and a
message the person never read being sent on their behalf is worse than one
more click.
"""
import http.server
import json
import pathlib
import threading
import urllib.parse

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
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _open(browser, server, query=""):
    pg = browser.new_page(viewport={"width": 1400, "height": 950})
    pg.set_default_timeout(6000)
    sent = []

    def route(r):
        if r.request.method == "POST":
            sent.append(r.request.url)
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"items": [], "total": 0}))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html%s" % (server.server_address[1], query))
    pg.wait_for_selector(".ap-composer input[name=message]", state="attached")
    pg.wait_for_timeout(350)
    pg.sent = sent
    return pg


def test_the_message_lands_in_the_box(browser, server):
    q = "?ask=" + urllib.parse.quote("Ada, weekly review")
    pg = _open(browser, server, q)
    try:
        assert pg.input_value(".ap-composer input[name=message]") == "Ada, weekly review"
    finally:
        pg.close()


def test_it_is_not_sent_for_them(browser, server):
    """A turn costs money and can run tools. Arriving on a page must never
    spend that on somebody's behalf."""
    q = "?ask=" + urllib.parse.quote("Ada, weekly review")
    pg = _open(browser, server, q)
    try:
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_arriving_with_nothing_leaves_the_box_empty(browser, server):
    pg = _open(browser, server)
    try:
        assert pg.input_value(".ap-composer input[name=message]") == ""
    finally:
        pg.close()


def test_the_url_is_tidied_so_a_reload_does_not_refill(browser, server):
    """Left in place, F5 would put the message back after the person cleared
    it, and a link shared from the address bar would carry somebody else's
    question."""
    q = "?ask=" + urllib.parse.quote("Ada, weekly review")
    pg = _open(browser, server, q)
    try:
        assert "ask=" not in pg.url, pg.url
    finally:
        pg.close()
