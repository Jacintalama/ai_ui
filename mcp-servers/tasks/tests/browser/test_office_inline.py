"""The office, inline in the chat column.

It has been three shapes. A separate page, then a floating window opened with
a button, and now a section of the column itself:

  "where is the office in this page... put it inline instead of clicking it...
   make sure it can be able to resize but the user."

Inline is what the earlier shapes kept failing at. A floating window has to
overlap something on a single screen, and the thing it landed on was the
composer. Stacked in the column it covers nothing: the floor, the conversation
and the box you type in each get their own room, and the grip between them
decides how that room is shared.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"


OFFICE_AGENTS = [
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-ada-0001", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": []},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
]


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


# Stand-ins for the Open WebUI document, holding only what the contract needs:
# a recorder for the one message the shell answers, aiui:open-pane. The office
# pane variant also loads the REAL task-panel.js, because the office decides
# it is inside the shell by the flag that file sets on the top window, and a
# flag written here by hand would only prove what this fixture imagined.
_RECORD = (b'<script>window.__panes = [];'
           b'window.addEventListener("message", function (ev) {'
           b' if (ev.data && ev.data.type === "aiui:open-pane")'
           b'  window.__panes.push({ data: ev.data, origin: ev.origin });'
           b'});</script>')
SHELL_AROUND_OFFICE = (
    b'<!doctype html><title>shell</title>' + _RECORD +
    b'<script src="/tasks/static/task-panel.js"></script>'
    b'<iframe id="pane" src="/tasks/office" '
    b'style="width:100%;height:1400px;border:0"></iframe>')
SHELL_AROUND_AGENTS = (
    b'<!doctype html><title>shell</title>' + _RECORD +
    b'<iframe id="pane" src="/agents.html" '
    b'style="width:1500px;height:1000px;border:0"></iframe>')


# The page's own stylesheet has to be served, not stubbed. An earlier version
# of this fixture answered every path that was not /agents with a placeholder
# document, which meant /tasks/static/agent-chat.css arrived as HTML and the
# browser dropped it. Every geometry measured was therefore taken against an
# unstyled page: one full-width column instead of the real two, and a composer
# nowhere near where it actually sits. A stubbed asset hid a broken layout
# through a whole deploy once on this project already.
@pytest.fixture(scope="module")
def server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            name = path.rsplit("/", 1)[-1]
            kind = "text/html"
            asset = STATIC / name
            if name.endswith((".css", ".js")) and asset.is_file():
                body = asset.read_bytes()
                kind = "text/css" if name.endswith(".css") else "text/javascript"
            elif path.startswith("/tasks/office"):
                body = (STATIC / "office.html").read_bytes()
            elif path.startswith("/bare"):
                # A frame that is NOT the agents page. The office is also a
                # pane in the shell at /ai-agents/office, so "am I in a frame"
                # is not the same question as "is somebody listening".
                body = (b'<!doctype html><title>bare</title>'
                        b'<iframe src="/tasks/office" '
                        b'style="width:100%;height:1400px;border:0"></iframe>')
            elif path.startswith("/shell-agents"):
                body = SHELL_AROUND_AGENTS
            elif path.startswith("/shell"):
                body = SHELL_AROUND_OFFICE
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


@pytest.fixture
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    # The office inside the frame needs a roster, or there are no robots to
    # click and the chat link cannot be tested at all.
    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": OFFICE_AGENTS, "total": len(OFFICE_AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": {}}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.wait_for_selector("#office-dock", state="attached")
    pg.wait_for_timeout(300)
    yield pg
    pg.close()


def _box(page, sel):
    return page.locator(sel).bounding_box()


def _overlap(a, b):
    return not (a["x"] + a["width"] <= b["x"] + 1
                or b["x"] + b["width"] <= a["x"] + 1
                or a["y"] + a["height"] <= b["y"] + 1
                or b["y"] + b["height"] <= a["y"] + 1)


# --- it is simply there -----------------------------------------------------

def test_the_office_is_on_the_page_without_being_opened(page):
    """No button, no click. It is part of the column."""
    assert page.locator("#office-dock").is_visible()
    assert page.locator("#office-body iframe").count() == 1


def test_it_is_not_a_floating_window(page):
    """Fixed or absolute is the old shape. Inline means it takes its own room
    in the flow and moves the rest of the column down."""
    how = page.evaluate(
        "() => getComputedStyle(document.getElementById('office-dock')).position")
    assert how in ("static", "relative"), how


def test_the_office_and_the_chat_are_separate_cards(page):
    """"separaete the card for each office and chat." The office used to be a
    section inside the conversation's card, which read as one thing with
    another stuffed into it."""
    assert page.locator(".chat-column > #office-dock").count() == 1
    assert page.locator("#agent-panel #office-dock").count() == 0
    assert page.locator(".chat-column > #agent-panel").count() == 1


# --- and it costs nothing else its place ------------------------------------

def test_it_covers_neither_the_conversation_nor_the_composer(page):
    """The whole reason for moving it inline. The floating version landed on
    the composer, which is the one thing that has to stay reachable."""
    dock = _box(page, "#office-dock")
    assert not _overlap(dock, _box(page, ".ap-composer"))
    assert not _overlap(dock, _box(page, ".ap-thread"))


def test_the_floor_is_above_the_conversation(page):
    """Order in the column: the floor, then what was said, then the box. The
    newest message stays next to the composer, where it is read."""
    assert _box(page, "#office-dock")["y"] < _box(page, ".ap-thread")["y"]
    assert _box(page, ".ap-thread")["y"] < _box(page, ".ap-composer")["y"]


# --- the person decides how much room it gets -------------------------------

def _drag_grip(page, by):
    grip = _box(page, "#office-grip")
    x = grip["x"] + grip["width"] / 2
    page.mouse.move(x, grip["y"] + 5)
    page.mouse.down()
    page.mouse.move(x, grip["y"] + 5 + by, steps=8)
    page.mouse.up()
    page.wait_for_timeout(200)


def test_the_user_can_resize_it_by_dragging(page):
    """"make sure it can be able to resize but the user."

    Shrink first, then grow. The card opens at the height the floor asked for,
    which can already be as tall as the column will allow, and a test that
    only grows would be measuring the ceiling rather than the grip."""
    start = _box(page, "#office-dock")["height"]
    _drag_grip(page, -150)
    smaller = _box(page, "#office-dock")["height"]
    assert smaller < start - 80, (start, smaller)
    _drag_grip(page, 110)
    assert _box(page, "#office-dock")["height"] > smaller + 60


def test_it_can_be_dragged_smaller_again(page):
    bigger = _box(page, "#office-dock")["height"]
    _drag_grip(page, -90)
    assert _box(page, "#office-dock")["height"] < bigger - 40


def test_resizing_it_never_costs_the_composer(page):
    """Growing the floor must not push the box you type in out of the panel.
    Dragged past every limit, the composer still has to be where it was."""
    was = _box(page, ".ap-composer")
    _drag_grip(page, 4000)
    now = _box(page, ".ap-composer")
    assert abs(now["y"] - was["y"]) < 2, (was, now)
    assert not _overlap(_box(page, "#office-dock"), now)


def test_the_size_you_chose_is_remembered(page):
    """A floor you have to resize on every visit is one you stop using."""
    _drag_grip(page, 100)
    chosen = _box(page, "#office-dock")["height"]
    page.reload()
    page.wait_for_selector("#office-dock", state="visible")
    page.wait_for_timeout(350)
    assert abs(_box(page, "#office-dock")["height"] - chosen) < 4


def test_the_keyboard_can_resize_it_too(page):
    """A drag handle only a mouse can reach is one a keyboard user cannot use
    at all. The column's own handle already takes arrow keys."""
    before = _box(page, "#office-dock")["height"]
    page.locator("#office-grip").focus()
    for _ in range(5):
        page.keyboard.press("ArrowUp")
    page.wait_for_timeout(200)
    assert _box(page, "#office-dock")["height"] < before


# --- always there, but not inescapable --------------------------------------

def test_it_can_be_hidden_and_brought_back(page):
    """Always there is right. Always there with no way out is not."""
    page.locator("#office-close").click()
    page.wait_for_timeout(180)
    assert page.locator("#office-dock").is_hidden()
    assert page.locator("#office-open").is_visible()
    page.locator("#office-open").click()
    page.wait_for_timeout(180)
    assert page.locator("#office-dock").is_visible()


def test_hiding_it_is_remembered(page):
    page.locator("#office-close").click()
    page.wait_for_timeout(180)
    page.reload()
    page.wait_for_selector("#office-open", state="visible")
    page.wait_for_timeout(350)
    assert page.locator("#office-dock").is_hidden()


def test_bringing_it_back_keeps_the_same_frame(page):
    """Rebuilding the frame reloads the whole floor and throws away what it
    had drawn, which is the opposite of watching."""
    was = page.locator("#office-body iframe").get_attribute("src")
    page.locator("#office-close").click()
    page.wait_for_timeout(150)
    page.locator("#office-open").click()
    page.wait_for_timeout(150)
    assert page.locator("#office-body iframe").count() == 1
    assert page.locator("#office-body iframe").get_attribute("src") == was


# --- asking an agent from the floor -----------------------------------------

def test_chatting_from_the_office_opens_that_agents_own_conversation(page):
    """A chat link that navigated would tear the floor down and rebuild it on
    every click. It switches the conversation in place instead, and to that
    agent's own thread rather than typing their name into the room."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the page reloaded"
    assert page.locator("#ap-agent").input_value() == "agent-iris-a103"
    assert "Iris" in page.locator("#ap-who").inner_text()


def test_it_opens_the_conversation_and_sends_nothing(page):
    """Switching rooms is free. Sending is not: a turn costs money and can
    run tools, so nothing is ever sent on the person's behalf."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.locator(".ap-composer input[name=message]").input_value() == ""


def test_a_frame_that_does_not_host_the_office_still_follows_the_link(page, server):
    """The office is a pane in the shell too, at /ai-agents/office. Being in a
    frame is not the same as having somebody listening, and swallowing the
    click with no listener would make Chat do nothing at all there."""
    page.goto("http://127.0.0.1:%d/bare" % server.server_address[1])
    frame = page.frame_locator("iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(600)
    # It left /bare, which is the point: the link was followed rather than
    # swallowed. The agents page takes ?ask= out of the address bar once it is
    # in the box, so the question is checked where it lands.
    assert "/bare" not in page.url, page.url
    assert page.locator(".ap-composer input[name=message]").input_value(
        ).startswith("Iris,")


# --- it has to LOOK like part of the page -----------------------------------

def test_the_embedded_office_drops_its_own_header(page):
    """The dock already says Agent Office. The floor's own top bar repeated
    the title, the search box and New agent inside the frame, so the column
    carried two headers stacked on each other."""
    frame = page.frame_locator("#office-body iframe")
    assert frame.locator(".top").count() == 1      # still in the markup
    assert not frame.locator(".top").is_visible()  # but not shown here


def _floor(page):
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".floor").wait_for()
    return frame.locator(".floor")


def _spill(page):
    return _floor(page).evaluate(
        "el => el.getBoundingClientRect().bottom"
        " - document.documentElement.clientHeight")


def test_the_whole_floor_can_be_reached_by_making_it_bigger(page):
    """A whole floor needs 570 in this dock: its own 460 minimum plus the
    header, the frame's padding and the Brain chip. The column can only give
    about 608 before the conversation has nothing left, so it does not open
    that tall. Dragging up has to get there."""
    _drag_grip(page, 400)
    assert _spill(page) <= 2, _spill(page)


def test_the_whole_floor_stays_visible_however_small_the_card_gets(page):
    """"can you zoom out the office." Rooms are percentages of the floor but a
    robot is a fixed 76px, so reflowing a narrow floor packs six rooms into
    strips too small to hold one and they pile up. The floor is one fixed
    canvas scaled to fit instead, so shrinking the card shrinks the office
    rather than cropping it."""
    before = _floor(page).evaluate("el => el.getBoundingClientRect().width")
    _drag_grip(page, -4000)
    after = _floor(page).evaluate("el => el.getBoundingClientRect().width")
    assert after < before, (before, after)


def test_the_shell_pane_keeps_its_own_header(page, server):
    """The office is also a whole pane at /ai-agents/office, and there its top
    bar is the only header there is. Hiding it everywhere would take the
    search box and New agent with it."""
    page.goto("http://127.0.0.1:%d/tasks/office" % server.server_address[1])
    page.wait_for_selector(".top", state="visible")
    assert page.locator(".top").is_visible()


def test_the_floor_bar_does_not_swallow_the_chat_pill(page):
    """The bar across the bottom of the floor is a full width strip with
    transparent gaps. It sat on top of the Chat pill of whoever stood in the
    bottom row, so clicking them did nothing and the click reported
    "<div class=floor-bar> intercepts pointer events"."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".floor-bar").wait_for()
    assert frame.locator(".floor-bar").evaluate(
        "el => getComputedStyle(el).pointerEvents") == "none"
    assert frame.locator(".floor-bar a").first.evaluate(
        "el => getComputedStyle(el).pointerEvents") == "auto"


# --- a private word with one agent ------------------------------------------

def test_the_chat_starts_on_the_room(page):
    """The shared room is still the default and still what the page opens
    on: "that global chat is for all the ai"."""
    assert page.locator("#ap-agent").input_value() == ""
    assert page.locator("#ap-who").inner_text() == "Chat with your agents"
    assert page.locator("#ap-everyone").is_hidden()


def test_the_header_says_who_you_are_talking_to(page):
    """What you say is either heard by everybody or by nobody else at all,
    and which of the two has to be impossible to mistake."""
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(200)
    assert page.locator("#ap-who").inner_text() == "Chat with Iris"
    assert "Iris" in page.locator("#ap-sub").inner_text()
    assert "Iris" in page.locator(
        ".ap-composer input[name=message]").get_attribute("placeholder")


def test_there_is_a_way_back_to_everyone(page):
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(200)
    assert page.locator("#ap-everyone").is_visible()
    page.locator("#ap-everyone").click()
    page.wait_for_timeout(200)
    assert page.locator("#ap-agent").input_value() == ""
    assert page.locator("#ap-who").inner_text() == "Chat with your agents"


def test_who_you_are_talking_to_is_remembered(page):
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(250)
    page.reload()
    page.wait_for_selector("#office-dock", state="attached")
    page.wait_for_timeout(400)
    assert page.locator("#ap-agent").input_value() == "agent-iris-a103"


def test_the_message_carries_the_conversation_it_belongs_to(page):
    """The field is what the send posts. Without it a private message would
    be answered in the room, where everybody reads it."""
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(200)
    assert page.locator(
        ".ap-composer input[name=agent]").input_value() == "agent-iris-a103"


def test_fit_leaves_nothing_hanging_below_the_view(page):
    """"can you make it small.. so its fit tio the box."

    Measured at 860x470 with seven agents: the floor fitted across but the
    page was 81px taller than the frame, so the card showed a scrollbar and
    the bottom of the office was cut off. The fit reserved room for what sits
    ABOVE the floor and nothing for the live activity strip below it."""
    over = page.frame_locator("#office-body iframe").locator("body").evaluate(
        "() => document.documentElement.scrollHeight"
        " - document.documentElement.clientHeight")
    assert over <= 4, over


# --- the dock gives the floor the room it asked for -------------------------
#
# Ralph, with a screenshot of /ai-agents, 2026-09-29: the office was a sliver
# with a scrollbar and the rooms cut off at the bottom, reading 95% rather
# than Fit.
#
# Two defects, both measured in the dock and neither visible in the office on
# its own:
#
#  1. fitScale reserves the space above the floor AND below it (the Brain chip
#     and the live activity strip). tellHostOurHeight added back only the
#     space above. So the card it asked the page for was short by exactly the
#     strip underneath, and the floor got 171px of the 255px it sized itself
#     for. Fit then shrank to fill the height instead of the width.
#
#  2. drawZoom sized the wrapper to the full scaled canvas. Zoomed past Fit
#     inside a short dock, that made the iframe's own page taller than the
#     frame, so the office scrolled away rather than panning, which is what
#     the grab cursor has always promised.

SEVEN = [
    {"id": "agent-ada", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": ["code", "schedules"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-kai", "name": "Kai",
     "meta": {"role": "App reviewer", "toolIds": ["code"]},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
    {"id": "agent-rex", "name": "Rex",
     "meta": {"role": "Programmer", "toolIds": ["code"]},
     "params": {}, "user_id": "me", "created_at": 3, "updated_at": 3},
    {"id": "agent-mia", "name": "Mia",
     "meta": {"role": "Receptionist", "toolIds": ["gmail"]},
     "params": {}, "user_id": "me", "created_at": 4, "updated_at": 4},
    {"id": "agent-nora", "name": "Nora",
     "meta": {"role": "Calendar keeper", "toolIds": ["calendar"]},
     "params": {}, "user_id": "me", "created_at": 5, "updated_at": 5},
    {"id": "agent-iris", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 6, "updated_at": 6},
    {"id": "agent-vera", "name": "Vera",
     "meta": {"role": "Researcher", "toolIds": ["server:mcp-proxy"]},
     "params": {}, "user_id": "me", "created_at": 7, "updated_at": 7},
]

#: Read from inside the frame, because every one of these numbers is a
#: property of the office in the dock and none of them is visible from the
#: office on its own.
_DOCK = """() => {
  const fr = document.getElementById('office-dock').querySelector('iframe');
  const d = fr.contentDocument, w = fr.contentWindow;
  const fit = d.getElementById('floor-fit');
  const rooms = d.getElementById('rooms');
  const f = fit.getBoundingClientRect(), r = rooms.getBoundingClientRect();
  return { scrolls: d.body.scrollHeight > w.innerHeight + 1,
           clippedX: r.right > f.right + 1 || r.left < f.left - 1,
           clippedY: r.bottom > f.bottom + 1 || r.top < f.top - 1,
           boxW: f.width, boxH: f.height,
           drawnW: r.width, drawnH: r.height,
           zoom: d.getElementById('zoom-fit').textContent }; }"""


def _dock(browser, server, zoom=None, stale=False):
    ctx = browser.new_context(viewport={"width": 1920, "height": 1050})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": SEVEN, "total": len(SEVEN)}
        elif "/agents/activity" in url:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": {}}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    if zoom is not None:
        pg.add_init_script(
            "try{localStorage.setItem('aiuiOfficeZoom2','%s')}catch(e){}" % zoom)
    if stale:
        # What the owner's browser actually held on 2026-09-29: a height and a
        # zoom chosen for the 1040x680 floor that no longer exists.
        pg.add_init_script(
            "try{localStorage.setItem('aiuiOfficeZoom','0.95');"
            "localStorage.setItem('aiuiOfficeHeight','150')}catch(e){}")
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.wait_for_selector("#office-dock", state="attached")
    # The card resizes itself once the office reports what it needs, so this
    # waits for the settled layout rather than the first paint.
    pg.wait_for_timeout(2500)
    return ctx, pg


def test_the_office_in_the_dock_does_not_scroll_away(browser, server):
    """The floor is panned, not scrolled. A page taller than its frame put
    the office out of sight inside a short card."""
    ctx, pg = _dock(browser, server)
    try:
        got = pg.evaluate(_DOCK)
        assert not got["scrolls"], got
    finally:
        ctx.close()


def test_a_saved_zoom_still_does_not_scroll_the_dock(browser, server):
    """A zoom the box cannot hold is what panning is for, not what the
    office's own page scrolling is for."""
    ctx, pg = _dock(browser, server, zoom="0.95")
    try:
        got = pg.evaluate(_DOCK)
        assert got["zoom"] == "95%", got
        assert not got["scrolls"], got
    finally:
        ctx.close()


def test_fit_uses_the_width_the_dock_gives_it(browser, server):
    """The office asks the page for a card tall enough to show the whole
    floor. If it asks for too little, Fit shrinks to the height it was given
    and leaves a third of the width empty, which is what the screenshot
    showed."""
    ctx, pg = _dock(browser, server)
    try:
        got = pg.evaluate(_DOCK)
        assert got["zoom"] == "Fit", got
        assert not got["clippedX"] and not got["clippedY"], got
        used = got["drawnW"] / got["boxW"]
        assert used >= 0.85, got
    finally:
        ctx.close()


def test_a_height_chosen_for_the_old_floor_is_not_obeyed(browser, server):
    """The fix that reaches the owner's actual screen.

    A saved height blocks the floor's own suggestion (agents.html: `!chosen
    && saved(HEIGHT_KEY) == null`). His browser held 150px, chosen when the
    floor was a fixed 1040x680 canvas, so every repair to the layout would
    have been invisible to him for good: the office would have stayed the
    sliver in his screenshot no matter what was deployed.

    A remembered height is a choice about a particular floor. That floor is
    gone, so the value is ignored exactly once and the next drag is
    remembered as normal."""
    ctx, pg = _dock(browser, server, stale=True)
    try:
        got = pg.evaluate(_DOCK)
        assert got["zoom"] == "Fit", got
        assert not got["scrolls"], got
        assert not got["clippedX"] and not got["clippedY"], got
        assert got["drawnW"] / got["boxW"] >= 0.85, got
    finally:
        ctx.close()


# --- nothing in the office loads a bare page --------------------------------
#
# Design 2026-10-05, finding 5: every office link is target=_top and only the
# Chat pills were intercepted, so The Brain, Call a team meeting, the skill
# links and Edit agent each replaced the whole Open WebUI window with a bare
# page. Hosted by the agents page they are now messages to it. Framed straight
# into the shell (the Agent Office pane) they are aiui:open-pane messages to
# the shell. Anywhere else they are still followed, which
# test_a_frame_that_does_not_host_the_office_still_follows_the_link pins.

SKILLED = [
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"],
              "skillIds": ["find-my-file"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    OFFICE_AGENTS[1],
]
SKILL_CATALOGUE = [{"name": "find-my-file", "description": "Find a file.",
                    "tools": ["gdrive"], "tags": ["files"]}]


def _as_owner(browser, server, agents=None, url="/agents.html"):
    """The agents page signed in as the owner of the office's agents.

    The default fixture answers /api/v1/auths/ with no id, which the page
    reads as no identity, so it has no agents of its own and nothing to edit.
    """
    roster = agents or OFFICE_AGENTS
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        u = r.request.url
        if "/api/v1/auths/" in u:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in u:
            body = {"items": roster, "total": len(roster)}
        elif "/agents/activity" in u:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/stats" in u:
            body = {"stats": {}}
        elif "/agents/skills" in u:
            body = {"skills": SKILL_CATALOGUE}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d%s" % (server.server_address[1], url))
    return ctx, pg


def test_the_embedded_office_does_not_offer_to_open_the_page_it_is_in(page):
    """"Open the chat" points at /tasks/agents, which is the page around the
    floor. Followed, it reloaded the page; it has nothing to do here."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".floor-bar").wait_for()
    said = frame.locator(".floor-bar a").all_inner_texts()
    assert "Open the chat" not in said, said
    assert any("team meeting" in s for s in said), said


def test_the_meeting_button_fills_the_room_in_place(page):
    """Call a team meeting hands over "everyone answer: ". It is a question
    for the room, so a private conversation that happens to be open is left
    for the room first: in Iris's own thread only Iris would hear it."""
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(200)
    frame = page.frame_locator("#office-body iframe")
    meeting = frame.locator(".floor-bar a.btn").first
    meeting.wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    meeting.click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the page reloaded"
    assert page.locator("#ap-agent").input_value() == ""
    assert page.locator(".ap-composer input[name=message]").input_value(
        ) == "everyone answer: "


def test_a_skill_opens_that_agents_conversation_with_the_question(browser, server):
    """The skill link says "Iris, find my file". It opens Iris's own
    conversation and leaves the question in the box, unsent."""
    ctx, pg = _as_owner(browser, server, agents=SKILLED)
    try:
        frame = pg.frame_locator("#office-body iframe")
        frame.locator('.who[data-id="agent-iris-a103"]').click()
        skill = frame.locator("#side a.skill").first
        skill.wait_for()
        pg.evaluate("() => { window.__stillHere = true; }")
        skill.click()
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__stillHere === true"), "the page reloaded"
        assert pg.locator("#ap-agent").input_value() == "agent-iris-a103"
        assert pg.locator(".ap-composer input[name=message]").input_value(
            ) == "find my file"
    finally:
        ctx.close()


def test_edit_agent_in_the_office_opens_the_form_on_this_page(browser, server):
    """Edit agent linked to /tasks/agents, which reloaded this page and
    opened nothing. The page around the floor has the form already."""
    ctx, pg = _as_owner(browser, server)
    try:
        pg.wait_for_selector('#my-agents .card[data-agent-id="agent-iris-a103"]',
                             state="attached")
        frame = pg.frame_locator("#office-body iframe")
        frame.locator('.who[data-id="agent-iris-a103"]').click()
        edit = frame.locator("#side a", has_text="Edit agent")
        edit.wait_for()
        pg.evaluate("() => { window.__stillHere = true; }")
        edit.click()
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__stillHere === true"), "the page reloaded"
        assert pg.locator("#agent-overlay").is_visible()
        assert pg.locator("#form-title").inner_text() == "Edit agent"
        assert pg.locator("#agent-name").input_value() == "Iris"
    finally:
        ctx.close()


def test_the_brain_opens_the_graph_pane_and_leaves_the_page_alone(browser, server):
    """Inside the shell the agents page asks the shell for its Graph pane,
    the same pane a click on the sidebar entry opens. The shell document is
    not replaced and the agents page stays where it is."""
    ctx, pg = _as_owner(browser, server, url="/shell-agents")
    try:
        office = pg.frame_locator("#pane").frame_locator("#office-body iframe")
        office.locator(".brain a").wait_for()
        pg.wait_for_timeout(300)
        office.locator(".brain a").click()
        pg.wait_for_timeout(400)
        origin = "http://127.0.0.1:%d" % server.server_address[1]
        got = pg.evaluate("() => window.__panes || null")
        assert got == [{"data": {"type": "aiui:open-pane", "path": "/graph"},
                        "origin": origin}], got
        assert pg.locator("#pane").evaluate(
            "f => f.contentWindow.location.pathname") == "/agents.html"
    finally:
        ctx.close()


def test_in_the_shell_a_chat_pill_asks_for_the_agents_pane(page, server):
    """The Agent Office pane on its own, inside the shell. Nobody hosts it,
    so its Chat pill asks the shell to open AI Agents with the question, and
    names the agent the way it does when docked, so the agents page can open
    that agent's own conversation either way."""
    page.goto("http://127.0.0.1:%d/shell" % server.server_address[1])
    office = page.frame_locator("#pane")
    office.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    assert page.evaluate("() => window.__aiuiTaskPanelLoaded === true")
    # Standalone, so the floor still offers the chat.
    assert office.locator(".floor-bar a", has_text="Open the chat").count() == 1
    page.evaluate("() => { window.__stillHere = true; }")
    office.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the shell was replaced"
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    assert page.evaluate("() => window.__panes") == [
        {"data": {"type": "aiui:open-pane", "path": "/ai-agents",
                  "ask": "Iris, ", "agent": "agent-iris-a103", "name": "Iris"},
         "origin": origin}]


def test_in_the_shell_the_brain_asks_for_the_graph_pane(page, server):
    page.goto("http://127.0.0.1:%d/shell" % server.server_address[1])
    office = page.frame_locator("#pane")
    office.locator(".brain a").wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    office.locator(".brain a").click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the shell was replaced"
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    assert page.evaluate("() => window.__panes") == [
        {"data": {"type": "aiui:open-pane", "path": "/graph"}, "origin": origin}]


def test_on_its_own_the_agents_page_still_opens_the_graph(page):
    """Guard, passes before and after: /tasks/agents with no shell around it
    has no pane to open, so The Brain still reaches the graph page."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".brain a").wait_for()
    page.wait_for_timeout(300)
    frame.locator(".brain a").click()
    page.wait_for_url("**/tasks/graph")
