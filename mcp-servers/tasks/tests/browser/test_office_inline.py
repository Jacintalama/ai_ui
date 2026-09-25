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

def test_chatting_from_the_office_fills_the_box_where_you_are(page):
    """A chat link that navigated would tear the floor down and rebuild it on
    every click. Inside the page it hands the question to the column."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the page reloaded"
    assert page.locator(".ap-composer input[name=message]").input_value(
        ).startswith("Iris,")


def test_it_fills_the_box_and_stops(page):
    """The same rule the ?ask= links follow: a turn costs money and can run
    tools, so it is never sent on the person's behalf."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.locator(".ap-composer input[name=message]").input_value() == "Iris, "


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
