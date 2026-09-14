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
    # or htmx would refuse the ambiguous target outright. Checked with the
    # browser's own node identity (===), not by comparing two Python
    # ElementHandle objects: that class has no __eq__ of its own, so two
    # handles are never equal to each other even when they wrap the exact
    # same node, and the comparison would pass no matter what it pointed at.
    same_node = page.evaluate(
        "([a, b]) => document.querySelector(a) === document.querySelector(b)",
        [render.turn_body_target(first_id), render.turn_body_target(second_id)])
    assert not same_node


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


# --- the sseClose fallback clears the turn, not the sink beneath it --------

# static/agent-chat.js's htmx:sseClose handler used to clear .awork, which
# looked right (that WAS where the working line's own sse-swap sink lived)
# right up until the working line stopped being delivered there. Since
# into_turn/turn_status wrap every streamed fragment out of band, htmx pulls
# that content out of the sink and places it at the turn's own id before the
# sink's own swap ever runs, so .awork is unconditionally empty and
# `querySelector(".awork").innerHTML = ""` clears nothing, ever. The gap
# this leaves: a connection that drops and reconnects lands on the stream
# route with the tail no longer "user", which closes immediately with no
# round and no clearing "working" event, and "X is working..." stays pinned
# on that turn's status row until the page is reloaded.
#
# Only a real DOM, a real close event and a held-open connection (to arrive
# AFTER the working line is already on screen, the way a real drop does)
# can tell "cleared the status row" from "cleared nothing": a substring
# check on static/agent-chat.js's source, the shape every prior check in
# this suite used, cannot see where an already-rendered line actually goes
# when the handler runs.

class _CloseHandler(http.server.BaseHTTPRequestHandler):
    """Serves the real, on-disk static/agent-chat.js (not a copy), so this
    test breaks the moment that file's fix reverts, and a held-open /stream
    that only sends its close event once told to, so the working line can
    be observed on screen before the close arrives."""

    sse_body = b""
    close_now: threading.Event

    def do_GET(self):                                        # noqa: N802
        if self.path == "/panel.html":
            self._send(200, "text/html", _CLOSE_PAGE.encode("utf-8"))
        elif self.path in ("/vendor/htmx.min.js", "/vendor/sse.js"):
            fname = self.path.rsplit("/", 1)[-1]
            self._send(200, "application/javascript",
                      (STATIC / "vendor" / fname).read_bytes())
        elif self.path == "/agent-chat.js":
            self._send(200, "application/javascript",
                      (STATIC / "agent-chat.js").read_bytes())
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(self.sse_body)
            self.wfile.flush()
            self.close_now.wait(10)
            self.wfile.write(b"event: close\ndata: \n\n")
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


_CLOSE_PAGE = """<!doctype html>
<html><body>
<div class="agents-layout"><div id="agent-thread"></div></div>
<script src="/vendor/htmx.min.js"></script>
<script src="/vendor/sse.js"></script>
<script src="/agent-chat.js"></script>
</body></html>"""


def test_sse_close_clears_the_turns_status_row_not_the_empty_sink(browser):
    """Adapted from a verification harness written during review
    (scratchpad/verify_sseclose.py), turned into a permanent regression
    test: the exact check shape that let this ship broken twice
    (substring checks on agent-chat.js's source in test_agent_chat_page.py)
    would not notice a revert of the fix, so only a real DOM run can.

    Two turns are on screen: t1 has a live working line and a finished
    answer already in its body (so the test can tell "cleared the status
    row" from "cleared the whole turn"); t2 has neither, and stays untouched
    throughout, proving the clear is not indiscriminate.
    """
    t1, t2 = "aaa111aaa111", "bbb222bbb222"
    _CloseHandler.sse_body = (
        "event: working\ndata: %s\n\n"
        % render.turn_status(t1, render.working("Mia"))).encode("utf-8")
    _CloseHandler.close_now = threading.Event()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CloseHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        pg = browser.new_page()
        pg.set_default_timeout(8000)
        pg.goto("http://127.0.0.1:%d/panel.html" % srv.server_address[1])

        # Exactly what agent_chat_send returns for a first message (t1) and
        # a queued one (t2): a turn + stream block, then a second turn out
        # of band after it.
        _append_beforeend(pg, render.turn_open("what is in my inbox?", t1)
                              + render.turn_close() + render.stream_block())
        _append_beforeend(pg, render.turn_open("and my calendar?", t2)
                              + render.turn_close())
        pg.evaluate(
            "([sel, html]) => document.querySelector(sel)"
            ".insertAdjacentHTML('beforeend', html)",
            [render.turn_body_target(t1),
             render.agent_bubble("Mia", "here is your inbox")])
        pg.evaluate(
            """() => {
              var el = document.querySelector('.astream');
              el.setAttribute('sse-connect', '/stream');
              htmx.process(el);
            }""")

        pg.wait_for_selector("%s .aworking" % render.turn_status_target(t1))
        # Before the close: the working line really is in the turn's own
        # status row, and the sink it streamed through is really empty,
        # confirming the premise this fix and this test both depend on.
        assert pg.locator(".awork").inner_html() == ""
        assert pg.locator(render.turn_status_target(t2)).inner_html() == ""

        _CloseHandler.close_now.set()
        pg.wait_for_function(
            "() => !document.querySelector('.astream')"
            ".hasAttribute('sse-connect')")

        assert pg.locator(render.turn_status_target(t1)).inner_html() == ""
        # Untouched: not the whole turn, and not the other turn either.
        assert "here is your inbox" in pg.locator(
            render.turn_body_target(t1)).inner_html()
        assert pg.locator(render.turn_status_target(t2)).inner_html() == ""
        assert pg.locator("#agent-thread .aturn").count() == 2
        pg.close()
    finally:
        srv.shutdown()
