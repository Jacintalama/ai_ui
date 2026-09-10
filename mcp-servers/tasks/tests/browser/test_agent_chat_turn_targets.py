"""The turn targets, resolved against a real DOM in a real browser.

A substring check passed while these selectors matched nothing. The first
version of turn_body_target/turn_status_target was
`#agent-thread .aturn:last-child .aturn-body`, and `"aturn-body" in html`
kept passing right through the change that broke it: the send response for
the first message in a conversation is turn_open + turn_close +
stream_block(), all appended by ONE beforeend swap, which makes the stream
block a SIBLING of the turn rather than something inside it. The stream
block comes second, so it is the stream block that ends up last, not the
turn, and `:last-child` stopped matching the turn at all. A queued message
made it worse: its own turn arrives later, also as a sibling, so whichever
turn is newest keeps stealing :last-child from the one a round is still
answering.

The fix moved to an id per turn (`#aturn-{id}`) and an out-of-band swap that
names its turn explicitly instead of relying on DOM position. This resolves
that selector shape in Chromium against the actual HTML this module's
functions produce, the way htmx's own getTarget does, rather than checking
for a substring that can be present while the selector as a whole matches
nothing.
"""
import http.server
import pathlib
import sys
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
sys.path.insert(0, str(ROOT))
import agent_chat_render as render                        # noqa: E402


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


PAGE = """<!doctype html>
<html><body>
<div id="agent-thread"></div>
<script src="/vendor/htmx.min.js"></script>
<script src="/vendor/sse.js"></script>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the minimal page, the two vendored scripts htmx needs, and
    (when set) a canned SSE stream at /stream."""

    sse_body = b""

    def do_GET(self):                                        # noqa: N802
        if self.path == "/panel.html":
            self._send(200, "text/html", PAGE.encode("utf-8"))
        elif self.path in ("/vendor/htmx.min.js", "/vendor/sse.js"):
            fname = self.path.rsplit("/", 1)[-1]
            self._send(200, "application/javascript",
                      (STATIC / "vendor" / fname).read_bytes())
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(self.sse_body)
            self.wfile.flush()
        else:
            self.send_response(404)
            self.end_headers()

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server(browser):
    _Handler.sse_body = b""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page()
    pg.set_default_timeout(5000)
    pg.goto("http://127.0.0.1:%d/panel.html" % server.server_address[1])
    yield pg
    pg.close()


def _append_beforeend(page, html):
    """What htmx does for the composer's hx-swap="beforeend": insert the raw
    HTML fragment as new children at the end of #agent-thread. Faithful for
    a non-oob top-level fragment, which is exactly what the send route
    returns for a first message."""
    page.evaluate(
        "(html) => { document.getElementById('agent-thread')"
        ".insertAdjacentHTML('beforeend', html); }", html)


def test_the_first_turns_targets_resolve_to_exactly_one_element(page):
    """What the send route returns for the first message in a conversation:
    a turn immediately followed by the stream block, as siblings under
    #agent-thread. TURN_BODY_TARGET's :last-child predecessor matched zero
    elements here, because .astream (the stream block), not .aturn (the
    turn), is what ends up last."""
    tid = "abc123def456"
    fragment = (render.turn_open("hi", tid) + render.turn_close()
               + render.stream_block())
    _append_beforeend(page, fragment)
    assert page.locator(render.turn_body_target(tid)).count() == 1
    assert page.locator(render.turn_status_target(tid)).count() == 1


def test_an_earlier_turns_targets_still_resolve_once_a_newer_one_exists(page):
    """A queued message's turn arrives later as a further sibling, out of
    band, exactly like a real queued send. The first turn's own targets
    must still resolve to exactly one element apiece: this is the shape
    that made a position-based selector answer the wrong turn, because
    :last-child moves to whichever turn is newest regardless of which one a
    round in flight is actually answering."""
    first_id, second_id = "aaa111aaa111", "bbb222bbb222"
    _append_beforeend(page, render.turn_open("one", first_id)
                            + render.turn_close() + render.stream_block())
    _append_beforeend(page, render.turn_open("two", second_id)
                            + render.turn_close())

    assert page.locator(render.turn_body_target(first_id)).count() == 1
    assert page.locator(render.turn_status_target(first_id)).count() == 1
    assert page.locator(render.turn_body_target(second_id)).count() == 1
    # Not each other's element. A selector that matched two would be just as
    # wrong as one that matches zero: the answer would land in both turns,
    # or htmx would refuse the ambiguous target outright.
    body_first = page.locator(render.turn_body_target(first_id)).element_handle()
    body_second = page.locator(render.turn_body_target(second_id)).element_handle()
    assert body_first != body_second


def test_an_answer_reaches_the_turn_it_names_through_a_real_sse_swap(server, page):
    """The full path, not just the selector: a real vendored htmx + sse
    extension, in a real browser, processing an actual SSE stream whose
    events carry into_turn/turn_status-wrapped fragments the way
    routes_agent_chat._run_round really yields them. Proves the out-of-band
    swap this fix relies on actually places content where the id says,
    rather than only proving the CSS selector resolves in isolation."""
    tid = "abc123def456"
    first_turn = render.turn_open("hi", tid) + render.turn_close()
    stream = render.stream_block()
    answer = render.into_turn(tid, '<div class="am agent">hello there</div>')
    status = render.turn_status(tid, "")

    sse = (("event: message\ndata: %s\n\n" % answer)
          + ("event: working\ndata: %s\n\n" % status)
          + "event: close\ndata: \n\n")
    _Handler.sse_body = sse.encode("utf-8")

    _append_beforeend(page, first_turn + stream)
    # Wires the vendored sse extension up to the canned stream the same way
    # stream_block's own hx-ext/sse-connect attributes would, since this
    # page never ran the real /tasks/agents/chat/send route that would
    # normally have put them there already.
    page.evaluate(
        """() => {
          var el = document.querySelector('.astream');
          el.setAttribute('sse-connect', '/stream');
          htmx.process(el);
        }""")
    page.wait_for_selector("%s .am.agent" % render.turn_body_target(tid))
    body_html = page.locator(render.turn_body_target(tid)).inner_html()
    assert "hello there" in body_html
