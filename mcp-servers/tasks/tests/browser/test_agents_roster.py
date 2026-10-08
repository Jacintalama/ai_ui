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
#: The same shell on a phone: the pane is the whole 390px screen.
SHELL_PHONE = SHELL.replace(b"width:1400px;height:900px",
                            b"width:390px;height:844px")

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
            if path.startswith("/phoneshell"):
                body = SHELL_PHONE
            elif path.startswith("/shell"):
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


def _open(browser, server, roster=None, url="/agents.html", activity=None,
          size=(1500, 1000)):
    """The agents page signed in as the owner of `roster`. Returns the page
    and the locator root for the agents document (the pane when framed)."""
    agents = ROSTER if roster is None else roster
    pg = browser.new_page(viewport={"width": size[0], "height": size[1]})
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
    framed = url.startswith(("/shell", "/phoneshell"))
    root = pg.frame_locator("#pane") if framed else pg
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


# --- Task 3: the conversation header says who hears you ---------------------
#
# DESIGN.md, Do's: "say who will hear a message before it is sent". The old
# header read "Chat with your agents" in the room and "Chat with Iris" in a
# private conversation, which said where you were but not who would read it.

BOX = ".ap-composer input[name=message]"


def _header(root):
    return (root.locator("#ap-who").inner_text(),
            root.locator("#ap-sub").inner_text(),
            root.locator(BOX).get_attribute("placeholder"))


def test_the_room_header_names_who_hears_it(browser, server):
    pg, root = _open(browser, server)
    try:
        assert _header(root) == (
            "Everyone",
            "Iris and Bo hear this. Each answers only if it has something"
            " to add.",
            "Message everyone")
    finally:
        pg.close()


def test_a_private_header_names_the_agent_and_role(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        assert _header(root) == (
            "Iris",
            "Drive librarian. Only Iris hears this conversation.",
            "Message Iris")
    finally:
        pg.close()


def test_a_private_header_without_a_role_names_only_the_agent(browser, server):
    plain = dict(BO, meta={"toolIds": []})
    pg, root = _open(browser, server, roster=[IRIS, plain])
    try:
        root.locator('#roster-list .roster-row[data-agent-id="agent-bo-0002"]').click()
        pg.wait_for_timeout(200)
        assert root.locator("#ap-sub").inner_text() == (
            "Only Bo hears this conversation.")
    finally:
        pg.close()


def test_three_names_are_listed_and_more_are_counted(browser, server):
    ada = dict(BO, id="agent-ada-0003", name="Ada", created_at=3)
    dev = dict(BO, id="agent-dev-0004", name="Dev", created_at=4)
    pg, root = _open(browser, server, roster=[IRIS, BO, ada])
    try:
        assert root.locator("#ap-sub").inner_text().startswith(
            "Iris, Bo and Ada hear this.")
    finally:
        pg.close()
    pg, root = _open(browser, server, roster=[IRIS, BO, ada, dev])
    try:
        assert root.locator("#ap-sub").inner_text().startswith(
            "All 4 agents hear this.")
    finally:
        pg.close()


def test_a_search_does_not_change_who_hears_the_room(browser, server):
    """The search narrows the list; it does not take anybody out of the
    room. Saying "Bo hears this" while Iris also reads it would be false."""
    pg, root = _open(browser, server)
    try:
        root.locator("#agent-search").fill("bo")
        pg.wait_for_timeout(300)
        assert root.locator("#ap-sub").inner_text().startswith(
            "Iris and Bo hear this.")
    finally:
        pg.close()


def test_the_header_name_is_text_not_markup(browser, server):
    evil = "<img src=x onerror=window.__pwned=1>"
    agent = dict(BO, id="agent-evil-0003", name=evil)
    pg, root = _open(browser, server, roster=[IRIS, agent])
    try:
        assert evil in root.locator("#ap-sub").inner_text()
        root.locator('#roster-list .roster-row[data-agent-id="agent-evil-0003"]').click()
        pg.wait_for_timeout(200)
        assert root.locator("#ap-who").inner_text() == evil
        assert root.locator(".ap-head img").count() == 0
        assert pg.evaluate("() => window.__pwned") is None
    finally:
        pg.close()


def test_the_list_replaces_back_to_everyone(browser, server):
    """#ap-everyone stays in the DOM (older code looks it up) but is never
    shown: the Everyone row is the way back."""
    pg, root = _open(browser, server)
    try:
        assert root.locator("#ap-everyone").count() == 1
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        assert root.locator("#ap-everyone").is_hidden()
    finally:
        pg.close()


# --- Task 4: the details panel on the right ---------------------------------
#
# DESIGN.md, Details panel: the selected agent's details on the right,
# collapsible, its open or closed state remembered. In the room every card
# shows, because that is where agents are managed.

DETAILS = ".agents-main"
VISIBLE_CARDS = "#my-agents .card[data-agent-id]:visible"


def test_three_panes_at_wide_widths(browser, server):
    pg, root = _open(browser, server)
    try:
        roster = root.locator("#agent-roster").bounding_box()
        chat = root.locator(".chat-column").bounding_box()
        details = root.locator(DETAILS).bounding_box()
        assert roster["x"] < chat["x"] < details["x"]
        assert root.locator("#details-toggle").get_attribute(
            "aria-expanded") == "true"
        controls = root.locator("#details-toggle").get_attribute("aria-controls")
        assert controls and root.locator(DETAILS).get_attribute("id") == controls
        pg.mouse.move(700, 500)
        pg.mouse.wheel(0, 1200)
        pg.wait_for_timeout(120)
        assert pg.evaluate("() => window.scrollY") == 0
        box = root.locator(".ap-composer").bounding_box()
        assert box["y"] + box["height"] <= 1000 + 1
    finally:
        pg.close()


def test_details_shows_only_the_open_agent(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        cards = root.locator(VISIBLE_CARDS)
        assert cards.count() == 1
        assert cards.first.get_attribute("data-agent-id") == "agent-iris-a103"
        assert root.locator("#details-title").inner_text() == "Iris"
    finally:
        pg.close()


def test_the_room_shows_every_agent_in_details(browser, server):
    pg, root = _open(browser, server)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        root.locator(EVERYONE_ROW).click()
        pg.wait_for_timeout(200)
        assert root.locator(VISIBLE_CARDS).count() == 2
        assert root.locator("#details-title").inner_text() == "Your agents"
    finally:
        pg.close()


def test_details_can_be_closed_and_it_is_remembered(browser, server):
    pg, root = _open(browser, server)
    try:
        before = root.locator(".chat-column").bounding_box()["width"]
        root.locator("#details-toggle").click()
        pg.wait_for_timeout(150)
        assert root.locator(DETAILS).is_hidden()
        assert root.locator("#details-toggle").get_attribute(
            "aria-expanded") == "false"
        # The conversation takes the room the details gave up.
        assert root.locator(".chat-column").bounding_box()["width"] > before + 200
        pg.reload()
        root.locator("#my-agents .card").first.wait_for(state="attached")
        pg.wait_for_timeout(300)
        assert root.locator(DETAILS).is_hidden()
        assert root.locator("#details-toggle").get_attribute(
            "aria-expanded") == "false"
        root.locator("#details-toggle").click()
        pg.wait_for_timeout(150)
        assert root.locator(DETAILS).is_visible()
    finally:
        pg.close()


def test_details_start_closed_below_1440(browser, server):
    """Open by default only where three panes leave the conversation enough
    room (the plan's 1440px line); a choice the person made wins either way."""
    pg, root = _open(browser, server, size=(1300, 900))
    try:
        assert root.locator(DETAILS).is_hidden()
        assert root.locator("#details-toggle").get_attribute(
            "aria-expanded") == "false"
    finally:
        pg.close()


def test_the_conversation_gets_the_room(browser, server):
    pg, root = _open(browser, server, size=(1920, 1080))
    try:
        assert root.locator(".ap-thread").bounding_box()["height"] >= 700
    finally:
        pg.close()


def test_the_list_replaces_chat_with_on_the_card(browser, server):
    """The element stays (Phase 0 code looks it up), but it is not shown:
    the conversation list is the one way to open a conversation."""
    pg, root = _open(browser, server)
    try:
        assert root.locator("#my-agents .card-foot .chat-with").count() == 2
        assert root.locator("#my-agents .card-foot .chat-with:visible").count() == 0
    finally:
        pg.close()


def test_details_sits_beside_clear(browser, server):
    """The header's actions sit together on the right. Measured in a
    screenshot: with the head spread space-between, Details floated in the
    middle of the header, a long way from anything it belongs to."""
    pg, root = _open(browser, server, size=(1920, 1080))
    try:
        details = root.locator("#details-toggle").bounding_box()
        clear = root.locator("#ap-clear").bounding_box()
        gap = clear["x"] - (details["x"] + details["width"])
        assert 0 <= gap <= 16, gap
    finally:
        pg.close()


# --- Task 5: smaller windows, two panes and then one ------------------------
#
# DESIGN.md: three panes on wide screens, two on medium, one at a time on
# phones. From 700 to 1180px the list and the conversation sit side by side
# and the details open as a sheet over the conversation. Under 700px one
# pane fills the screen at a time.

MEDIUM = (1000, 800)
PHONE = (390, 844)
LIST = "#agent-roster"
CHAT = ".chat-column"


def _window_stays_still(pg, x, y):
    pg.mouse.move(x, y)
    pg.mouse.wheel(0, 1500)
    pg.wait_for_timeout(150)
    return pg.evaluate("() => window.scrollY") == 0


def _overflow_y(root, sel):
    return root.locator(sel).evaluate("e => getComputedStyle(e).overflowY")


def test_two_panes_at_1000(browser, server):
    pg, root = _open(browser, server, size=MEDIUM)
    try:
        roster = root.locator(LIST).bounding_box()
        chat = root.locator(CHAT).bounding_box()
        assert abs(roster["width"] - 232) <= 1, roster
        # Side by side, not stacked.
        assert roster["x"] + roster["width"] <= chat["x"], (roster, chat)
        assert abs(roster["y"] - chat["y"]) <= 1, (roster, chat)
        assert chat["x"] + chat["width"] <= MEDIUM[0], chat
        # Details defaults to closed at this width.
        assert root.locator(DETAILS).is_hidden()
        toggle = root.locator("#details-toggle")
        assert toggle.get_attribute("aria-expanded") == "false"

        toggle.click()
        pg.wait_for_timeout(150)
        sheet = root.locator(DETAILS)
        assert sheet.is_visible()
        assert toggle.get_attribute("aria-expanded") == "true"
        box = sheet.bounding_box()
        # A sheet over the conversation, pinned to the right edge, the whole
        # height of the window.
        assert abs(box["width"] - 360) <= 1, box
        assert abs(box["x"] + box["width"] - MEDIUM[0]) <= 1, box
        assert box["y"] <= 0.5 and abs(box["height"] - MEDIUM[1]) <= 1, box
        assert box["x"] < chat["x"] + chat["width"], "it is not over the chat"
        style = sheet.evaluate(
            "e => { const s = getComputedStyle(e); return [s.position,"
            " s.borderLeftWidth, s.boxShadow]; }")
        assert style == ["fixed", "1px", "rgba(0, 0, 0, 0.45) 0px 4px 8px 0px"], style

        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        assert sheet.is_hidden()
        assert toggle.get_attribute("aria-expanded") == "false"
        assert root.locator(LIST).is_visible() and root.locator(CHAT).is_visible()
    finally:
        pg.close()


def test_the_sheet_can_be_closed_without_a_keyboard(browser, server):
    """The sheet covers the right of the conversation header, Details
    included, so the sheet carries its own Done."""
    pg, root = _open(browser, server, size=MEDIUM)
    try:
        root.locator("#details-toggle").click()
        pg.wait_for_timeout(150)
        done = root.locator("#details-done")
        assert done.is_visible() and done.inner_text() == "Done"
        done.click()
        pg.wait_for_timeout(150)
        assert root.locator(DETAILS).is_hidden()
        assert root.locator("#details-toggle").get_attribute(
            "aria-expanded") == "false"
    finally:
        pg.close()


def test_a_wide_screen_choice_does_not_open_the_sheet(browser, server):
    """Details open at 1920 is remembered for 1920. At 1000 the sheet would
    cover the conversation on arrival, so it starts closed there anyway."""
    pg, root = _open(browser, server, size=MEDIUM)
    try:
        pg.evaluate("() => localStorage.setItem('aiui-details-open', '1')")
        pg.reload()
        root.locator("#my-agents .card").first.wait_for(state="attached")
        pg.wait_for_timeout(300)
        assert root.locator(DETAILS).is_hidden()
        # And opening the sheet here does not overwrite the wide choice.
        root.locator("#details-toggle").click()
        pg.keyboard.press("Escape")
        assert pg.evaluate(
            "() => localStorage.getItem('aiui-details-open')") == "1"
    finally:
        pg.close()


def test_the_medium_layout_fills_the_window_and_each_pane_scrolls(browser, server):
    pg, root = _open(browser, server, size=MEDIUM)
    try:
        assert _window_stays_still(pg, 600, 400)
        assert _window_stays_still(pg, 100, 400)
        box = root.locator(".ap-composer").bounding_box()
        assert box["y"] + box["height"] <= MEDIUM[1] + 1, box
        assert _overflow_y(root, "#roster-list") == "auto"
        assert _overflow_y(root, ".ap-thread") == "auto"
        assert _overflow_y(root, DETAILS) == "auto"
    finally:
        pg.close()


def test_the_phone_buttons_hide_on_wider_screens(browser, server):
    for size in (MEDIUM, (1500, 1000)):
        pg, root = _open(browser, server, size=size)
        try:
            assert root.locator("#pane-back").count() == 1
            assert root.locator("#pane-back").is_hidden(), size
        finally:
            pg.close()
    pg, root = _open(browser, server, size=(1500, 1000))
    try:
        # Three panes: the panel is a column, not a sheet, and needs no Done.
        assert root.locator(DETAILS).is_visible()
        assert root.locator("#details-done").is_hidden()
    finally:
        pg.close()


def test_one_pane_at_a_time_on_a_phone(browser, server):
    pg, root = _open(browser, server, size=PHONE)
    try:
        assert root.locator(LIST).is_visible()
        assert root.locator(CHAT).is_hidden()
        assert root.locator(DETAILS).is_hidden()
        assert root.locator(LIST).bounding_box()["width"] >= PHONE[0] - 32

        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        assert root.locator(LIST).is_hidden()
        assert root.locator(CHAT).is_visible()
        assert root.locator(CHAT).bounding_box()["width"] >= PHONE[0] - 32
        assert root.locator("#ap-who").inner_text() == "Iris"
        box = root.locator(".ap-composer").bounding_box()
        assert box["y"] + box["height"] <= PHONE[1] + 1, box

        back = root.locator("#pane-back")
        assert back.is_visible() and back.inner_text() == "Agents"
        back.click()
        pg.wait_for_timeout(150)
        assert root.locator(LIST).is_visible()
        assert root.locator(CHAT).is_hidden()
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_details_on_a_phone_fill_the_screen_and_done_goes_back(browser, server):
    pg, root = _open(browser, server, size=PHONE)
    try:
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        root.locator("#details-toggle").click()
        pg.wait_for_timeout(150)
        assert root.locator(DETAILS).is_visible()
        assert root.locator(CHAT).is_hidden()
        assert root.locator(LIST).is_hidden()
        assert root.locator(DETAILS).bounding_box()["width"] >= PHONE[0] - 32
        assert root.locator("#details-title").inner_text() == "Iris"
        assert root.locator(VISIBLE_CARDS).count() == 1
        done = root.locator("#details-done")
        assert done.is_visible() and done.inner_text() == "Done"
        done.click()
        pg.wait_for_timeout(150)
        assert root.locator(CHAT).is_visible()
        assert root.locator(DETAILS).is_hidden()
    finally:
        pg.close()


def test_the_phone_layout_fills_the_screen_and_each_pane_scrolls(browser, server):
    pg, root = _open(browser, server, size=PHONE)
    try:
        assert _window_stays_still(pg, 195, 500)
        assert _overflow_y(root, "#roster-list") == "auto"
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        assert _window_stays_still(pg, 195, 400)
        assert _overflow_y(root, ".ap-thread") == "auto"
    finally:
        pg.close()


def _targets(root, sel):
    """[name, height] of every rendered element matching `sel`."""
    return root.locator("body").evaluate(
        "(b, sel) => [...document.querySelectorAll(sel)]"
        ".filter(e => e.getClientRects().length"
        " && getComputedStyle(e).visibility !== 'hidden')"
        ".map(e => [e.id || e.className || e.tagName,"
        " Math.round(e.getBoundingClientRect().height * 10) / 10])", sel)


def test_phone_targets_are_44px(browser, server):
    pg, root = _open(browser, server, size=PHONE)
    try:
        targets = _targets(
            root, "#agent-roster button, #agent-roster a, #agent-roster input")
        assert len(targets) >= 6, targets
        small = [t for t in targets if t[1] < 44]
        assert not small, small
        root.locator(IRIS_ROW).click()
        pg.wait_for_timeout(200)
        targets = _targets(
            root, ".ap-head button, .ap-composer button, .ap-composer input")
        assert len(targets) >= 4, targets
        small = [t for t in targets if t[1] < 44]
        assert not small, small
    finally:
        pg.close()


def test_an_ask_on_a_phone_lands_in_the_conversation(browser, server):
    pg, root = _open(browser, server, url="/agents.html?ask=hello", size=PHONE)
    try:
        assert root.locator(CHAT).is_visible()
        assert root.locator(LIST).is_hidden()
        assert root.locator(BOX).input_value() == "hello"
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_a_shell_ask_on_a_phone_lands_in_the_conversation(browser, server):
    pg, root = _open(browser, server, url="/phoneshell", size=PHONE)
    try:
        assert root.locator(LIST).is_visible()
        pg.evaluate(
            "() => document.getElementById('pane').contentWindow.postMessage("
            "{type: 'aiui-agents-ask', ask: 'hello'}, location.origin)")
        pg.wait_for_timeout(300)
        assert root.locator(CHAT).is_visible()
        assert root.locator(LIST).is_hidden()
        assert root.locator(BOX).input_value() == "hello"
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()
