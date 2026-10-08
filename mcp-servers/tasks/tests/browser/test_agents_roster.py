"""The conversation list on the left of the AI agents page.

Phase 1 of the chat-first workspace (docs/plans/2026-10-08-ai-agents-
workspace-phase1.md, Task 2; design in docs/plans/2026-10-05-ai-agents-
workspace-design.md and DESIGN.md, "Conversation list"). "Everyone" first,
then one row per agent. Picking a row opens that conversation through the
same window.aiuiTalkTo the cards and the office already use, so a private
conversation is the same saved thread whichever way it was opened. Picking
never sends anything.

The server and stubs follow test_agents_ask_prefill.py (_shell_as_owner),
with one change: the page's own stylesheet and vendor scripts are served for
real, because a stubbed asset hid a broken layout through a whole deploy on
this project once.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
KINDS = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}

#: A top document framing the agents page as a pane, the way task-panel.js
#: does, recording every aiui:open-pane message it receives.
SHELL = (b'<!doctype html><meta charset="utf-8"><title>shell</title>'
         b'<body style="margin:0"><script>window.__panes = [];'
         b'addEventListener("message", function (ev) {'
         b' if (ev.data && ev.data.type === "aiui:open-pane")'
         b'  window.__panes.push({ data: ev.data, origin: ev.origin });'
         b'});</script>'
         b'<iframe id="pane" src="/agents.html" '
         b'style="width:1400px;height:900px;border:0"></iframe></body>')

IRIS = {"id": "agent-iris-a103", "name": "Iris",
        "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
        "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1}
BO = {"id": "agent-bo-0002", "name": "Bo",
      "meta": {"role": "Researcher", "toolIds": []},
      "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2}
ROSTER = [IRIS, BO]

ROWS = "#roster-list .roster-row"
IRIS_ROW = '#roster-list .roster-row[data-agent-id="agent-iris-a103"]'
EVERYONE_ROW = '#roster-list .roster-row[data-room="1"]'


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
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            kind = "text/html"
            rel = path[len("/tasks/static/"):]
            if path.startswith("/shell"):
                body = SHELL
            elif path.startswith("/tasks/static/") and (STATIC / rel).is_file():
                body = (STATIC / rel).read_bytes()
                kind = KINDS.get((STATIC / rel).suffix, kind)
            elif path.startswith("/tasks/graph"):
                body = b"<!doctype html><title>graph</title>"
            else:
                body = (STATIC / "agents.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _open(browser, server, roster=None, url="/agents.html", activity=None):
    """The agents page signed in as the owner of `roster`. Returns the page
    and the locator root for the agents document (the pane when framed)."""
    agents = ROSTER if roster is None else roster
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    sent = []

    def route(r):
        u = r.request.url
        if r.request.method == "POST":
            sent.append(u)
        if "/api/v1/auths/" in u:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in u:
            body = {"items": agents, "total": len(agents)}
        elif "/agents/activity" in u:
            body = {"activity": activity or {}, "handoffs": []}
        elif "/agents/chat/" in u:
            r.fulfill(status=200, content_type="text/html", body="")
            return
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/**", route)
    pg.goto("http://127.0.0.1:%d%s" % (server.server_address[1], url))
    root = pg.frame_locator("#pane") if url.startswith("/shell") else pg
    root.locator("#my-agents .card").first.wait_for(state="attached")
    pg.wait_for_timeout(300)
    pg.sent = sent
    return pg, root


def _row_names(root):
    return root.locator(ROWS + " .roster-name").all_inner_texts()


def test_the_list_starts_with_everyone_then_each_agent(browser, server):
    pg, root = _open(browser, server)
    try:
        assert _row_names(root) == ["Everyone", "Iris", "Bo"]
        # Everyone's second line names who is in the room.
        assert "Iris, Bo" in root.locator(EVERYONE_ROW).inner_text()
        # An agent's row carries its role.
        assert "Drive librarian" in root.locator(IRIS_ROW).inner_text()
    finally:
        pg.close()


def test_picking_an_agent_opens_their_conversation(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        assert root.locator("#ap-agent").input_value() == "agent-iris-a103"
        assert root.locator(IRIS_ROW).get_attribute("aria-current") == "true"
        assert root.locator(EVERYONE_ROW).get_attribute("aria-current") is None
    finally:
        pg.close()


def test_everyone_goes_back_to_the_room(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        root.locator(EVERYONE_ROW).click()
        pg.wait_for_timeout(200)
        assert root.locator("#ap-agent").input_value() == ""
        assert root.locator(EVERYONE_ROW).get_attribute("aria-current") == "true"
        assert root.locator(IRIS_ROW).get_attribute("aria-current") is None
    finally:
        pg.close()


def test_the_room_is_current_on_a_first_visit(browser, server):
    pg, root = _open(browser, server)
    try:
        assert root.locator(EVERYONE_ROW).get_attribute("aria-current") == "true"
    finally:
        pg.close()


def test_search_filters_the_list(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator("#agent-search").fill("bo")
        pg.wait_for_timeout(300)
        assert _row_names(root) == ["Everyone", "Bo"]
    finally:
        pg.close()


def test_a_name_is_text_not_markup(browser, server):
    evil = "<img src=x onerror=window.__pwned=1>"
    agent = dict(BO, id="agent-evil-0003", name=evil)
    pg, root = _open(browser, server, roster=[IRIS, agent])
    try:
        row = root.locator('#roster-list .roster-row[data-agent-id="agent-evil-0003"]')
        assert evil in row.inner_text()
        assert root.locator("#agent-roster img").count() == 0
        assert pg.evaluate("() => window.__pwned") is None
    finally:
        pg.close()


def test_the_avatar_is_the_agents_one_hue(browser, server):
    """DESIGN.md, Agent identity: a solid hsl(hue 45% 32%) square with a
    white initial, the hue being the same hash the cards use."""
    pg, root = _open(browser, server)
    try:
        av = root.locator(IRIS_ROW + " .roster-av")
        assert av.inner_text() == "I"
        hue = pg.evaluate("() => window.__aiuiAgents.avatarHue('Iris')")
        expect = pg.evaluate(
            "h => { const d = document.createElement('div');"
            " d.style.background = 'hsl(' + h + ' 45% 32%)';"
            " document.body.appendChild(d);"
            " const c = getComputedStyle(d).backgroundColor; d.remove();"
            " return c; }", hue)
        assert av.evaluate("e => getComputedStyle(e).backgroundColor") == expect
        assert av.evaluate("e => getComputedStyle(e).backgroundImage") == "none"
    finally:
        pg.close()


def test_a_status_word_shows_only_when_it_needs_you(browser, server):
    """Ready is silent; Needs you and Failed are words (DESIGN.md). The
    activity arrives after the cards are drawn, so the list has to pick it
    up then, not only when the cards are drawn."""
    pg, root = _open(browser, server, activity={
        "agent-iris-a103": {"state": "waiting"},
        "agent-bo-0002": {"state": "ready"}})
    try:
        root.locator(IRIS_ROW + " .roster-status").wait_for()
        assert root.locator(IRIS_ROW + " .roster-status").inner_text() == "Needs you"
        bo = '#roster-list .roster-row[data-agent-id="agent-bo-0002"]'
        assert root.locator(bo + " .roster-status").count() == 0
        assert "Ready" not in root.locator(bo).inner_text()
    finally:
        pg.close()


def test_the_footer_offers_the_office_and_the_graph(browser, server):
    pg, root = _open(browser, server)
    try:
        assert root.locator("#agent-roster .roster-foot #office-open").count() == 1
        graph = root.locator("#agent-roster .roster-foot #roster-graph")
        assert graph.inner_text() == "Knowledge graph"
        assert graph.get_attribute("href") == "/tasks/graph"
        # Search, Connections and New agent moved into the list with it.
        for sel in ("#agent-search", "#open-connections", "#new-agent"):
            assert root.locator("#agent-roster " + sel).count() == 1, sel
    finally:
        pg.close()


def test_knowledge_graph_asks_the_shell_when_framed(browser, server):
    pg, root = _open(browser, server, url="/shell")
    try:
        root.locator("#roster-graph").click()
        pg.wait_for_timeout(400)
        origin = "http://127.0.0.1:%d" % server.server_address[1]
        assert pg.evaluate("() => window.__panes") == [
            {"data": {"type": "aiui:open-pane", "path": "/graph"},
             "origin": origin}]
        assert pg.locator("#pane").evaluate(
            "f => f.contentWindow.location.pathname") == "/agents.html"
    finally:
        pg.close()


def test_knowledge_graph_is_a_plain_link_standalone(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator("#roster-graph").click()
        pg.wait_for_url("**/tasks/graph")
    finally:
        pg.close()


def test_nothing_is_sent_by_picking(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        root.locator(EVERYONE_ROW).click()
        pg.wait_for_timeout(300)
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()
