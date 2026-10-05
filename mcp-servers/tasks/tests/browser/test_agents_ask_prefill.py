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

#: The Open WebUI shell, cut down to what these tests need from it: a top
#: document that frames the agents page as a pane, the way task-panel.js does.
#: ?frame= points the pane somewhere else, so one server can also play a
#: shell on a different origin (localhost framing 127.0.0.1).
SHELL = (b'<!doctype html><meta charset="utf-8"><title>shell</title>'
         b'<body style="margin:0">'
         b'<iframe id="pane" style="width:1300px;height:900px;border:0">'
         b'</iframe><script>document.getElementById("pane").src = '
         b'new URLSearchParams(location.search).get("frame")'
         b' || "/agents.html";</script></body>')


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
            body = SHELL if self.path.startswith("/shell") else html
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


def test_the_cursor_waits_at_the_end_so_they_can_type_the_rest(browser, server):
    """"Chat with Iris" hands over "Iris, " and the person writes the rest.
    A cursor sitting at the front means the first thing they type lands in
    front of the name, and the message stops naming anybody.

    This passed the moment it was written: focus() on an input that already
    has a value leaves the caret at the end. It is kept as a pin, not claimed
    as a fix, because the behaviour it relies on belongs to the browser and
    an explicit setSelectionRange would be the obvious thing for somebody to
    "tidy up" later."""
    q = "?ask=" + urllib.parse.quote("Iris, ")
    pg = _open(browser, server, q)
    try:
        at = pg.eval_on_selector(
            ".ap-composer input[name=message]",
            "el => ({ start: el.selectionStart, end: el.selectionEnd, "
            "focused: el === document.activeElement })")
        assert at["focused"] is True
        assert at["start"] == len("Iris, "), at
        assert at["end"] == len("Iris, "), at
    finally:
        pg.close()


# --- the shell handing the pane a question ----------------------------------
#
# task-panel.js opens the agents pane and then posts
# {type: "aiui-agents-ask", ask} to its iframe, with targetOrigin set to its
# own origin (the shared aiui:open-pane protocol, 2026-10-05). The page fills
# the box by the same path ?ask= uses, and only for a message from the window
# that framed it, on its own origin. It never sends.

BOX = ".ap-composer input[name=message]"

#: target None means the shell's own origin, which is what task-panel.js
#: uses. "*" is only for the cross-origin case: with a named target the
#: browser would drop the message before the page ever saw it, and the test
#: would pass without the page checking anything.
POST_TO_PANE = (
    "([ask, target]) => document.getElementById('pane').contentWindow"
    ".postMessage({type: 'aiui-agents-ask', ask: ask},"
    " target || location.origin)")

#: Records every message type the pane receives, so a test that expects the
#: box to stay empty can also prove the message did arrive and was refused.
LISTEN = ("() => { window.__got = [];"
          " addEventListener('message', e => window.__got.push("
          "e.data && e.data.type)); }")


def _shell(browser, server, host="127.0.0.1", frame=None):
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
    url = "http://%s:%d/shell" % (host, server.server_address[1])
    if frame:
        url += "?frame=" + urllib.parse.quote(frame, safe="")
    pg.goto(url)
    pg.frame_locator("#pane").locator(BOX).wait_for(state="attached")
    pg.wait_for_timeout(350)
    pg.frame_locator("#pane").locator("body").evaluate(LISTEN)
    pg.sent = sent
    return pg


def _pane(pg):
    return pg.frame_locator("#pane")


def _arrived(pg):
    return _pane(pg).locator("body").evaluate("() => window.__got")


def test_the_shell_can_hand_the_pane_a_question(browser, server):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["Ada, weekly review", None])
        pg.wait_for_timeout(200)
        assert _pane(pg).locator(BOX).input_value() == "Ada, weekly review"
        assert _pane(pg).locator(BOX).evaluate(
            "e => e === document.activeElement"), (
            "the box was filled but not focused, unlike ?ask=")
    finally:
        pg.close()


def test_a_question_from_the_shell_is_not_sent(browser, server):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["Ada, weekly review", None])
        pg.wait_for_timeout(300)
        assert "aiui-agents-ask" in _arrived(pg)
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_a_message_that_is_not_from_the_parent_is_ignored(browser, server):
    """The pane posting to itself stands in for any other frame on the same
    origin: right origin, wrong source."""
    pg = _shell(browser, server)
    try:
        _pane(pg).locator("body").evaluate(
            "() => window.postMessage({type: 'aiui-agents-ask',"
            " ask: 'typed by someone else'}, location.origin)")
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg), "the message never arrived"
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_a_parent_on_another_origin_is_ignored(browser, server):
    """Right source, wrong origin: a page on localhost framing the agents
    page on 127.0.0.1 must not be able to type into it."""
    port = server.server_address[1]
    pg = _shell(browser, server, host="localhost",
                frame="http://127.0.0.1:%d/agents.html" % port)
    try:
        pg.evaluate(POST_TO_PANE, ["typed by another site", "*"])
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg), "the message never arrived"
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_a_standalone_page_ignores_the_message(browser, server):
    """Not framed, there is no shell, and window.parent is the page itself,
    so a source check alone would let the page's own posts through."""
    pg = _open(browser, server)
    try:
        pg.evaluate(
            "() => window.postMessage({type: 'aiui-agents-ask',"
            " ask: 'nobody asked'}, location.origin)")
        pg.wait_for_timeout(200)
        assert pg.input_value(BOX) == ""
    finally:
        pg.close()


@pytest.mark.parametrize("ask", [42, None, "   "])
def test_a_question_that_is_not_text_is_ignored(browser, server, ask):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, [ask, None])
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg)
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_an_overlong_question_is_ignored(browser, server):
    """The shell drops an ask over 2000 characters rather than cutting it,
    and so does the page: one policy on both sides, so half a question never
    lands in the box looking like the whole of it."""
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["x" * 2500, None])
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg)
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


# --- the shell naming the agent ---------------------------------------------
#
# A robot's Chat pill in the Agent Office opens that agent's own conversation
# when the office is docked in this page (aiui-office-ask with the agent).
# The same click in the standalone Agent Office pane reaches this page through
# the shell as aiui-agents-ask, now carrying the same agent and name, and has
# to do the same thing: one click may not behave two ways. Only for the
# viewer's own agents, the rule the cards follow.

ROSTER = [
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-bo-0002", "name": "Bo",
     "meta": {"role": "Researcher", "toolIds": []},
     "params": {}, "user_id": "someone-else", "created_at": 2, "updated_at": 2},
]
IRIS_CARD = '#my-agents .card[data-agent-id="agent-iris-a103"]'

#: What task-panel.js posts, plus whatever fields the test hands it.
POST_ASK = (
    "m => document.getElementById('pane').contentWindow.postMessage("
    "Object.assign({type: 'aiui-agents-ask'}, m), location.origin)")


def _shell_as_owner(browser, server, hold_list=False):
    """The shell around the agents page, signed in as the owner of Iris.

    hold_list leaves the agent list unanswered until the test calls
    pg.release(). The shell hands a question over the moment the pane's
    frame fires load, and the list is a fetch that is still out then."""
    pg = browser.new_page(viewport={"width": 1400, "height": 950})
    pg.set_default_timeout(6000)
    sent, held = [], []

    def answer(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in url:
            body = {"items": ROSTER, "total": len(ROSTER)}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    def route(r):
        if r.request.method == "POST":
            sent.append(r.request.url)
        if hold_list and "/models/list" in r.request.url:
            held.append(r)
            return
        answer(r)

    def release():
        while held:
            answer(held.pop(0))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    pg.goto("http://127.0.0.1:%d/shell" % server.server_address[1])
    pg.frame_locator("#pane").locator(BOX).wait_for(state="attached")
    if not hold_list:
        pg.frame_locator("#pane").locator(IRIS_CARD).wait_for(state="attached")
    pg.wait_for_timeout(200)
    pg.frame_locator("#pane").locator("body").evaluate(LISTEN)
    pg.sent = sent
    pg.release = release
    return pg


def _talking_to(pg):
    return _pane(pg).locator("#ap-agent").input_value()


def test_the_shell_opens_your_agents_own_conversation(browser, server):
    """The Chat pill says "Iris, ". Docked, it opens Iris's own conversation
    and leaves the box empty; from the shell it does the same."""
    pg = _shell_as_owner(browser, server)
    try:
        pg.evaluate(POST_ASK, {"ask": "Iris, ", "agent": "agent-iris-a103",
                               "name": "Iris"})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "agent-iris-a103"
        assert _pane(pg).locator("#ap-who").inner_text() == "Chat with Iris"
        assert _pane(pg).locator(BOX).input_value() == ""
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_a_skill_from_the_shell_opens_the_conversation_with_the_question(
        browser, server):
    """A skill link says "Iris, find my file". In Iris's own conversation her
    name is not needed, so only the question goes in the box, unsent."""
    pg = _shell_as_owner(browser, server)
    try:
        pg.evaluate(POST_ASK, {"ask": "Iris, find my file",
                               "agent": "agent-iris-a103", "name": "Iris"})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "agent-iris-a103"
        assert _pane(pg).locator(BOX).input_value() == "find my file"
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_the_question_waits_until_your_agents_are_known(browser, server):
    """Until the list arrives the page cannot tell whose agent this is. It
    waits for it rather than putting the question in the room."""
    pg = _shell_as_owner(browser, server, hold_list=True)
    try:
        pg.evaluate(POST_ASK, {"ask": "Iris, find my file",
                               "agent": "agent-iris-a103", "name": "Iris"})
        pg.wait_for_timeout(300)
        assert "aiui-agents-ask" in _arrived(pg)
        assert _pane(pg).locator(BOX).input_value() == ""
        pg.release()
        _pane(pg).locator(IRIS_CARD).wait_for(state="attached")
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "agent-iris-a103"
        assert _pane(pg).locator(BOX).input_value() == "find my file"
    finally:
        pg.close()


def test_only_your_own_agents_conversation_is_opened(browser, server):
    """Somebody else's agent, or an id this page does not list, gets no
    private conversation from a message. The question goes to the room as
    it was written, which is what happened before the office named agents."""
    pg = _shell_as_owner(browser, server)
    try:
        for agent, name in (("agent-bo-0002", "Bo"),
                            ("agent-nobody-0009", "Nobody")):
            ask = name + ", hello"
            pg.evaluate(POST_ASK, {"ask": ask, "agent": agent, "name": name})
            pg.wait_for_timeout(300)
            assert _talking_to(pg) == "", agent
            assert _pane(pg).locator(BOX).input_value() == ask
        pg.evaluate(POST_ASK, {"ask": "Iris, ", "agent": "agent-iris-a103",
                               "name": "Iris"})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "agent-iris-a103"
    finally:
        pg.close()


def test_a_question_for_the_room_leaves_a_private_conversation(browser, server):
    """Call a team meeting in the Agent Office pane hands over
    "everyone answer: " with no agent. Docked, the same button goes back to
    the room first; through the shell it landed in whatever private
    conversation the page had restored, so only that one agent heard it."""
    pg = _shell_as_owner(browser, server)
    try:
        pg.evaluate(POST_ASK, {"ask": "Iris, ", "agent": "agent-iris-a103",
                               "name": "Iris"})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "agent-iris-a103"
        pg.evaluate(POST_ASK, {"ask": "everyone answer: "})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == "", "the room question stayed in Iris's thread"
        assert _pane(pg).locator(BOX).input_value() == "everyone answer: "
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_somebody_elses_agent_is_asked_in_the_room_not_the_open_thread(
        browser, server):
    """A question naming an agent that is not yours goes to the room as
    written. With a private conversation open it must still be the room."""
    pg = _shell_as_owner(browser, server)
    try:
        pg.evaluate(POST_ASK, {"ask": "Iris, ", "agent": "agent-iris-a103",
                               "name": "Iris"})
        pg.wait_for_timeout(300)
        pg.evaluate(POST_ASK, {"ask": "Bo, hello", "agent": "agent-bo-0002",
                               "name": "Bo"})
        pg.wait_for_timeout(300)
        assert _talking_to(pg) == ""
        assert _pane(pg).locator(BOX).input_value() == "Bo, hello"
    finally:
        pg.close()
