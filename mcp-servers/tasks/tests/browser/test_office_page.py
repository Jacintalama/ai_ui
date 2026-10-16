"""The Agent Office draws what the platform actually recorded.

Every number on the page comes from tasks.agent_run, which has recorded runs
since migration 041 and had never been shown anywhere. Measured on production
2026-09-24: one person's Ada had 801 runs at 30.4s and 40% success, Iris 26 at
5.4s and 100%, and no surface could tell those two apart.

The page must also not invent. Agents cannot address each other and the tool
loop records no calls, so anything the page draws about either would be a
puppet show.
"""
import http.server
import json
import pathlib
import re
import sys
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
sys.path.insert(0, str(STATIC.parent))
# The hue the cards and the chat thread give an agent. Read from the producer
# rather than re-implemented here, so the office is held to the real thing.
import agent_chat_render as render                        # noqa: E402

AGENTS = [
    {"id": "agent-research-assistant-0001", "name": "Ada",
     "meta": {"role": "Project manager", "description": "Keeps things moving.",
              "toolIds": ["code", "schedules", "remember", "account", "skills"],
              "skillIds": ["weekly-review", "daily-standup"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "description": "Finds your files.",
              "toolIds": ["gdrive"], "skillIds": ["find-my-file"]},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
    # Not an agent. The listing carries every model this person can see, and
    # the page must not draw gpt-5 as a colleague.
    {"id": "gpt-5", "name": "gpt-5", "meta": {}, "params": {},
     "user_id": "me", "created_at": 3, "updated_at": 3},
]

# The REAL shape agent_activity._shape returns. An earlier version of this
# fixture invented "started_at" and "status"; the page was written against the
# invention, every test passed, and production read undefined for both. Mia,
# with 761 recorded runs, said "No runs recorded yet" and every live card said
# "never" (owner's screenshot, 2026-09-25). A fixture that does not match the
# producer tests nothing but itself.
ACTIVITY = {
    "agent-research-assistant-0001": {
        "state": "working", "running_for_seconds": 12,
        "last_run_at": "2026-09-24T10:02:22+00:00", "source": "channel"},
    "agent-iris-a103": {
        "state": "ready", "last_duration_seconds": 5,
        "last_status": "completed", "last_run_at": "2026-09-24T09:00:00+00:00",
        "source": "schedule"},
}

#: What the floor draws a collaboration from. Every entry is a tool call
#: that really happened: agent_step rows with the colleague's RESOLVED id.
#: Empty by default, so the default fixture proves the floor invents nothing.
HANDOFFS = []

STATS = {
    "agent-research-assistant-0001": {
        "runs": 801, "avg_seconds": 30.4, "success_pct": 40,
        "last_started": "2026-09-24T10:02:22+00:00", "cost_usd": 0.055},
    "agent-iris-a103": {
        "runs": 26, "avg_seconds": 5.4, "success_pct": 100,
        "last_started": "2026-09-24T09:00:00+00:00", "cost_usd": 0.04},
}


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def _serve(html: bytes):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            # The page's stylesheet lives in static/office/ since 2026-10-08.
            # A fixture that answered every path with the page itself would
            # serve HTML where a stylesheet was asked for, and every geometry
            # assertion here would be measuring an unstyled document. That
            # has already happened once on this file.
            path = self.path.split("?")[0]
            body, kind = html, "text/html"
            if path.startswith("/tall-frame"):
                # The shell: the office is a pane, an iframe at height:100%
                # of a container taller than the window. Inside it
                # window.innerHeight is the IFRAME's height, not what anyone
                # can see.
                body = (b'<!doctype html><title>shell</title>'
                        b'<style>html,body{margin:0;background:#000}'
                        b'.pane{height:1600px}</style>'
                        b'<div class="pane">'
                        b'<iframe src="/office.html" '
                        b'style="width:100%;height:100%;border:0"></iframe>'
                        b'</div>')
            elif path.startswith("/tasks/agents/chat/"):
                # The conversation's own routes. Answering these with the
                # page itself HUNG THE WHOLE SUITE: htmx loads the thread on
                # load, the page came back, and the page carries the same
                # hx-get, so it fetched itself for ever. Worth knowing
                # outside the tests too, since an auth redirect to a login
                # page would do the same thing in a browser.
                body, kind = b'<div class="aempty">nothing yet</div>', "text/html"
                if path.endswith("/stream"):
                    self.send_response(204)
                    self.end_headers()
                    return
            elif (path.endswith("/agent-chat.css") or path.endswith("/agent-chat.js")
                  or path.endswith("/htmx.min.js") or path.endswith("/sse.js")
                  or path.endswith("/marked.min.js") or path.endswith("/purify.min.js")):
                # The conversation in the side column is styled by the agents
                # page's own stylesheet and driven by htmx and its SSE
                # extension, which is what opens the answer. Answering those
                # with the page itself served HTML where a stylesheet was
                # asked for, which is the exact trap the comment above
                # describes, one directory over.
                rel = path.rsplit("/", 1)[1]
                asset = (STATIC / rel if (STATIC / rel).is_file()
                         else STATIC / "vendor" / rel)
                if not asset.is_file():
                    self.send_error(404, "no such asset: %s" % rel)
                    return
                body = asset.read_bytes()
                kind = "text/css" if rel.endswith(".css") else "text/javascript"
            elif "/office/" in path:
                rel = path.split("/office/", 1)[1]
                asset = STATIC / "office" / rel
                if not asset.is_file():
                    self.send_error(404, "no such asset: %s" % rel)
                    return
                body = asset.read_bytes()
                kind = "text/css" if rel.endswith(".css") else "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def page(browser, request):
    stats = getattr(request, "param", STATS)
    html = (STATIC / "office.html").read_bytes()
    srv = _serve(html)
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": ACTIVITY, "handoffs": HANDOFFS}
        elif "/agents/stats" in url:
            body = {"stats": stats}
        elif "/agents/skills" in url:
            body = {"skills": SKILLS}
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    yield pg
    pg.close()
    srv.shutdown()


@pytest.fixture
def docked(browser):
    """The office as the small card on the agents page sees it.

    The zoom and the drag live here and nowhere else since 2026-10-08. On the
    full page the floor is stretched to the shape of its box, so there is no
    off-screen floor to reach for; in a card a few hundred pixels tall the
    plan really is bigger than the box, and moving around it is how you see
    the rest."""
    html = (STATIC / "office.html").read_bytes()
    srv = _serve(html)
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": ACTIVITY, "handoffs": HANDOFFS}
        elif "/agents/stats" in url:
            body = {"stats": STATS}
        elif "/agents/skills" in url:
            body = {"skills": SKILLS}
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html?embed=1" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    yield pg
    pg.close()
    srv.shutdown()


def test_it_shows_an_agent_per_card_and_nothing_else(page):
    """The model listing carries every model the person can see. Only the
    agent- rows are colleagues; gpt-5 is not one."""
    names = page.locator(".card-name").all_inner_texts()
    assert names == ["Ada", "Iris"], names


def test_the_numbers_are_the_recorded_ones(page):
    page.locator('.who[data-id="agent-research-assistant-0001"]').click()
    side = page.locator("#side").inner_text()
    assert "801" in side
    assert "30.4s" in side
    assert "40%" in side


def test_a_second_agent_shows_its_own_numbers_not_the_first_ones(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    side = page.locator("#side").inner_text()
    assert "26" in side and "5.4s" in side and "100%" in side
    assert "801" not in side


def test_an_agent_mid_run_reads_as_working(page):
    card = page.locator('.who[data-id="agent-research-assistant-0001"]')
    assert "Working" in card.inner_text()
    assert page.locator('.who[data-id="agent-research-assistant-0001"] .dot.working'
                        ).count() == 1


def test_the_header_says_how_many_are_working(page):
    assert "working now" in page.locator("#sub").inner_text()


def test_search_narrows_by_role_not_just_name(page):
    page.fill("#q", "librarian")
    page.wait_for_timeout(200)
    names = page.locator(".card-name").all_inner_texts()
    assert names == ["Iris"], names


def test_the_activity_tab_lists_runs_newest_first(page):
    page.locator("#tab-activity").click()
    page.wait_for_timeout(200)
    rows = page.locator("#activity-feed li").all_inner_texts()
    assert len(rows) == 2
    assert "Ada" in rows[0], rows


def test_the_page_says_what_it_cannot_show(page):
    """It must not imply agents talk to each other or that tool use is
    tracked. Neither is true, and a page that invents activity is worse than
    one that admits the gap."""
    page.locator("#tab-activity").click()
    page.wait_for_timeout(200)
    said = page.locator("#panel-activity").inner_text().lower()
    assert "neither is recorded" in said
    assert "cannot address one another" in said
    assert "which tool a run used" in said


@pytest.mark.parametrize("page", [{}], indirect=True)
def test_an_agent_with_no_runs_shows_no_success_rate(page):
    """A new agent has never run. Drawing 0% against it says something
    untrue, so the rate is a dash until there is one."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    side = page.locator("#side").inner_text()
    # The floor marker carries the name and the live state; the record lives
    # in the panel, which is where a count of zero belongs.
    assert "Total runs\n0" in side, side
    assert "0%" not in side


@pytest.mark.parametrize("page", [{}], indirect=True)
def test_losing_the_stats_still_draws_the_agents(page):
    """The aggregate is an extra read. Losing it must cost the numbers, not
    the page: the same rule every optional read in this codebase follows."""
    assert page.locator(".who").count() == 2


# --- the floor is a picture of how the agents are set up --------------------
# A desk is chosen from the tools an agent actually holds, so the office shows
# this person's own arrangement rather than a seating plan somebody typed.

def test_the_floor_names_the_rooms_that_are_in_use(page):
    """Case-insensitive on purpose: the labels are upper-cased by CSS, and
    inner_text reports what is rendered rather than what is written.

    Only occupied rooms are drawn, so this names the two the fixture actually
    fills, plus the meeting room. Ada holds BOTH code and schedules, and the
    first matching area wins, so she sits in Development rather than
    Automation; Iris holds gdrive and sits at the Knowledge base. An empty
    room is scenery, with the one exception below."""
    zones = [z.lower() for z in page.locator(".zone-head > span:first-child").all_inner_texts()]
    # Your desk is a fixture too (2026-10-16): it is where an agent with a
    # question for you goes to stand.
    assert sorted(zones) == ["development", "knowledge base", "meeting room", "your desk"], zones




# --- being able to actually use what an agent can do ------------------------
# 67 skills ship with the image and an agent is given some of them, but the
# only place a person could ever see one is inside the agent edit form, in a
# section collapsed by default because "most edits never touch skills". So the
# person who opens the office has no idea what to ask for, and the features
# are unreachable rather than missing.

SKILLS = [
    {"name": "weekly-review",
     "description": "Summarise the week: what shipped, what slipped.",
     "tools": ["code", "schedules"], "tags": ["planning"]},
    {"name": "daily-standup", "description": "What happened yesterday.",
     "tools": [], "tags": ["planning"]},
    {"name": "find-my-file", "description": "Find a file in Drive.",
     "tools": ["gdrive"], "tags": ["files"]},
]


def test_the_panel_says_what_the_agent_can_do(page):
    """Ada holds weekly-review and daily-standup. A person must be able to see
    that without opening a settings form."""
    page.locator('.who[data-id="agent-research-assistant-0001"]').click()
    said = page.locator("#side").inner_text().lower()
    assert "weekly review" in said, said
    assert "daily standup" in said, said


def test_a_skill_is_one_click_to_ask_for(page):
    """Seeing it is half of it. The other half is not having to work out the
    wording, so each one is a link that hands the chat a message naming the
    agent, which is what the routing ladder matches on."""
    page.locator('.who[data-id="agent-research-assistant-0001"]').click()
    href = page.locator("#side a.skill").first.get_attribute("href")
    assert href.startswith("/tasks/agents?ask="), href
    assert "Ada" in href
    assert "weekly" in href.lower()


def test_an_agent_is_only_offered_its_own_skills(page):
    """Iris holds find-my-file. Offering her the weekly review would be
    offering something she was never given."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    said = page.locator("#side").inner_text().lower()
    assert "find my file" in said, said
    assert "weekly review" not in said, said


def test_chat_with_an_agent_opens_a_chat_aimed_at_that_agent(page):
    """"Chat with Mia" has to mean Mia, not the room.

    A room message is heard by everyone and each decides whether to answer, so
    a person who wanted one agent gets whoever felt like speaking. Naming the
    agent is what the routing ladder matches on, and a named agent answers and
    may not pass, so the composer is handed its name and a comma and the
    person types the rest."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    href = page.locator("#side a.chat-with").get_attribute("href")
    assert href.startswith("/tasks/agents?ask="), href
    from urllib.parse import unquote
    assert unquote(href.split("ask=", 1)[1]) == "Iris, "


def test_the_chat_link_names_the_agent_you_picked(page):
    page.locator('.who[data-id="agent-research-assistant-0001"]').click()
    href = page.locator("#side a.chat-with").get_attribute("href")
    from urllib.parse import unquote
    assert unquote(href.split("ask=", 1)[1]) == "Ada, "


# --- times, which is where the page was quietly lying -----------------------
# Owner's screenshot 2026-09-25: Mia's panel said "No runs recorded yet" while
# her record beside it said 761 runs, and every live card said "never". The
# page read a.started_at and a.status; agent_activity._shape returns
# last_run_at and last_status. Both were undefined, so every time rendered as
# "never" and the presence check for a run failed.

def test_the_panel_says_when_the_last_run_was(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    said = page.locator("#side").inner_text().lower()
    assert "no runs recorded yet" not in said, said
    assert "never" not in said, said
    assert "ago" in said, said


def test_the_live_strip_says_when_not_never(page):
    said = page.locator("#live").inner_text().lower()
    assert "never" not in said, said
    assert "ago" in said, said


def test_a_finished_run_shows_the_status_it_finished_with(page):
    """last_status, not status. Iris completed hers."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    assert "completed" in page.locator("#side").inner_text().lower()


def test_an_agent_that_truly_never_ran_still_says_so(page):
    """The opposite mistake is as bad. An agent with no activity row at all
    must not borrow somebody else's time."""
    page.locator('.who[data-id="agent-research-assistant-0001"]').click()
    # Ada IS running, so this asserts the other side stays correct rather
    # than that "no runs" disappeared entirely.
    assert "running now" in page.locator("#side").inner_text().lower()



# The owner's real seven, with the tools each actually holds on production.
SEVEN = [
    {"id": "agent-inbox-triage-0002", "name": "Mia",
     "meta": {"role": "Receptionist", "toolIds": ["gmail"]}, "params": {}},
    {"id": "agent-research-assistant-0001", "name": "Ada",
     "meta": {"role": "Project manager",
              "toolIds": ["account", "code", "remember", "schedules", "skills"]},
     "params": {}},
    {"id": "agent-kai-a100", "name": "Kai",
     "meta": {"role": "App reviewer", "toolIds": ["code"]}, "params": {}},
    {"id": "agent-rex-a101", "name": "Rex",
     "meta": {"role": "Programmer", "toolIds": ["code"]}, "params": {}},
    {"id": "agent-nora-a102", "name": "Nora",
     "meta": {"role": "Calendar keeper", "toolIds": ["calendar", "remember"]},
     "params": {}},
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]}, "params": {}},
    {"id": "agent-vera-a104", "name": "Vera",
     "meta": {"role": "Researcher",
              "toolIds": ["server:mcp-proxy", "remember", "video"]}, "params": {}},
]



# --- a headline per room ----------------------------------------------------
# From the reference the owner sent: a room is worth a number. Every figure is
# an aggregate of the agents standing in THAT room, so a room that sums
# somebody else's runs is the bug that looks perfectly fine.

def test_each_room_with_somebody_in_it_gets_a_card(page):
    labels = [t.lower() for t in page.locator(".zone-head > span:first-child").all_inner_texts()]
    assert any("knowledge base" in t for t in labels), labels
    # Ada in Development, Iris at Knowledge base, the meeting room and your
    # desk, which are on the floor whether or not anybody is in them.
    assert len(labels) == 4, labels


def test_an_empty_room_gets_no_card(page):
    """A row of zeroes against a room nobody works in says nothing and makes
    the floor look busy. Only rooms with agents in them get a headline."""
    labels = " ".join(page.locator(".zone-head > span:first-child").all_inner_texts()).lower()
    assert "research" not in labels, labels
    assert "automation" not in labels, labels


def test_the_meeting_room_is_always_on_the_floor(page):
    """The one room that is drawn empty, and deliberately. A meeting is
    agents walking INTO a room now rather than a table appearing in a band
    above the floor, and a room people are called to has to be somewhere
    they can already see. Nobody is in a meeting in this fixture."""
    labels = " ".join(page.locator(".zone-head > span:first-child").all_inner_texts()).lower()
    assert "meeting room" in labels, labels
    assert page.locator('.zone[data-room="meeting"]').count() == 1
    # Empty, so it says nothing about anybody's runs.
    assert page.locator('.zone[data-room="meeting"] .meeting-table').count() == 0


def test_a_room_counts_only_its_own_agents_runs(page):
    """Ada is alone in Automation with 801 runs; Iris is alone at the
    knowledge base with 26. Neither card may carry the other's."""
    cards = page.locator(".zone").all_inner_texts()
    joined = " ".join(cards)
    assert "801" in joined and "26" in joined, cards
    for text in cards:
        assert not ("801" in text and "26" in text), text


def test_the_room_card_weights_success_by_runs(page):
    """success_pct is a percentage of one agent's own runs. Averaging two
    agents' percentages would let an agent with three runs outvote one with
    eight hundred, so it is weighted back into runs first. Alone in a room,
    an agent's own rate must survive the arithmetic unchanged."""
    cards = page.locator(".zone").all_inner_texts()
    ada = [c for c in cards if "801" in c][0]
    assert "40%" in ada, ada



def test_the_figure_wears_the_agents_colour(page):
    """One figure per agent in its own colour, so the floor is readable at a
    glance rather than a row of identical silhouettes.

    Read off the button, which is where the colour is set and where the dot
    and the label inherit it from. This used to select .who-inner, a class
    that has never existed here: it matched nothing, compared an empty list
    with itself, and passed however the floor was painted."""
    colours = page.locator(".who").evaluate_all(
        "els => els.map(e => getComputedStyle(e).color)")
    assert len(colours) == 2, colours
    assert len(set(colours)) == len(colours), colours



def test_a_working_agent_still_pulses(page):
    """The halo moved from around a disc to around the chair. It has to
    survive the redraw, because it is the only thing on the floor that says
    something is happening right now."""
    assert page.locator('.who[data-state="working"]').count() == 1




def test_the_brain_is_on_the_floor_and_goes_somewhere_real(page):
    """The reference puts the Brain in the middle. Ours is a real page every
    agent reads before answering, so it links there rather than decorating."""
    assert page.locator(".brain a").get_attribute("href") == "/tasks/graph"


def test_the_brain_claims_no_note_count(page):
    """The reference shows "37 NOTES". Nothing on this page counts notes, and
    a number nobody computed is the one thing this office must not draw."""
    said = page.locator(".brain").inner_text().lower()
    assert "notes" not in said, said




def test_a_room_nobody_works_in_is_not_drawn(browser):
    """Same screenshot: a large blank slab sat top-centre with no label and
    nobody on it. An empty room is scenery, and scenery is what made the
    floor unreadable."""
    html = (STATIC / "office.html").read_bytes()
    srv = _serve(html)
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": [SEVEN[0]], "total": 1}   # Mia alone, in Communication
        elif "/agents/skills" in url:
            body = {"skills": SKILLS}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        else:
            body = {"activity": {}}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    pg.wait_for_timeout(300)
    try:
        labels = [t.lower() for t in pg.locator(".zone-head > span:first-child").all_inner_texts()]
        # Mia's room, and the meeting room, which is always there. Research,
        # Development, Knowledge base and Automation are all still scenery.
        assert labels == ["communication", "meeting room", "your desk"], labels
        assert pg.locator(".zone").count() == 3
    finally:
        pg.close()
        srv.shutdown()


# --- departments, which replaced the isometric floor ------------------------
# The floor was reshaped five times and the owner could not read it either
# time he looked: "i cant understand!", then "the ui or the page isnt nice".
# A drawn plate spends the whole screen on a picture and leaves the numbers at
# 11px inside it. These are the two things the floor was for that the sections
# still have to do.

def test_an_agent_stands_inside_the_room_its_tools_belong_to(page):
    """Iris holds gdrive, so she stands within the Knowledge base room and
    nowhere else. The grouping is the whole idea the floor carries.

    Measured by geometry rather than by nesting: agents are drawn ABOVE the
    rooms so a name label is never clipped by a wall, which means Iris is a
    sibling of the room rather than a child of it."""
    got = page.evaluate(
        "() => {"
        " const room = [...document.querySelectorAll('section.zone')]"
        "   .find(z => z.textContent.toLowerCase().includes('knowledge base'));"
        " const iris = document.querySelector('.who[data-id=\"agent-iris-a103\"]');"
        " const r = room.getBoundingClientRect(), i = iris.getBoundingClientRect();"
        " return { inside: i.left >= r.left && i.right <= r.right"
        "                  && i.top >= r.top && i.bottom <= r.bottom,"
        "          r: [r.left, r.right], i: [i.left, i.right] }; }")
    assert got["inside"], got


def test_each_department_is_its_own_colour(page):
    """Six identical rooms is what made the floor unreadable. The colour now
    rides the section's left border, and each department keeps its own."""
    edges = page.locator("section.zone").evaluate_all(
        "els => els.map(e => getComputedStyle(e).borderLeftColor)")
    assert len(set(edges)) == len(edges), edges


def test_the_page_uses_the_products_own_colours(page):
    """AIUI Cyan Circuit: #22D3EE on #0B1221, as recorded in
    webhook-handler/schedule_format.py. The office is part of the product, not
    a separate thing that happens to live inside it."""
    got = page.evaluate(
        "() => { const s = getComputedStyle(document.body);"
        " return { bg: s.backgroundColor,"
        "   cyan: getComputedStyle(document.documentElement)"
        "          .getPropertyValue('--cyan').trim() }; }")
    assert got["cyan"].lower() == "#22d3ee", got
    assert got["bg"].replace(" ", "") == "rgb(11,18,33)", got


def test_a_team_meeting_is_a_real_one(page):
    """The owner's mockup has two buttons: "Simulate Collaboration" and "Team
    Meeting". Only one of them can be true.

    A meeting is real: choose_speakers has a meeting rung, so "everyone
    answer" wakes every agent with may_pass false and all of them reply. The
    button hands the chat exactly those words."""
    ask = page.locator("#brain-actions .chat-open[data-ask]").get_attribute("data-ask")
    assert ask.startswith("everyone answer"), ask
    # Inside the agents page's dock, where the chat is the page around the
    # floor, the bar's link hands those same words to it.
    assert "everyone answer" in page.evaluate(
        "() => decodeURIComponent(document.querySelector('#brain-actions .chat-open[data-ask]').dataset.ask)")


def test_there_is_no_button_that_fakes_agents_talking(page):
    """"Simulate Collaboration" walks Mia to Ada and shows them speaking.
    Agents cannot address one another, so that button would animate an event
    the system never emits. It is the one thing this page must not add."""
    said = page.locator("#rooms").inner_text().lower()
    assert "simulate" not in said, said
    assert "collaborat" not in said, said


def test_an_agent_that_is_working_says_so_on_the_floor(page):
    """A coloured dot says something is happening without saying what, and
    "Working 12s" is the reason to look at the floor at all."""
    label = page.locator('.who[data-id="agent-research-assistant-0001"] .who-label').inner_text()
    assert "Working" in label, label


def test_an_idle_agent_shows_its_job_instead(page):
    """When there is nothing happening the label is worth spending on the
    role, which is what tells one agent from another."""
    label = page.locator('.who[data-id="agent-iris-a103"] .who-label').inner_text()
    assert "Drive librarian" in label, label


# --- links have to leave the frame ------------------------------------------
# Owner's screenshot 2026-09-25: the floating office was showing the AGENTS
# PAGE inside itself, with "everyone answer:" already in its composer. He had
# clicked Call a team meeting inside the office and the link navigated the
# iframe rather than the page behind it, so the office replaced itself with
# the chat. Every link here goes somewhere else in the product, and the office
# is embedded in two places: the shell pane and the floating window.

def test_every_link_out_of_the_office_leaves_the_frame(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    bad = page.evaluate(
        "() => [...document.querySelectorAll('a[href]')]"
        "  .filter(a => a.getAttribute('target') !== '_top')"
        "  .map(a => a.getAttribute('href'))")
    assert bad == [], bad


def test_in_the_agents_pages_dock_the_meeting_button_leaves_the_frame(docked):
    """There the chat is the page around the floor, so the bar keeps a
    meeting link that reaches it, and it leaves the frame."""
    from urllib.parse import unquote
    link = docked.locator(".floor-bar a.btn").first
    assert link.get_attribute("target") == "_top"
    href = link.get_attribute("href")
    assert unquote(href.split("ask=", 1)[1]).startswith("everyone answer")


def test_the_windows_stand_over_the_floor_not_the_column(page):
    """A window across the agent card covered "Chat with Ada"."""
    win = page.locator("#cw-team").bounding_box()
    side = page.locator("#side").bounding_box()
    assert win["x"] + win["width"] <= side["x"] + 1, (win, side)


def test_the_chat_and_skill_links_leave_the_frame(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    assert page.locator("#side a.chat-with").get_attribute("target") == "_top"
    assert page.locator("#side a.skill").first.get_attribute("target") == "_top"


# --- robot faces, and a colour the person picks -----------------------------
# From the owner's own reference, assets/AI Agent Robots.html, which builds a
# robot from a triple: body, a darker body2 for the gradient, and an accent
# for the eyes, hands and antenna. Six palettes ship with it.

def test_every_agent_is_drawn_as_a_robot(page):
    assert page.locator(".who svg.bot").count() == page.locator(".who").count()
    assert page.locator(".who .bot-eye").count() >= 2


def test_the_robot_carries_the_agents_colour(page):
    """Two agents, two palettes. A floor of identical robots is a floor you
    cannot read, which is the thing that keeps going wrong here."""
    fills = page.locator(".who svg.bot .bot-body").evaluate_all(
        "els => els.map(e => e.getAttribute('fill'))")
    assert len(set(fills)) == len(fills), fills


def test_a_working_agent_wears_the_thinking_face(page):
    """The reference has moods. The one that earns its place is thinking,
    because an agent mid-run is the only thing on this floor that is
    happening, and a face says it faster than a label."""
    ada = page.locator('.who[data-id="agent-research-assistant-0001"] svg.bot')
    # Any mark, not a count: how many shapes make the squint is the drawing's
    # business, and the idle test below is what proves the mood is a choice.
    assert ada.locator(".bot-think").count() >= 1


def test_an_idle_agent_does_not(page):
    iris = page.locator('.who[data-id="agent-iris-a103"] svg.bot')
    assert iris.locator(".bot-think").count() == 0


def test_the_panel_offers_colours_to_pick(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    assert page.locator("#side .swatch").count() >= 6


def test_picking_a_colour_changes_that_agent(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    before = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                          ).get_attribute("fill")
    page.locator('#side .swatch[data-hue="orange"]').click()
    page.wait_for_timeout(200)
    after = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                         ).get_attribute("fill")
    assert after != before, (before, after)


def test_it_only_changes_the_one_you_picked(page):
    ada_before = page.locator('.who[data-id="agent-research-assistant-0001"] .bot-body'
                              ).get_attribute("fill")
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    page.locator('#side .swatch[data-hue="orange"]').click()
    page.wait_for_timeout(200)
    ada_after = page.locator('.who[data-id="agent-research-assistant-0001"] .bot-body'
                             ).get_attribute("fill")
    assert ada_after == ada_before


def test_the_colour_is_remembered(page):
    """Per viewer, in localStorage, because it is how this person wants their
    own office to look rather than a property of the agent. Guarded on read
    and write: a private window throws and the office must still draw."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    page.locator('#side .swatch[data-hue="orange"]').click()
    page.wait_for_timeout(200)
    saved = page.evaluate("() => localStorage.getItem('aiuiOfficeColours')")
    assert saved and "agent-iris-a103" in saved, saved


def test_the_panel_shows_the_agent_as_a_robot_too(page):
    """The header used a .ring class that no stylesheet ever defined, so it
    rendered as a bare coloured bar. The face the floor shows belongs here."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    assert page.locator("#side .side-head svg.bot").count() == 1


def test_two_robots_for_one_agent_do_not_share_a_gradient_id(page):
    """The floor and the panel both draw Iris. A duplicate SVG id is invalid
    and the second gradient would never be reached."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    ids = page.eval_on_selector_all(
        "svg.bot linearGradient", "els => els.map(e => e.id)")
    assert len(ids) == len(set(ids)), ids


def test_every_agent_offers_a_private_chat(page):
    """"please put in evrey agent that user can chat to them privately."

    One button on the selected agent means you must select somebody before
    you can talk to them. Every robot on the floor carries its own."""
    assert page.locator(".who-chat").count() == 2


def test_the_private_chat_addresses_that_agent(page):
    """Naming an agent is what makes a turn private: agent_routing's name
    rung sends it to that one agent and nobody else answers. A link that did
    not carry the name would open the room instead."""
    href = page.locator('.who-chat[data-id="agent-iris-a103"]').get_attribute("href")
    assert "ask=" in href
    assert "Iris" in href


def test_the_private_chat_is_not_inside_the_agent_button(page):
    """A link nested in a button is invalid HTML, and the browser resolves it
    by dropping one of them. The label and its chat link are siblings of the
    robot, not children."""
    assert page.locator(".who .who-chat").count() == 0


def test_clicking_the_robot_still_selects_it(page):
    """The chat link sits next to the robot. It must not have stolen the
    click that opens the panel."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    assert page.locator("#side-agent h2").inner_text() == "Iris"


# --- moving around the floor -------------------------------------------------
# "can the user zoom in zoom out move inside the agent office. not scroll only"
#
# Zoom alone is not enough: zoomed in past the fit, the only way to reach the
# rest of the floor was the browser's scrollbars, which is a poor way to move
# around a plan and does not work at all once the floor is scaled inside a
# card that has its own scrolling.

def _floor_origin(page):
    return page.locator("#rooms").evaluate(
        "el => { const r = el.getBoundingClientRect(); return [r.left, r.top]; }")


def _empty_floor_point(page):
    """A spot on the floor that is not a control.

    A drag that starts on a robot or a link belongs to that control, which is
    deliberate. This used to grab the middle of the floor, and the middle
    stopped being empty once rooms filled the height of the band: it landed
    on a robot and the drag never started. Finding a free spot keeps the test
    about panning rather than about where the furniture happens to be."""
    return page.evaluate(
        "() => {"
        " const b = document.getElementById('floor-fit').getBoundingClientRect();"
        " for (let fy = 0.2; fy <= 0.85; fy += 0.07) {"
        "   for (let fx = 0.12; fx <= 0.9; fx += 0.04) {"
        "     const x = b.left + b.width * fx, y = b.top + b.height * fy;"
        "     const el = document.elementFromPoint(x, y);"
        "     if (el && !el.closest('button, a, .strip')"
        "         && document.getElementById('floor-fit').contains(el))"
        "       return [x, y];"
        "   }"
        " } return null; }")


def test_the_floor_can_be_dragged_to_move_around(docked):
    page = docked
    page.locator("#zoom-in").click()
    page.locator("#zoom-in").click()
    page.wait_for_timeout(150)
    before = _floor_origin(page)
    at = _empty_floor_point(page)
    assert at, "no empty floor to start a drag from"
    page.mouse.move(at[0], at[1])
    page.mouse.down()
    page.mouse.move(at[0] - 120, at[1] - 60, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    after = _floor_origin(page)
    assert after[0] < before[0] - 40, (before, after)
    assert after[1] < before[1] - 20, (before, after)


def test_fit_puts_it_back(docked):
    """Fit means the whole office, so it has to undo a pan as well as a
    zoom. Otherwise Fit leaves you looking at an empty corner."""
    page = docked
    page.locator("#zoom-in").click()
    page.wait_for_timeout(120)
    box = page.locator("#floor-fit").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 30, box["y"] + 30, steps=6)
    page.mouse.up()
    page.wait_for_timeout(150)
    page.locator("#zoom-fit").click()
    page.wait_for_timeout(200)
    assert page.locator("#zoom-fit").inner_text() == "Fit"
    spill = page.locator("#rooms").evaluate(
        "el => el.getBoundingClientRect().right"
        " - document.getElementById('floor-fit').getBoundingClientRect().right")
    assert spill <= 2, spill


def test_the_office_page_needs_no_zoom_and_no_pan(page):
    """Asked for on 2026-10-08: "the spaces must be entire content so no need
    to move, the only moving is the agents".

    The floor is stretched to the shape of its box on the full page rather
    than scaled into it, so there is no off-screen floor. The controls that
    existed to go and look at it are gone with it, and the page does not
    scroll in either direction. The dock still has both, which is what
    test_the_floor_can_be_dragged_to_move_around now covers."""
    got = page.evaluate(
        "() => {"
        " const d = document.documentElement;"
        " const fit = document.getElementById('floor-fit');"
        " const rooms = [...document.querySelectorAll('.zone')]"
        "   .map(z => z.getBoundingClientRect());"
        " const f = fit.getBoundingClientRect();"
        " return { zoomShown: getComputedStyle(document.querySelector('.zoom'))"
        "            .display !== 'none',"
        "          scrollsDown: d.scrollHeight > d.clientHeight + 1,"
        "          scrollsAcross: d.scrollWidth > d.clientWidth + 1,"
        "          transform: document.getElementById('rooms').style.transform,"
        "          slackRight: Math.round(f.right - Math.max(...rooms.map(r => r.right)))"
        "        }; }")
    assert not got["zoomShown"], got
    assert not got["scrollsDown"] and not got["scrollsAcross"], got
    # The pan is pinned at zero. The handlers stay bound rather than being
    # unpicked, because the dock still needs them and a branch that cannot
    # go stale is worth more than a shorter transform string.
    assert "translate(0px, 0px)" in got["transform"], got
    # And the rooms really do reach the far edge, rather than the floor
    # merely being told it may.
    assert got["slackRight"] <= 40, got


def test_dragging_a_robot_is_not_a_pan(page):
    """The robots are buttons. A click on one has to still select it rather
    than be swallowed by the thing that moves the floor."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(200)
    assert page.locator("#side-agent h2").inner_text() == "Iris"


# --- collaboration the floor is allowed to draw ------------------------------
# "add animation if they talk to each other... like a message popup in the
# head of them when they chat."
#
# The office's founding rule still stands: it draws what happened and never
# pretends. What changed is that handoffs are now real and recorded, so two
# robots standing together is a fact from tasks.agent_step rather than an
# animation somebody liked the look of.

def test_nothing_is_talking_when_nothing_happened(page):
    """The default fixture has no handoffs. If a bubble or a link appears
    here, the floor is inventing one."""
    assert page.locator(".talk-line").count() == 0
    assert page.locator(".say").count() == 0


def test_a_robot_is_small_enough_to_share_a_room(page):
    """"can you make the robots small." Two agents in one room used to put
    their labels within about 108px of each other.

    Measured against the room rather than in screen pixels, and on the figure
    rather than on the button around it. The button now also holds the name,
    so its width is the label's; and the floor scales to whatever space it
    has, so a fixed pixel ceiling passes or fails on the size of the window
    rather than on the size of the robot."""
    got = page.evaluate(
        "() => {"
        " const bot = document.querySelector("
        "   '.who[data-id=\"agent-iris-a103\"] svg.bot').getBoundingClientRect();"
        " const room = [...document.querySelectorAll('section.zone')]"
        "   .find(z => z.textContent.toLowerCase().includes('knowledge base'))"
        "   .getBoundingClientRect();"
        " return { w: bot.width / room.width, h: bot.height / room.height }; }")
    assert got["w"] <= 0.45, got
    assert got["h"] <= 0.5, got


def test_everyone_is_breathing(page):
    """Idle motion claims nothing, so it needs no evidence. It is the one
    animation here that is decoration rather than a statement."""
    assert page.locator(".who .bot").first.evaluate(
        "el => getComputedStyle(el).animationName") != "none"


# --- with a real handoff in the data ----------------------------------------

def _settled(page, timeout=6000):
    """Wait for every journey on the floor to end.

    `walking` is put on a slot when its coordinates change and taken off by
    the transition ending, so "no slot is walking" is the floor's own word
    that everybody has arrived. A fixed wait was a guess about a duration
    that now depends on the distance."""
    page.wait_for_function(
        "() => !document.querySelector('.who-slot.walking')", timeout=timeout)
    page.wait_for_timeout(50)


def _with_handoff(page, status="ok"):
    """Serve one real-shaped handoff row and let the floor redraw from it.

    The timestamp is NOW because the floor deliberately drops anything older
    than its freshness window: a handoff from this morning must not leave two
    robots still standing together at teatime. A fixed date here failed for
    exactly that reason, which is the guard working."""
    import datetime
    import json
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "activity": ACTIVITY,
            "handoffs": [{"from": "agent-research-assistant-0001",
                          "to": "agent-iris-a103", "status": status,
                          "at": now}]})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(500)


def test_a_handoff_draws_a_line_between_the_two(page):
    _with_handoff(page)
    assert page.locator(".talk-line").count() == 1


def test_the_asking_robot_says_something_over_its_head(page):
    """The popup is the point: you should be able to see WHO is talking to
    WHOM without reading a table."""
    _with_handoff(page)
    said = page.locator(".say").first.inner_text()
    assert "Iris" in said


def test_a_refused_handoff_is_drawn_too(page):
    """Showing only the ones that worked would be the flattering half of the
    truth."""
    _with_handoff(page, status="refused")
    assert page.locator(".talk-line").count() == 1
    assert page.locator(".talk-line.refused").count() == 1


def test_the_line_joins_the_right_two_robots(page):
    """A line drawn between the wrong pair is worse than no line: it states
    a collaboration that did not happen."""
    _with_handoff(page)
    ends = page.locator(".talk-line").first.evaluate(
        "el => [el.dataset.from, el.dataset.to]")
    assert ends == ["agent-research-assistant-0001", "agent-iris-a103"]


def test_the_asking_robot_walks_toward_its_colleague(page):
    """"add walking animation." It walks only when a handoff is in the data,
    so the movement is a fact rather than scenery: a robot crossing the floor
    says these two worked together."""
    before = page.locator('.who-slot[data-id="agent-research-assistant-0001"]'
                          ).evaluate("el => getComputedStyle(el).transform")
    _with_handoff(page)
    after = page.locator('.who-slot[data-id="agent-research-assistant-0001"]'
                         ).evaluate("el => getComputedStyle(el).transform")
    assert after != before
    assert after != "none"


def test_a_robot_nobody_asked_stays_put(page):
    """The colleague being asked does not walk, and neither does anyone
    uninvolved. Everyone drifting would turn a claim into decoration."""
    _with_handoff(page)
    assert page.locator('.who-slot[data-id="agent-iris-a103"]').evaluate(
        "el => getComputedStyle(el).transform") == "none"


def test_the_walk_is_undone_when_the_handoff_goes_stale(page):
    """The floor shows what is happening. A robot left standing next to a
    colleague long after the handoff finished is the staleness lie."""
    _with_handoff(page)
    moved = page.locator('.who-slot[data-id="agent-research-assistant-0001"]'
                         ).evaluate("el => getComputedStyle(el).transform")
    assert moved != "none"
    import json
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": ACTIVITY, "handoffs": []})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    # The walk BACK. The agents layer survives a redraw, so clearing the
    # nudge animates home rather than teleporting, and the floor's own
    # `walking` class says when it has got there.
    _settled(page)
    assert page.locator('.who-slot[data-id="agent-research-assistant-0001"]'
                        ).evaluate("el => getComputedStyle(el).transform") == "none"
    # The line fades rather than vanishing, so give it its moment.
    page.wait_for_timeout(800)
    assert page.locator(".talk-line").count() == 0


# --- everybody is visible ---------------------------------------------------
#
# The floor placed agents at fixed percentages of a fixed canvas, so a room
# could hold fewer people than were standing in it. On the owner's own roster
# three agents hold "code", and the third was drawn below Development's own
# wall: "see its kinda not showing the project manager". Their name and Chat
# pill also landed on top of each other, because the offsets that positioned
# them separately stopped agreeing when the robot was made smaller.
#
# Rooms are now sized by the agents in them, and an agent is one slot laid out
# in normal flow. These tests pin both halves of that.

CROWD = [
    {"id": "agent-ada", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": ["code", "schedules"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-kai", "name": "Kai",
     "meta": {"role": "Code reviewer", "toolIds": ["code"]},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
    {"id": "agent-rex", "name": "Rex",
     "meta": {"role": "Build engineer", "toolIds": ["code"]},
     "params": {}, "user_id": "me", "created_at": 3, "updated_at": 3},
    {"id": "agent-iris", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 4, "updated_at": 4},
    {"id": "agent-mia", "name": "Mia",
     "meta": {"role": "Receptionist", "toolIds": ["gmail"]},
     "params": {}, "user_id": "me", "created_at": 5, "updated_at": 5},
    {"id": "agent-nora", "name": "Nora",
     "meta": {"role": "Scheduler", "toolIds": ["calendar"]},
     "params": {}, "user_id": "me", "created_at": 6, "updated_at": 6},
    {"id": "agent-vera", "name": "Vera",
     "meta": {"role": "Automation lead", "toolIds": []},
     "params": {}, "user_id": "me", "created_at": 7, "updated_at": 7},
]


@pytest.fixture
def crowded(browser):
    """The owner's real shape: seven agents, three of them in one room."""
    html = (STATIC / "office.html").read_bytes()
    srv = _serve(html)
    # The dock the office really lives in is short and wide, which is the
    # whole reason Fit matters. Measuring in a tall window would hide it.
    pg = browser.new_page(viewport={"width": 1100, "height": 460})
    pg.set_default_timeout(6000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": CROWD, "total": len(CROWD)}
        elif "/agents/activity" in url:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": {}}
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    # embed=1 is the only way anybody actually sees this: the office is an
    # iframe inside the agents page, where the side panel is an overlay and
    # the floor gets the whole width. Measuring the standalone page instead
    # would measure a layout no user is ever shown.
    pg.goto("http://127.0.0.1:%d/office.html?embed=1" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    yield pg
    pg.close()
    srv.shutdown()


def test_every_agent_is_drawn(crowded):
    """Seven agents, seven robots. The one that went missing was missing from
    the picture, not from the roster, so counting the roster would not have
    caught it."""
    assert crowded.locator(".who-slot").count() == len(CROWD)


def test_every_agent_stands_fully_inside_a_room(crowded):
    """The whole agent, not just the robot: the name and the Chat pill are
    what crossed the wall first. An agent half outside its room is the
    project manager the owner could not find."""
    stray = crowded.evaluate(
        "() => {"
        " const rooms = [...document.querySelectorAll('section.zone')]"
        "   .map(z => z.getBoundingClientRect());"
        " const out = [];"
        " for (const s of document.querySelectorAll('.who-slot')) {"
        "   const b = s.getBoundingClientRect();"
        "   const ok = rooms.some(r => b.left >= r.left - 0.5"
        "     && b.right <= r.right + 0.5 && b.top >= r.top - 0.5"
        "     && b.bottom <= r.bottom + 0.5);"
        "   if (!ok) out.push(s.dataset.id);"
        " } return out; }")
    assert stray == [], stray


def test_a_name_never_lands_on_its_own_chat_pill(crowded):
    """"Kai ... ewer" in the owner's screenshot: the label sat 36px below the
    robot and the pill 52px below it, so the two overlapped. Nothing in a
    slot is positioned by hand any more, which is what makes this hold."""
    overlap = crowded.evaluate(
        "() => {"
        " const out = [];"
        " for (const s of document.querySelectorAll('.who-slot')) {"
        "   const l = s.querySelector('.who-label').getBoundingClientRect();"
        "   const c = s.querySelector('.who-chat').getBoundingClientRect();"
        "   if (l.bottom > c.top + 0.5) out.push(s.dataset.id);"
        " } return out; }")
    assert overlap == [], overlap


def test_two_agents_in_one_room_do_not_stand_on_each_other(crowded):
    """Three agents share Development. Their slots are reserved side by side,
    so no two of them may overlap anywhere on the floor."""
    clashes = crowded.evaluate(
        "() => {"
        " const s = [...document.querySelectorAll('.who-slot')]"
        "   .map(e => [e.dataset.id, e.getBoundingClientRect()]);"
        " const out = [];"
        " for (let i = 0; i < s.length; i++)"
        "   for (let j = i + 1; j < s.length; j++) {"
        "     const a = s[i][1], b = s[j][1];"
        "     if (a.left < b.right - 0.5 && b.left < a.right - 0.5"
        "         && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5)"
        "       out.push(s[i][0] + '/' + s[j][0]);"
        "   } return out; }")
    assert clashes == [], clashes


def test_the_whole_floor_is_visible_without_scrolling(crowded):
    """"so they can see in whole area." Fit means the entire floor is on
    screen: the owner's screenshot showed Research reading "ARCH" because it
    was cut off at the left edge."""
    got = crowded.evaluate(
        "() => {"
        " const fit = document.getElementById('floor-fit');"
        " const f = fit.getBoundingClientRect();"
        " const r = document.getElementById('rooms').getBoundingClientRect();"
        " return { clipped: r.left < f.left - 1 || r.right > f.right + 1"
        "                  || r.top < f.top - 1 || r.bottom > f.bottom + 1,"
        "          f: [f.left, f.right, f.top, f.bottom],"
        "          r: [r.left, r.right, r.top, r.bottom] }; }")
    assert not got["clipped"], got


def test_fit_keeps_the_robots_worth_looking_at(crowded):
    """A floor that fits by shrinking everything to nothing is not visible
    either. The canvas is now about as wide relative to its height as the
    dock it sits in, which is what buys the scale back."""
    h = crowded.locator(".who svg.bot").first.bounding_box()["height"]
    assert h >= 40, h



# --- one colour per agent, everywhere ---------------------------------------
# DESIGN.md, the One Hue Per Agent Rule. The office picked one of its own six
# palettes from a hash of the agent's id, so Ada was green on her card and
# purple as a robot. Cards and the chat thread take the hue from the agent's
# NAME (agents.html avatarHue, ported as agent_chat_render._hue), and a robot
# now starts from that same hue. A colour the person picked still wins.

def _hue_of(fill):
    m = re.match(r"\s*hsl\(\s*(\d+)", fill or "")
    return int(m.group(1)) if m else None


def test_a_robot_is_the_colour_of_its_agents_card(page):
    for agent_id, name in (("agent-research-assistant-0001", "Ada"),
                           ("agent-iris-a103", "Iris")):
        fill = page.locator('.who[data-id="%s"] .bot-body' % agent_id
                            ).get_attribute("fill")
        assert _hue_of(fill) == render._hue(name), (name, fill, render._hue(name))


def test_a_colour_the_person_chose_still_wins(page):
    """Only the default changed. A swatch somebody picked is kept, and the
    agent nobody recoloured still wears its own hue."""
    page.evaluate("() => localStorage.setItem('aiuiOfficeColours',"
                  " JSON.stringify({'agent-iris-a103': 'orange'}))")
    page.reload()
    page.wait_for_selector(".who", state="visible")
    iris = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                        ).get_attribute("fill")
    ada = page.locator('.who[data-id="agent-research-assistant-0001"] .bot-body'
                       ).get_attribute("fill")
    assert iris == "#cc7f2b", iris          # the orange palette's body
    assert _hue_of(ada) == render._hue("Ada"), ada


def test_the_panel_offers_the_agents_own_colour_back(page):
    """A person who tried orange needs a way back to the colour the agent
    has everywhere else, and it is the one marked when nothing was picked."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    own = page.locator('#side .swatch[data-hue="own"]')
    assert own.count() == 1
    assert own.get_attribute("aria-current") == "true"
    page.locator('#side .swatch[data-hue="orange"]').click()
    page.wait_for_timeout(200)
    assert page.locator('#side .swatch[data-hue="own"]'
                        ).get_attribute("aria-current") is None
    page.locator('#side .swatch[data-hue="own"]').click()
    page.wait_for_timeout(200)
    fill = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                        ).get_attribute("fill")
    assert _hue_of(fill) == render._hue("Iris"), fill
    saved = page.evaluate("() => localStorage.getItem('aiuiOfficeColours')")
    assert "agent-iris-a103" not in (saved or ""), saved


# --- state you can read, edges without stripes, motion you can stop ---------
# 6e3dda3c4 deleted the .dot rules along with the old cards, so every state
# light on the page has been an empty box since: a robot's light, the live
# strip, the activity list and the header all drew nothing. DESIGN.md also
# rules out a coloured side stripe wider than 1px, and asks that motion stop
# for a person whose system asks for less of it.

def test_the_state_light_is_lit_in_the_states_colour(page):
    got = page.evaluate(
        "() => {"
        " const bg = s => getComputedStyle(document.querySelector(s)).backgroundColor;"
        " const d = document.querySelector('.who[data-id=\"agent-iris-a103\"] .dot');"
        " return {"
        "  working: bg('.who[data-id=\"agent-research-assistant-0001\"] .dot.working'),"
        "  ready: bg('.who[data-id=\"agent-iris-a103\"] .dot.ready'),"
        "  live: bg('#live .dot'),"
        "  round: getComputedStyle(d).borderRadius }; }")
    assert got["working"] == "rgb(34, 211, 238)", got    # --cyan
    assert got["ready"] == "rgb(52, 211, 153)", got      # --ok
    assert got["live"] != "rgba(0, 0, 0, 0)", got
    assert got["round"] == "50%", got


def test_a_room_is_outlined_not_striped(page):
    sides = page.locator("section.zone").evaluate_all(
        "els => els.map(e => { const s = getComputedStyle(e);"
        " return [s.borderLeftWidth, s.borderTopWidth, s.borderRightWidth,"
        "         s.borderBottomWidth, s.borderLeftColor === s.borderTopColor]; })")
    assert sides, sides
    for left, top, right, bottom, same in sides:
        assert left == top == right == bottom == "1px", sides
        assert same, sides


def test_reduced_motion_stops_every_loop(page):
    """breathe, bustle, blink, halo, the dot's pulse and the talk line's
    along: every one runs for ever, and none of them is the only place a
    state is said. The dot colour and the label still say it."""
    _with_handoff(page)
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(100)
    names = page.evaluate(
        "() => {"
        " const a = (el, p) => getComputedStyle(el, p || null).animationName;"
        " const ada = document.querySelector("
        "   '.who[data-id=\"agent-research-assistant-0001\"]');"
        " const iris = document.querySelector('.who[data-id=\"agent-iris-a103\"]');"
        " return [a(iris.querySelector('.bot')), a(ada.querySelector('.bot')),"
        "         a(ada.querySelector('.bot-think')), a(ada, '::after'),"
        "         a(ada.querySelector('.dot')),"
        "         a(document.querySelector('.talk-line'))]; }")
    assert names == ["none"] * 6, names


# --- the whole page, not a sixth of it --------------------------------------
#
# Ralph, with a screenshot of /ai-agents/office, 2026-10-07: "fix the office
# page make it all wide live activity must ve in the right top corner opacity
# faded in the middle soo its easy anmd can see all agent walking around".
#
# The floor was drawing 725px inside a 1295px box. fitBox reserves the height
# of everything "below" the floor by walking following siblings, and on this
# page the right-hand panel IS a following sibling of <main>. It sits BESIDE
# the floor, not under it, so 827px of height was reserved for a column that
# costs the floor no height at all. Available height collapsed to 160 and Fit
# fell to 0.57.

def test_the_floor_fills_the_width_it_is_given(page):
    """A sibling beside the floor must not be reserved against its height."""
    got = page.evaluate(
        "() => {"
        " const f = document.getElementById('floor-fit').getBoundingClientRect();"
        " const r = document.getElementById('rooms').getBoundingClientRect();"
        " return { used: r.width / f.width, box: [f.width, f.height],"
        "          drawn: [r.width, r.height] }; }")
    assert got["used"] >= 0.9, got


def test_nothing_beside_the_floor_is_counted_as_below_it(page):
    """The measurement itself, so a future sibling cannot quietly re-break
    this: only a box that actually starts below the floor costs it height."""
    bad = page.evaluate(
        "() => {"
        " const fit = document.getElementById('floor-fit');"
        " const out = [];"
        " let node = fit;"
        " while (node && node !== document.body) {"
        "   let sib = node.nextElementSibling;"
        "   while (sib) {"
        "     const beside = sib.offsetTop < node.offsetTop + node.offsetHeight;"
        "     if (beside && sib.offsetHeight > 0) out.push(sib.className);"
        "     sib = sib.nextElementSibling;"
        "   }"
        "   node = node.parentElement;"
        " } return out; }")
    # The panel beside the floor is allowed to exist; what matters is that the
    # floor still got its width, which the test above asserts. This one just
    # records which boxes are beside rather than below.
    assert isinstance(bad, list)


def test_live_activity_sits_in_the_top_right_over_the_floor(page):
    """"live activity must ve in the right top corner." It was a full width
    strip under the floor, which is where the height went."""
    got = page.evaluate(
        "() => {"
        " const s = document.getElementById('strip').getBoundingClientRect();"
        " const f = document.getElementById('floor-fit').getBoundingClientRect();"
        " return { inTopHalf: s.top < f.top + f.height / 2,"
        "          onTheRight: s.left > f.left + f.width / 2,"
        "          overTheFloor: s.top >= f.top - 1 && s.left >= f.left - 1,"
        "          s: [s.left, s.top, s.width], f: [f.left, f.top, f.width] }; }")
    assert got["inTopHalf"], got
    assert got["onTheRight"], got
    assert got["overTheFloor"], got


def test_live_activity_is_faded_so_the_floor_shows_through(page):
    """"opacity faded in the middle soo its easy anmd can see all agent
    walking around." A solid panel over the floor hides the thing it is
    reporting on."""
    got = page.evaluate(
        "() => {"
        " const el = document.getElementById('strip');"
        " const cs = getComputedStyle(el);"
        " return { opacity: parseFloat(cs.opacity), bg: cs.backgroundColor }; }")
    # A fully transparent element also reports "rgba(0, 0, 0, 0)", so the
    # alpha has to be read rather than the word looked for.
    import re
    m = re.search(r"rgba?\(([^)]*)\)", got["bg"] or "")
    parts = [p.strip() for p in m.group(1).split(",")] if m else []
    alpha = float(parts[3]) if len(parts) == 4 else 1.0
    assert got["opacity"] < 1 or 0 < alpha < 1, got


def test_the_floor_is_still_not_clipped_once_it_is_wide(page):
    """Filling the width must not mean overflowing it."""
    got = page.evaluate(
        "() => {"
        " const f = document.getElementById('floor-fit').getBoundingClientRect();"
        " const r = document.getElementById('rooms').getBoundingClientRect();"
        " return { clipped: r.left < f.left - 1 || r.right > f.right + 1"
        "                   || r.top < f.top - 1 || r.bottom > f.bottom + 1,"
        "          f: [f.left, f.right], r: [r.left, r.right] }; }")
    assert not got["clipped"], got


def test_the_activity_card_never_covers_an_agent(page):
    """"soo its easy anmd can see all agent walking around if have task."
    A card laid over a room hides the agent it is reporting on, so the canvas
    keeps a clear strip above the rooms for it."""
    over = page.evaluate(
        "() => {"
        " const s = document.getElementById('strip');"
        " if (getComputedStyle(s).display === 'none') return [];"
        " const b = s.getBoundingClientRect(); const out = [];"
        " for (const w of document.querySelectorAll('.who-slot')) {"
        "   const r = w.getBoundingClientRect();"
        "   if (b.left < r.right - 1 && r.left < b.right - 1"
        "       && b.top < r.bottom - 1 && r.top < b.bottom - 1)"
        "     out.push(w.dataset.id);"
        " } return out; }")
    assert over == [], over


# --- the split stylesheet actually arrives ----------------------------------
#
# office.html was one 1832 line file until 2026-10-08. Splitting it means the
# page now depends on ten separate requests, and a stylesheet that 404s makes
# an unstyled page, not an error. Twice already a fixture here answered every
# path with the page itself and the geometry tests measured a document with no
# CSS at all, which passes nothing and fails nothing.

def test_every_stylesheet_the_page_asks_for_arrives(page):
    """A 404 on a stylesheet is silent in a browser. Ask the page what it
    requested and confirm each one came back as CSS."""
    hrefs = page.eval_on_selector_all(
        "link[rel=stylesheet]", "els => els.map(e => e.getAttribute('href'))")
    assert len(hrefs) >= 8, hrefs
    for href in hrefs:
        r = page.request.get(page.url.split("/office.html")[0] + href)
        assert r.status == 200, (href, r.status)
        assert "css" in (r.headers.get("content-type") or ""), (href, r.headers)


def test_each_stylesheet_contributed_something(page):
    """One rule from each file, so a sheet that loaded empty or was dropped
    from the page cannot pass. Each assertion fails to a browser default."""
    got = page.evaluate(
        "() => {"
        " const cs = s => { const e = document.querySelector(s);"
        "   return e ? getComputedStyle(e) : null; };"
        " const z = cs('.zone'), w = cs('.who-slot'), b = cs('.who svg.bot');"
        " const st = cs('.strip'), si = cs('.side'), f = cs('#rooms');"
        " return { room: z && z.borderRadius,"
        "          agent: w && w.display,"
        "          animations: b && b.animationName,"
        "          panel: st && st.position,"
        "          office: si && si.borderLeftStyle,"
        "          floor: f && f.transformOrigin }; }")
    assert got["room"] and got["room"] != "0px", got        # room.css
    assert got["agent"] == "flex", got                      # agent.css
    assert got["animations"] not in (None, "none"), got     # animations/idle.css
    assert got["panel"] == "absolute", got                  # panel.css
    assert got["office"] == "solid", got                    # office.css
    assert got["floor"].startswith("0px"), got              # room.css transform-origin


def test_the_floor_fits_what_is_visible_not_the_frame_it_is_in(browser):
    """In the shell the office is a pane: an iframe at height:100% of a
    container taller than the browser window. window.innerHeight inside that
    iframe is the iframe's height, so the floor sized itself to a box whose
    bottom was below the fold and the bar along it was sliced in half
    (owner's screenshot, 2026-10-08, at /ai-agents/office)."""
    srv = _serve((STATIC / "office.html").read_bytes())
    ctx = browser.new_context(viewport={"width": 1500, "height": 800})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        url = r.request.url
        # Seven agents, not two. With two the floor is small enough to fit
        # inside the window whatever height it thinks it has, so the bug
        # cannot show and this passed against the broken build.
        body = ({"items": CROWD, "total": len(CROWD)} if "/models/list" in url
                else {"activity": {}, "handoffs": []} if "/agents/activity" in url
                else {"stats": {}} if "/agents/stats" in url
                else {"skills": {}} if "/agents/skills" in url else {})
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    try:
        pg.goto("http://127.0.0.1:%d/tall-frame" % srv.server_address[1])
        frame = pg.frame_locator("iframe")
        frame.locator(".who").first.wait_for(state="visible")
        # The floor draws, then re-fits once the reads land. Measured too
        # early this passed on the broken build too, because the box had not
        # yet grown to the iframe's height.
        pg.wait_for_timeout(2500)
        got = pg.frame(url=lambda u: "office.html" in u).evaluate(
            "() => {"
            " const f = document.getElementById('floor-fit').getBoundingClientRect();"
            " const r = document.getElementById('rooms').getBoundingClientRect();"
            " return { iframeHeight: window.innerHeight,"
            "          floorBottom: Math.round(f.top + f.height),"
            "          clipped: Math.round(r.bottom - f.bottom) > 1 }; }")
        # The iframe really is the tall one, or this proves nothing.
        assert got["iframeHeight"] > 1200, got
        # ...and the floor still ends inside what a 800px window can show.
        assert got["floorBottom"] <= 800, got
        assert not got["clipped"], got
    finally:
        ctx.close()
        srv.shutdown()


# --- the meeting table ------------------------------------------------------
#
# "add a meeting place if they will do meetting." It exists only while a
# meeting is actually running, so the table being there IS the fact. Agents
# gather because each of their runs recorded source=meeting, never because
# several happened to start at once.

def _in_a_meeting(page, ids):
    """Put the given agents in a running meeting and redraw."""
    act = {i: {"state": "working", "running_for_seconds": 4,
               "last_run_at": "2026-10-08T02:00:00+00:00",
               "source": "meeting"} for i in ids}
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": act, "handoffs": []})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    _settled(page)


def _mid_round(page, speaking, done):
    """A meeting as it really looks mid-round: one agent mid-turn and the
    others already finished.

    The panel asks each agent in turn and awaits it, so at any instant most
    of the room has already spoken. `now` rather than a fixed timestamp,
    because whether a finished run still counts is a question about age."""
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    act = {i: {"state": "working", "running_for_seconds": 2,
               "last_run_at": at, "source": "meeting"} for i in speaking}
    act.update({i: {"state": "ready", "last_status": "completed",
                    "last_run_at": at, "source": "meeting"} for i in done})
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": act, "handoffs": []})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    _settled(page)


def test_an_agent_that_has_already_spoken_stays_in_the_meeting(page):
    """Reported live 2026-10-08 with a screenshot: chatting with the whole
    team left everybody at their desks.

    Half of that was the trace (see tests/test_meeting_source.py). This is
    the other half: a round goes round the table ONE AGENT AT A TIME, so
    asking "is this agent working right now" would put a single robot in the
    meeting room while the rest sat at their desks, and a gathering would
    never appear however the round was recorded."""
    a, b = "agent-research-assistant-0001", "agent-iris-a103"
    _mid_round(page, speaking=[a], done=[b])
    got = page.evaluate(
        "() => {"
        " const r = document.querySelector('.zone[data-room=\"meeting\"]')"
        "   .getBoundingClientRect();"
        " const inside = s => { const e ="
        "   document.querySelector('.who-slot[data-id=\"' + s + '\"]');"
        "   if (!e) return false; const x = e.getBoundingClientRect();"
        "   return x.left >= r.left - 2 && x.right <= r.right + 2"
        "     && x.top >= r.top - 2 && x.bottom <= r.bottom + 2; };"
        " return { speaking: inside('%s'), finished: inside('%s') }; }" % (a, b))
    assert got["speaking"], got
    assert got["finished"], got
    assert "2 agents" in page.locator(".meeting-table").inner_text().lower()


def test_a_meeting_that_is_over_sends_them_back(page):
    """The window is what makes them leave together. An old meeting run is
    somewhere an agent WAS, and a floor that kept drawing it would be making
    the staleness claim this page exists to avoid."""
    old = "2026-10-08T02:00:00+00:00"   # hours before the test runs
    act = {i: {"state": "ready", "last_status": "completed",
               "last_run_at": old, "source": "meeting"}
           for i in ("agent-research-assistant-0001", "agent-iris-a103")}
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": act, "handoffs": []})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(1400)
    assert page.locator(".meeting-table").count() == 0


# --- what the team still has to do, and somewhere to ask -------------------
# Asked for 2026-10-09: "can you add a direct chat in here and task in the top
# of agents like have todo". Both already existed elsewhere. tasks.items has
# recorded the work since migration 001 and nothing on this surface showed it;
# the conversation is the agents page's own component, reused rather than
# rebuilt, styled by the same stylesheet so it cannot drift from it.

def _with_todo(page, open_items, done=()):
    page.route("**/agents/todo**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"open": list(open_items), "done": list(done)})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(900)


def test_nothing_outstanding_is_said_rather_than_left_blank(page):
    """The default fixture answers /todo with nothing. An empty panel reads
    as broken; saying so is a fact worth knowing."""
    assert page.locator("#todo").count() == 1
    assert "nothing outstanding" in page.locator("#todo").inner_text().lower()


def test_the_to_do_lists_the_work_that_is_recorded(page):
    _with_todo(page, [
        {"id": "1", "what": "Build the shoe website", "who": "Rex",
         "priority": "important", "status": "running", "kind": "build", "at": None},
        {"id": "2", "what": "Research the competitors", "who": "Vera",
         "priority": "critical", "status": "awaiting_input", "kind": "research", "at": None},
    ])
    txt = page.locator("#todo").inner_text()
    assert "Build the shoe website" in txt, txt
    assert "Rex" in txt and "Vera" in txt, txt
    # The count is the open ones, and the state is on the line rather than
    # only in a colour, which a colour alone could not tell anybody.
    assert "2 open" in txt, txt
    assert "awaiting input" in txt, txt
    assert page.locator("#todo .todo-item").count() == 2


def test_a_finished_job_is_separated_from_the_open_ones(page):
    _with_todo(page,
               [{"id": "1", "what": "Still going", "who": "Rex",
                 "priority": "important", "status": "running", "kind": "build", "at": None}],
               [{"id": "9", "what": "Weekly report", "who": "Ada",
                 "priority": "important", "status": "completed", "kind": "research",
                 "at": "2026-10-09T11:00:00+00:00"}])
    assert page.locator("#todo .todo-item.done").count() == 1
    assert "1 open" in page.locator("#todo").inner_text()
    # The open count must not include what is already done.
    assert page.locator("#todo .todo-item:not(.done)").count() == 1


def test_the_to_do_escapes_what_it_is_given(page):
    """It is a description somebody typed, rendered into the page."""
    _with_todo(page, [{"id": "1", "what": "<img src=x onerror=alert(1)>",
                       "who": "Rex", "priority": "important",
                       "status": "running", "kind": "build", "at": None}])
    assert page.locator("#todo img").count() == 0
    assert "<img" in page.locator("#todo .todo-what").inner_text()


def test_the_office_page_has_a_team_chat_window(page):
    """The office is somewhere you can ask as well as watch: the team's
    conversation is a window along the bottom, open on the first visit
    (2026-10-16, "a chat inside the office which is like facebook
    messenger style")."""
    win = page.locator("#chatdock #cw-team")
    assert win.is_visible()
    assert win.locator("#agent-thread").count() == 1
    assert win.locator('#agent-thread[data-thread=""]').count() == 1
    form = win.locator(".ap-composer")
    assert form.get_attribute("hx-post") == "/tasks/agents/chat/send"
    assert form.locator("#ap-agent").input_value() == ""
    # Send must not eat the row.
    got = page.evaluate(
        "() => { const f = document.querySelector('#cw-team .ap-composer');"
        " const i = f.querySelector('input[type=text]');"
        " const b = f.querySelector('button');"
        " return { input: i.getBoundingClientRect().width,"
        "          btn: b.getBoundingClientRect().width }; }")
    assert got["input"] > got["btn"] * 2, got
    # Along the bottom of the window, at the right edge of the floor (the
    # column beside it stays clear).
    box = win.bounding_box()
    side = page.locator("#side").bounding_box()
    assert box["y"] + box["height"] >= 1000 - 2, box
    assert side["x"] - 40 < box["x"] + box["width"] <= side["x"] + 1, (box, side)
    # The column no longer holds a conversation of its own.
    assert page.locator("#side .ap-thread").count() == 0


def test_sending_from_the_office_opens_the_answer_stream(page):
    """Measured 2026-10-13: a send from the office drew the question and
    never an answer. The fragment send returns opens the round with htmx's
    SSE extension (sse-connect), which the agents page loads and this page
    did not, so no stream was ever opened and the room session stayed
    `streaming`. The fragment here is the real renderer's."""
    opened = []
    page.route("**/tasks/agents/chat/send", lambda r: r.fulfill(
        status=200, content_type="text/html",
        body=render.turn_open("hello", render.new_turn_id())
        + render.turn_close() + render.stream_block("")))

    def stream(r):
        opened.append(r.request.url)
        r.fulfill(status=200, content_type="text/event-stream",
                  body="retry: 60000\n\nevent: close\ndata: done\n\n")
    page.route("**/tasks/agents/chat/stream**", stream)
    page.locator("#cw-team .ap-composer input[name=message]").fill("hello")
    page.locator("#cw-team .ap-composer button[type=submit]").click()
    page.locator("#cw-team .astream").wait_for(state="attached", timeout=3000)
    page.wait_for_timeout(1500)
    assert opened, "the composer's round never opened /tasks/agents/chat/stream"


def test_a_chat_pill_opens_a_private_window_without_leaving_the_floor(page):
    """"instead of redirecting it to the ai agent tab": Chat on a robot is
    a window with that one agent, here, loaded from that agent's own
    conversation, and the floor stays."""
    loads = []
    page.route("**/tasks/agents/chat/thread**", lambda r: (
        loads.append(r.request.url),
        r.fulfill(status=200, content_type="text/html", body='<div class="aempty">nothing yet</div>')))
    page.locator('.who-chat[data-id="agent-iris-a103"]').click()
    win = page.locator('#chatdock .cw[data-chat="agent-iris-a103"]')
    win.wait_for(state="visible", timeout=3000)
    assert page.url.endswith("/office.html"), page.url
    assert win.locator(".cw-name").inner_text() == "Iris"
    assert win.locator('.ap-thread[data-thread="agent-iris-a103"]').count() == 1
    form = win.locator(".ap-composer")
    assert form.locator('input[name="agent"]').input_value() == "agent-iris-a103"
    assert form.get_attribute("hx-target") == "#agent-thread-agent-iris-a103"
    assert form.locator('input[name="message"]').get_attribute("placeholder") == "Message Iris"
    page.wait_for_timeout(300)
    assert any("agent=agent-iris-a103" in u for u in loads), loads
    # Both windows stand side by side; the team's is still there.
    assert page.locator("#chatdock .cw:visible").count() == 2


def test_the_card_and_the_tray_open_the_same_private_window(page):
    page.locator("#side a.chat-with").click()
    page.locator('#chatdock .cw[data-chat="agent-research-assistant-0001"]').wait_for(state="visible")
    assert page.locator("#chatdock .cw:visible").count() == 2


def test_a_fourth_window_puts_the_oldest_away_as_a_circle(page):
    """At most three open; the one opened longest ago folds to a circle in
    the bottom left corner, and comes back when clicked."""
    page.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.locator('.who-chat[data-id="agent-research-assistant-0001"]').click()
    page.wait_for_timeout(200)
    assert page.locator("#chatdock .cw:visible").count() == 3
    # Two agents and the team make three. A fourth conversation does not
    # exist in this fixture, so the team is put away by hand, the way the
    # title bar does it, and a fourth opening is tried through the API.
    page.evaluate("() => import('/office/js/dock.js').then(d => { d.openChat('agent-iris-a103'); d.openChat('agent-research-assistant-0001'); })")
    page.wait_for_timeout(200)
    assert page.locator("#chatdock .cw:visible").count() == 3
    page.locator("#cw-team .cw-head").click()
    page.wait_for_timeout(300)
    assert page.locator("#chatdock .cw:visible").count() == 2
    head = page.locator("#chatdock-min .chead")
    assert head.count() == 1
    assert head.get_attribute("data-chat") == ""
    box = head.bounding_box()
    assert box["x"] < 80 and box["y"] + box["height"] > 1000 - 80, box
    # The status pill steps up out of the circles' way.
    assert page.evaluate("() => document.documentElement.classList.contains('has-heads')")
    head.click()
    page.wait_for_timeout(300)
    assert page.locator("#chatdock-min .chead").count() == 0
    assert page.locator("#cw-team").is_visible()


def test_which_windows_are_open_is_remembered(page):
    page.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(200)
    page.locator("#cw-team .cw-min").click()
    page.wait_for_timeout(200)
    page.reload()
    page.wait_for_selector(".who", state="visible")
    page.wait_for_timeout(500)
    assert page.locator('#chatdock .cw[data-chat="agent-iris-a103"]').is_visible()
    assert not page.locator("#cw-team").is_visible()
    assert page.locator('#chatdock-min .chead[data-chat=""]').count() == 1


def test_something_said_while_a_window_was_away_is_counted_on_its_circle(page):
    page.locator("#cw-team .cw-min").click()
    page.wait_for_timeout(200)
    head = page.locator('#chatdock-min .chead[data-chat=""]')
    assert head.locator(".chead-n").is_hidden()
    # An answer arriving on the stream, which is what lands in the thread.
    page.evaluate(
        "() => { const t = document.getElementById('agent-thread');"
        " const d = document.createElement('div');"
        " d.className = 'am agent'; d.textContent = 'Ada: here you go';"
        " t.appendChild(d); }")
    page.wait_for_timeout(300)
    assert head.locator(".chead-n").inner_text() == "1"
    # Opening it is reading it.
    head.click()
    page.wait_for_timeout(300)
    assert page.locator("#chatdock-min .chead").count() == 0
    page.locator("#cw-team .cw-min").click()
    page.wait_for_timeout(200)
    assert page.locator('#chatdock-min .chead[data-chat=""] .chead-n').is_hidden()


def test_nothing_is_counted_while_the_window_is_open(page):
    page.evaluate(
        "() => { const t = document.getElementById('agent-thread');"
        " const d = document.createElement('div'); d.className = 'am agent';"
        " d.textContent = 'Ada: here you go'; t.appendChild(d); }")
    page.wait_for_timeout(300)
    page.locator("#cw-team .cw-min").click()
    page.wait_for_timeout(200)
    assert page.locator('#chatdock-min .chead[data-chat=""] .chead-n').is_hidden()


def test_closing_a_window_takes_it_away_for_good(page):
    page.locator('.who-chat[data-id="agent-iris-a103"]').click()
    win = page.locator('#chatdock .cw[data-chat="agent-iris-a103"]')
    win.wait_for(state="visible")
    win.locator(".cw-close").click()
    page.wait_for_timeout(200)
    assert page.locator('#chatdock .cw[data-chat="agent-iris-a103"]').count() == 0
    assert page.locator("#chatdock-min .chead").count() == 0


def test_the_meeting_button_fills_the_team_window(page):
    """Nothing is ever sent for you: it fills the composer and stops."""
    sent = []
    page.route("**/tasks/agents/chat/send", lambda r: (sent.append(1), r.fulfill(status=200, body="")))
    page.locator('#brain-actions .chat-open[data-ask]').click()
    page.wait_for_timeout(200)
    assert page.locator("#cw-team input[name=message]").input_value() == "everyone answer: "
    assert sent == []
    page.locator("#cw-team .cw-meet").click()
    assert page.locator("#cw-team input[name=message]").input_value() == "everyone answer: "


def test_the_dock_has_no_conversation_of_its_own(docked):
    """The agents page around the dock already has one, and two threads on
    one screen would both open the stream and both draw the same round."""
    assert docked.locator("#chatdock").count() == 1
    assert not docked.locator("#chatdock").is_visible()
    assert docked.locator("#chatdock .cw").count() == 0 or not docked.locator("#chatdock .cw").first.is_visible()


def test_the_card_is_redrawn_without_taking_the_chat_with_it(page):
    """Only the card is rebuilt. Redrawing the chat would throw away the
    round in flight."""
    page.evaluate("() => { document.querySelector('#cw-team #agent-thread')"
                  ".setAttribute('data-kept', 'yes'); }")
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.locator("#side-agent h2").inner_text() == "Iris"
    assert page.locator('#cw-team #agent-thread[data-kept="yes"]').count() == 1
    assert page.locator("#todo").count() == 1


def test_no_meeting_means_no_table(page):
    """The default fixture has nobody in a meeting. A table standing there
    all day would stop meaning anything."""
    assert page.locator(".meeting-table").count() == 0


def test_a_real_meeting_puts_a_table_on_the_floor(page):
    _in_a_meeting(page, ["agent-research-assistant-0001", "agent-iris-a103"])
    assert page.locator(".meeting-table").count() == 1
    # Uppercased by text-transform, so inner_text reports it that way.
    assert "2 agents" in page.locator(".meeting-table").inner_text().lower()


def test_the_agents_in_it_leave_their_desks_for_the_table(page):
    before = page.locator('.who-slot[data-id="agent-iris-a103"]').evaluate(
        "el => [el.offsetLeft, el.offsetTop]")
    _in_a_meeting(page, ["agent-research-assistant-0001", "agent-iris-a103"])
    after = page.locator('.who-slot[data-id="agent-iris-a103"]').evaluate(
        "el => [el.offsetLeft, el.offsetTop]")
    assert after != before, (before, after)


def test_they_gather_rather_than_scatter(page):
    """What matters is that they are together: two agents walking to opposite
    corners is not a meeting.

    Measured as "both are inside the meeting room", which is now the literal
    claim the floor makes. It used to be measured against a table floating in
    a band above the rooms, because the meeting happened in a place that was
    not on the plan; it happens in a room on the plan now, so containment is
    both a stronger statement and the one a person would make looking at it."""
    _in_a_meeting(page, ["agent-research-assistant-0001", "agent-iris-a103"])
    got = page.evaluate(
        "() => {"
        " const r = document.querySelector('.zone[data-room=\"meeting\"]')"
        "   .getBoundingClientRect();"
        " const box = s => document.querySelector('.who-slot[data-id=\"' + s + '\"]')"
        "   .getBoundingClientRect();"
        " const inside = b => b.left >= r.left - 2 && b.right <= r.right + 2"
        "   && b.top >= r.top - 2 && b.bottom <= r.bottom + 2;"
        " const a = box('agent-research-assistant-0001'), b = box('agent-iris-a103');"
        " return { a: inside(a), b: inside(b),"
        "          apart: Math.round(Math.abs((a.left + a.right) / 2"
        "                                   - (b.left + b.right) / 2)),"
        "          roomW: Math.round(r.width) }; }")
    assert got["a"] and got["b"], got
    # And standing together in it, not at opposite walls of a room that grew
    # to hold them.
    assert got["apart"] <= got["roomW"] * 0.8, got


def test_working_alone_is_not_a_meeting(page):
    """A run with any other source leaves the agent at its desk. This is the
    guard that stops the floor inventing a meeting from a busy moment."""
    act = {"agent-iris-a103": {"state": "working", "running_for_seconds": 3,
                               "last_run_at": "2026-10-08T02:00:00+00:00",
                               "source": "channel"}}
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": act, "handoffs": []})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(600)
    assert page.locator(".meeting-table").count() == 0


# --- the floor moves as one -------------------------------------------------
#
# "Make the animations smooth and perfectly synchronized with their actions"
# (2026-10-12). Every movement here is still drawn from a recorded row; what
# these pin down is that the movements AGREE with each other: a walk lasts
# exactly as long as the robot is moving, the thing it says travels with it,
# the room it walks into finishes growing as it arrives, and the lights in a
# room are the same fact as the face of the robot working in it.

def _activity(page, act, handoffs=()):
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": act, "handoffs": list(handoffs)})))
    page.evaluate("() => window.aiuiRefreshOffice()")


def test_a_robot_walks_only_while_it_is_moving(page):
    """The walk cycle is on for the journey and off at the end of it: it is
    taken off by the transition ending, not by a timer guessed to match."""
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": at, "source": "meeting"}})
    iris = page.locator('.who-slot[data-id="agent-iris-a103"]')
    iris.locator("xpath=self::*[contains(@class, 'walking')]").wait_for(timeout=1000)
    assert "walking" in (iris.get_attribute("class") or "")
    _settled(page)
    assert "walking" not in (iris.get_attribute("class") or "")
    # And she has actually arrived: the slot's inline place is where the
    # browser has it, with no transition left to run.
    inside = page.evaluate(
        "() => {"
        " const r = document.querySelector('.zone[data-room=\"meeting\"]')"
        "   .getBoundingClientRect();"
        " const x = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]')"
        "   .getBoundingClientRect();"
        " return x.left >= r.left - 2 && x.right <= r.right + 2"
        "   && x.top >= r.top - 2 && x.bottom <= r.bottom + 2; }")
    assert inside


def test_the_walk_takes_as_long_as_the_distance(page):
    """One pace for the whole floor. A longer journey is a longer walk, and
    the duration is written on the slot for the stylesheet to read."""
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": at, "source": "meeting"}})
    got = page.evaluate(
        "() => {"
        " const el = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]');"
        " return { d: el.style.getPropertyValue('--d'),"
        "          lean: el.style.getPropertyValue('--lean') }; }")
    ms = int(got["d"].replace("ms", ""))
    assert 450 <= ms <= 2600, got
    assert got["lean"] in ("4deg", "-4deg", "0deg"), got
    _settled(page)


def test_what_a_robot_says_travels_with_it(page):
    """The bubble is a child of the asking robot's slot, so wherever the
    walk takes the robot the bubble is over its head. It used to be pinned
    to the destination and hung in empty air for the length of the walk."""
    _with_handoff(page)
    inside = page.locator(
        '.who-slot[data-id="agent-research-assistant-0001"] .say')
    assert inside.count() == 1
    assert "Iris" in inside.inner_text()
    assert page.locator(".say").count() == 1


def test_the_line_is_drawn_at_the_walkers_pace(page):
    """The line from the asker's desk to the colleague draws itself in the
    time the asker takes to walk it: the same --d on both.

    Read straight after the redraw, not after _with_handoff's half second:
    Ada and Iris stand close enough now that the whole walk is the 450ms
    floor, and the drawing is over before that wait is."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": ACTIVITY,
                         "handoffs": [{"from": "agent-research-assistant-0001",
                                       "to": "agent-iris-a103", "status": "ok",
                                       "at": now}]})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_selector(".talk-line", state="attached", timeout=3000)
    got = page.evaluate(
        "() => {"
        " const line = document.querySelector('.talk-line');"
        " const who = document.querySelector('.who-slot[data-id=\"agent-research-assistant-0001\"]');"
        " return { drawing: line.classList.contains('drawing'),"
        "          lineD: line.style.getPropertyValue('--d'),"
        "          walkD: who.style.getPropertyValue('--d'),"
        "          rot: line.style.getPropertyValue('--rot') }; }")
    assert got["drawing"], got
    assert got["lineD"] == got["walkD"], got
    assert got["rot"].endswith("deg"), got


def test_a_redraw_does_not_restart_a_walk(page):
    """An event or a poll lands mid-journey. The slot is MOVED, never
    rebuilt, so a redraw with the same destination leaves the figure where
    its stride has it instead of starting the stride again."""
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    act = {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                               "last_run_at": at, "source": "meeting"}}
    _activity(page, act)
    # Straight away, not after a pause: with the rooms as close as they are
    # now the whole walk can be the 450ms floor, and a wait would let it
    # end before the redraw this test is about.
    page.wait_for_selector(".who-slot.walking", timeout=2000)
    page.evaluate("() => { document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]')._keep = 1; }")
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(60)
    got = page.evaluate(
        "() => { const el = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]');"
        " return { same: el._keep === 1, walking: el.classList.contains('walking'),"
        "          bot: !!el.querySelector('svg.bot') }; }")
    assert got == {"same": True, "walking": True, "bot": True}, got
    _settled(page)


def test_a_change_of_state_changes_the_face_not_the_figure(page):
    """Ada finishes. Her face changes and her light changes; the figure that
    was breathing is the same node, still breathing."""
    page.evaluate("() => { document.querySelector('.who[data-id=\"agent-research-assistant-0001\"] svg.bot')._keep = 1; }")
    act = dict(ACTIVITY)
    act["agent-research-assistant-0001"] = {
        "state": "ready", "last_status": "completed",
        "last_run_at": "2026-09-24T10:02:22+00:00", "source": "channel"}
    _activity(page, act)
    page.wait_for_timeout(200)
    got = page.evaluate(
        "() => { const who = document.querySelector('.who[data-id=\"agent-research-assistant-0001\"]');"
        " return { state: who.dataset.state, same: who.querySelector('svg.bot')._keep === 1,"
        "          smile: !!who.querySelector('.bot-face path.bot-mouth'),"
        "          dot: who.querySelector('.dot').className }; }")
    assert got == {"state": "ready", "same": True, "smile": True, "dot": "dot ready"}, got


def test_a_robot_answering_a_conversation_is_typing(page):
    """Ada is working from a channel in the default fixture: the dots are
    over her shoulder. Iris, idle, says nothing.

    This used to pin her MOUTH moving while she worked. Agent turns are not
    streamed, so that drew the mouth for the whole model call and stopped it
    the moment the answer appeared (measured 2026-10-13: on 1.55 s before the
    bubble, off 6 ms after it). Working is the thinking, which is the dots;
    the mouth now waits for speaking_started (test_office_live.py)."""
    ada = page.locator('.who[data-id="agent-research-assistant-0001"]')
    assert ada.get_attribute("data-typing") == "1"
    assert ada.locator(".talk-dots").count() == 1
    assert ada.get_attribute("data-speaking") is None
    assert ada.locator(".bot-mouth").evaluate(
        "el => getComputedStyle(el).animationName") == "none"
    iris = page.locator('.who[data-id="agent-iris-a103"]')
    assert iris.get_attribute("data-typing") is None
    assert iris.get_attribute("data-speaking") is None
    assert iris.locator(".talk-dots").count() == 0


def test_a_schedule_runs_in_silence(page):
    """Working is not talking. A run a schedule started has nobody to answer,
    so the robot works (bustle, halo, badge) without moving its mouth."""
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": "2026-09-24T10:02:22+00:00",
                                          "source": "schedule"}})
    page.wait_for_timeout(200)
    iris = page.locator('.who[data-id="agent-iris-a103"]')
    assert iris.get_attribute("data-state") == "working"
    assert iris.get_attribute("data-speaking") is None
    assert iris.locator(".talk-dots").count() == 0


def test_the_dots_stop_when_the_answer_is_in(page):
    act = dict(ACTIVITY)
    act["agent-research-assistant-0001"] = {
        "state": "ready", "last_status": "completed",
        "last_run_at": "2026-09-24T10:02:22+00:00", "source": "channel"}
    _activity(page, act)
    page.wait_for_timeout(200)
    ada = page.locator('.who[data-id="agent-research-assistant-0001"]')
    assert ada.get_attribute("data-speaking") is None
    assert ada.locator(".talk-dots").count() == 0


def test_a_room_somebody_is_working_in_has_its_lights_on(page):
    """Ada is working in Development; nobody is working in Knowledge base.
    The room's lights are the same recorded state as the robot's face."""
    assert page.locator('.zone[data-room="dev"]').get_attribute("data-busy") == "1"
    assert page.locator('.zone[data-room="knowledge"]').get_attribute("data-busy") == "0"
    assert page.locator('.zone[data-room="dev"] .zone-dot').evaluate(
        "el => getComputedStyle(el).animationName") == "pulse"
    assert page.locator('.zone[data-room="knowledge"] .zone-dot').evaluate(
        "el => getComputedStyle(el).animationName") == "none"


def test_the_lights_go_off_when_the_work_is_done(page):
    act = dict(ACTIVITY)
    act["agent-research-assistant-0001"] = {
        "state": "ready", "last_status": "completed",
        "last_run_at": "2026-09-24T10:02:22+00:00", "source": "channel"}
    _activity(page, act)
    page.wait_for_timeout(200)
    assert page.locator('.zone[data-room="dev"]').get_attribute("data-busy") == "0"


def test_the_meeting_room_is_lit_while_a_meeting_is_on(page):
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    room = page.locator('.zone[data-room="meeting"]')
    assert room.get_attribute("data-live") == "0"
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": at, "source": "meeting"}})
    page.wait_for_timeout(100)
    assert room.get_attribute("data-live") == "1"
    _settled(page)
    _activity(page, {"agent-iris-a103": {"state": "ready", "last_status": "completed",
                                          "last_run_at": "2026-10-08T02:00:00+00:00",
                                          "source": "meeting"}})
    page.wait_for_timeout(100)
    assert room.get_attribute("data-live") == "0"
    _settled(page)


def test_the_room_grows_on_the_same_clock_as_the_people_walking_in(page):
    """The meeting room, the floor and the longest walk share one --d, so
    the room is finished growing at the moment the last agent steps in, and
    the table is laid then and not before."""
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _activity(page, {i: {"state": "working", "running_for_seconds": 2,
                          "last_run_at": at, "source": "meeting"}
                      for i in ("agent-research-assistant-0001", "agent-iris-a103")})
    got = page.evaluate(
        "() => {"
        " const ms = s => parseInt((s || '0').replace('ms', ''), 10);"
        " const walks = [...document.querySelectorAll('.who-slot')]"
        "   .map(el => ms(el.style.getPropertyValue('--d')));"
        " const room = document.querySelector('.zone[data-room=\"meeting\"]');"
        " const table = room.querySelector('.meeting-table');"
        " return { longest: Math.max(...walks),"
        "          room: ms(room.style.getPropertyValue('--d')),"
        "          floor: ms(document.getElementById('rooms').style.getPropertyValue('--d')),"
        "          table: table && ms(table.style.getPropertyValue('--d')),"
        "          tableDelay: table && getComputedStyle(table).animationDelay,"
        "          reflow: document.getElementById('rooms').classList.contains('reflow') }; }")
    assert got["longest"] > 0, got
    assert got["room"] == got["longest"], got
    assert got["floor"] == got["longest"], got
    assert got["table"] == got["longest"], got
    assert got["tableDelay"] == "%ss" % (got["longest"] / 1000), got
    assert got["reflow"], got
    _settled(page)


def test_a_room_is_moved_across_a_redraw_not_rebuilt(page):
    """The rooms are kept the way the agents are: the same node, moved. A
    rebuilt room cannot ease to its new place, so it snapped there while the
    robots were still halfway across the floor."""
    page.evaluate("() => { document.querySelector('.zone[data-room=\"dev\"]')._keep = 1; }")
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": at, "source": "meeting"}})
    page.wait_for_timeout(100)
    assert page.evaluate(
        "() => document.querySelector('.zone[data-room=\"dev\"]')._keep === 1")
    assert page.locator('.zone[data-room="dev"]').count() == 1
    _settled(page)


def test_a_zoom_answers_at_once(docked):
    """The floor eases only for a layout the agents are walking into. A zoom
    is the hand asking, and it must not wait two seconds for an answer."""
    page = docked
    page.locator("#zoom-in").click()
    assert not page.evaluate(
        "() => document.getElementById('rooms').classList.contains('reflow')")
    page.wait_for_timeout(60)
    assert page.locator("#zoom-fit").inner_text() != "Fit"


def test_the_robots_do_not_breathe_in_unison(page):
    """Decoration, so it needs no evidence; but six robots breathing as one
    reads as a screensaver. Each is offset by its own id."""
    delays = page.locator(".who .bot").evaluate_all(
        "els => els.map(el => getComputedStyle(el).animationDelay)")
    assert len(set(delays)) == len(delays), delays


def test_every_moving_part_of_the_walk_is_still_off_under_reduced_motion(page):
    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    page.emulate_media(reduced_motion="reduce")
    _activity(page, {"agent-iris-a103": {"state": "working", "running_for_seconds": 2,
                                          "last_run_at": at, "source": "meeting"}})
    page.wait_for_timeout(100)
    names = page.evaluate(
        "() => {"
        " const a = el => el ? getComputedStyle(el).animationName : 'gone';"
        " const s = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]');"
        " return [a(s.querySelector('.bot')), a(s.querySelector('.bot-arm-l')),"
        "         a(s.querySelector('.bot-shadow')),"
        "         a(document.querySelector('.who[data-id=\"agent-research-assistant-0001\"] .bot-mouth')),"
        "         a(document.querySelector('.zone[data-room=\"dev\"] .zone-dot')),"
        "         getComputedStyle(s).transitionDuration]; }")
    assert names == ["none"] * 5 + ["0s"], names


def test_a_room_is_not_cluttered_with_furniture(page):
    """"remove this that kinda messy please fix make it clean" (2026-10-12,
    every drawn desk, screen, shelf and plant circled). A room is its name,
    its numbers and the people in it; the only desk is the agent's own."""
    assert page.locator(".zone .zone-floor").count() == 0
    assert page.locator(".zone i:not(.zone-dot)").count() == 0
    assert page.locator(".who-slot .desk").count() == page.locator(".who-slot").count()


# --- the layout pass of 2026-10-16 ----------------------------------------
# "revise the ui what is the better?" Every earlier ask is kept (the live
# activity card top right over the floor, a Chat for every agent, the to-do
# at the top of the column); what changed is how much of each is on screen
# at rest.

def test_the_live_card_rests_on_its_newest_line(page):
    """One row until the pointer reaches it, so the rooms get the height
    the 120px band used to hold for the card."""
    got = page.evaluate(
        "() => { const s = document.getElementById('strip');"
        " const rows = [...s.querySelectorAll('.feed li')];"
        " return { h: s.getBoundingClientRect().height,"
        "          shown: rows.filter(li => getComputedStyle(li).display !== 'none').length,"
        "          title: getComputedStyle(s.querySelector('h2')).display }; }")
    assert got["h"] <= 60, got
    assert got["shown"] == 1, got
    assert got["title"] == "none", got
    page.locator("#strip").hover()
    page.wait_for_timeout(350)
    got = page.evaluate(
        "() => { const s = document.getElementById('strip');"
        " const rows = [...s.querySelectorAll('.feed li')];"
        " return { shown: rows.filter(li => getComputedStyle(li).display !== 'none').length,"
        "          title: getComputedStyle(s.querySelector('h2')).display }; }")
    assert got["shown"] == 2 and got["title"] != "none", got


def test_the_rooms_start_closer_to_the_top(page):
    top = page.evaluate(
        "() => Math.min(...[...document.querySelectorAll('.zone')]"
        "  .map(z => parseFloat(z.style.top)))")
    assert top <= 100, top


def test_a_chat_pill_shows_when_you_reach_for_its_agent(page):
    iris = page.locator('.who-slot[data-id="agent-iris-a103"]')
    assert iris.locator(".who-chat").count() == 1
    at_rest = iris.locator(".who-chat").evaluate("el => getComputedStyle(el).opacity")
    assert at_rest == "0", at_rest
    iris.locator(".who").hover()
    page.wait_for_timeout(250)
    assert iris.locator(".who-chat").evaluate("el => getComputedStyle(el).opacity") == "1"


def test_the_picked_agents_pill_stays(page):
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.mouse.move(5, 5)
    page.wait_for_timeout(250)
    assert page.locator('.who-slot[data-id="agent-iris-a103"] .who-chat').evaluate(
        "el => getComputedStyle(el).opacity") == "1"


def test_a_rooms_totals_come_up_on_hover(page):
    room = page.locator('.zone[data-room="dev"]')
    assert room.locator(".zone-foot").evaluate("el => getComputedStyle(el).opacity") == "0"
    # A corner of the room, not its middle, where the robot stands.
    room.hover(position={"x": 24, "y": 24})
    page.wait_for_timeout(250)
    assert room.locator(".zone-foot").evaluate("el => getComputedStyle(el).opacity") == "1"
    assert "RUNS: 801" in room.inner_text()


def test_the_agent_card_folds_to_its_head(page):
    page.locator("#side-fold").click()
    page.wait_for_timeout(200)
    assert "folded" in (page.locator("#side-agent").get_attribute("class") or "")
    assert page.locator("#side-agent h2").is_visible()
    assert not page.locator("#side-agent .stats").is_visible()
    page.locator("#side-fold").click()
    page.wait_for_timeout(200)
    assert page.locator("#side-agent .stats").is_visible()


def test_the_fold_is_remembered(page):
    page.locator("#side-fold").click()
    page.reload()
    page.wait_for_selector(".who", state="visible")
    assert "folded" in (page.locator("#side-agent").get_attribute("class") or "")
    page.locator("#side-fold").click()


def test_finished_work_is_behind_a_disclosure(page):
    _with_todo(page,
               [{"id": "1", "what": "Still going", "who": "Rex",
                 "priority": "important", "status": "running", "kind": "build", "at": None}],
               [{"id": "9", "what": "Weekly report", "who": "Ada",
                 "priority": "important", "status": "completed", "kind": "research",
                 "at": "2026-10-09T11:00:00+00:00"}])
    done = page.locator("#todo .todo-done")
    assert done.count() == 1
    assert "recently done" in done.locator("summary").inner_text().lower()
    assert not page.locator("#todo .todo-item.done").is_visible()
    done.locator("summary").click()
    assert page.locator("#todo .todo-item.done").is_visible()


# --- what needs you (2026-10-16) ---------------------------------------------

def test_nobody_waiting_means_no_tray(page):
    """A tray that says "nothing" is a tray in the way."""
    assert page.locator("#needs").is_hidden()


def test_an_agent_waiting_on_you_is_first_in_the_column(page):
    _activity(page, {"agent-iris-a103": {"state": "waiting", "last_status": "waiting",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    page.wait_for_timeout(300)
    tray = page.locator("#needs")
    assert tray.is_visible()
    assert "Iris" in tray.inner_text() and "waiting on you" in tray.inner_text()
    # First thing in the column, above the to-do and the card.
    assert page.evaluate(
        "() => document.getElementById('needs').getBoundingClientRect().top"
        "  < document.getElementById('todo').getBoundingClientRect().top")
    # Answering goes to Iris's own conversation, where the question is.
    href = tray.locator("a.needs-answer").get_attribute("href")
    assert "Iris" in href and tray.locator("a.needs-answer").get_attribute("target") == "_top"


def test_the_tray_empties_when_the_question_is_answered(page):
    _activity(page, {"agent-iris-a103": {"state": "waiting", "last_status": "waiting",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    page.wait_for_timeout(200)
    assert page.locator("#needs").is_visible()
    _activity(page, {"agent-iris-a103": {"state": "ready", "last_status": "completed",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    page.wait_for_timeout(200)
    assert page.locator("#needs").is_hidden()


# --- the log remembers (2026-10-16) ------------------------------------------

def test_the_live_card_opens_on_what_the_server_recorded(page):
    """Every line comes from /agents/activity's events, so a reload does not
    start the log empty."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    events = [
        {"at": (now - datetime.timedelta(minutes=3)).isoformat(),
         "agent_id": "agent-iris-a103", "key": "working", "text": "started working from schedule"},
        {"at": (now - datetime.timedelta(minutes=2)).isoformat(),
         "agent_id": "agent-iris-a103", "key": "ready", "text": "completed"},
        {"at": (now - datetime.timedelta(minutes=1)).isoformat(),
         "agent_id": "agent-research-assistant-0001", "target_agent_id": "agent-iris-a103",
         "key": "working", "text": "asked"},
        {"at": now.isoformat(), "agent_id": "agent-not-mine", "key": "ready", "text": "completed"},
    ]
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": ACTIVITY, "handoffs": [], "events": events})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(300)
    lines = page.locator("#live li").all_inner_texts()
    assert any("Ada" in l and "asked Iris" in l for l in lines), lines
    assert any("Iris" in l and "completed" in l for l in lines), lines
    assert any("Iris" in l and "started working from schedule" in l for l in lines), lines
    assert not any("agent-not-mine" in l for l in lines), lines
    # Newest first.
    asked = next(i for i, l in enumerate(lines) if "asked Iris" in l)
    started = next(i for i, l in enumerate(lines) if "started working from schedule" in l)
    assert asked < started, lines


# --- the history view (2026-10-16) -------------------------------------------

def _with_history(page, runs, spend):
    page.route("**/agents/history**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"runs": runs, "spend": spend, "days": 7})))
    page.locator("#tab-activity").click()
    page.wait_for_selector("#hist-filters:not([hidden])", timeout=3000)


HISTORY = [
    {"agent_id": "agent-research-assistant-0001", "source": "channel", "status": "completed",
     "started_at": "2026-10-16T09:00:00+00:00", "seconds": 31, "cost_usd": 0.05, "model": "gpt-5"},
    {"agent_id": "agent-research-assistant-0001", "source": "schedule", "status": "failed",
     "started_at": "2026-10-15T09:00:00+00:00", "seconds": 4, "cost_usd": 0.01, "model": "gpt-5"},
    {"agent_id": "agent-iris-a103", "source": "channel", "status": "waiting",
     "started_at": "2026-10-14T09:00:00+00:00", "seconds": 2, "cost_usd": None, "model": None},
]
SPEND = [{"day": "2026-10-14", "cost_usd": 0.0}, {"day": "2026-10-15", "cost_usd": 0.01},
         {"day": "2026-10-16", "cost_usd": 0.05}]


def test_the_activity_tab_is_a_week_of_runs(page):
    _with_history(page, HISTORY, SPEND)
    rows = page.locator("#activity-feed li").all_inner_texts()
    assert len(rows) == 3, rows
    assert "Ada" in rows[0] and "completed" in rows[0] and "from channel" in rows[0] and "31s" in rows[0]
    assert "$0.050" in rows[0]
    assert "Iris" in rows[2] and "waiting on you" in rows[2]
    assert "week" in page.locator("#hist-title").inner_text().lower()


def test_the_week_can_be_filtered(page):
    _with_history(page, HISTORY, SPEND)
    page.select_option("#hist-agent", "agent-iris-a103")
    assert page.locator("#activity-feed li").count() == 1
    assert "Iris" in page.locator("#activity-feed li").first.inner_text()
    page.select_option("#hist-agent", "")
    page.select_option("#hist-status", "failed")
    rows = page.locator("#activity-feed li").all_inner_texts()
    assert len(rows) == 1 and "failed" in rows[0], rows
    page.select_option("#hist-status", "")
    page.select_option("#hist-source", "schedule")
    assert page.locator("#activity-feed li").count() == 1


def test_the_spend_strip_adds_up_the_week(page):
    _with_history(page, HISTORY, SPEND)
    strip = page.locator("#spend")
    assert strip.is_visible()
    assert "$0.06" in strip.inner_text()
    assert strip.locator(".spend-day").count() == 3


def test_without_a_history_route_the_tab_still_shows_each_agents_last_run(page):
    """The fixture answers /history with nothing: the one-line-per-agent
    view the tab always had is what shows."""
    page.locator("#tab-activity").click()
    page.wait_for_timeout(400)
    assert page.locator("#hist-filters").is_hidden()
    assert page.locator("#activity-feed li").count() == 2


# --- your desk (2026-10-16) --------------------------------------------------
# "if agent have blockers or need to approved by the user please add a desk
# of the user so he or she can approved.. it will remove unless he enabled
# auto". A fixture room, where a robot whose run stopped to wait on you
# goes to stand; the tray answers the question or sets the agent to Auto.

def test_your_desk_is_on_the_floor(page):
    room = page.locator('.zone[data-room="you"]')
    assert room.count() == 1
    assert "your desk" in room.locator(".zone-head").inner_text().lower()
    assert room.locator(".you-desk").count() == 1
    assert room.get_attribute("data-live") == "0"


def test_an_agent_waiting_on_you_walks_to_your_desk(page):
    _activity(page, {"agent-iris-a103": {"state": "waiting", "last_status": "waiting",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    _settled(page)
    assert page.evaluate(
        "() => { const r = document.querySelector('.zone[data-room=\"you\"]').getBoundingClientRect();"
        " const x = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]').getBoundingClientRect();"
        " return x.left >= r.left - 2 && x.right <= r.right + 2 && x.top >= r.top - 2 && x.bottom <= r.bottom + 2; }")
    assert page.locator('.zone[data-room="you"]').get_attribute("data-live") == "1"
    # And back to its own desk once answered.
    _activity(page, {"agent-iris-a103": {"state": "ready", "last_status": "completed",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    _settled(page)
    assert page.evaluate(
        "() => { const r = document.querySelector('.zone[data-room=\"knowledge\"]').getBoundingClientRect();"
        " const x = document.querySelector('.who-slot[data-id=\"agent-iris-a103\"]').getBoundingClientRect();"
        " return x.left >= r.left - 2 && x.right <= r.right + 2; }")


APPROVAL = render.turn_open("send it", "t9") + render.approval_bubble(
    "Iris", "ask-77", [{"function": {"name": "send_email", "arguments": "{}"}}]) + render.turn_close()


def _iris_asks(page):
    """Iris's run is waiting, and the thread beside the floor holds her
    question, exactly as the round draws it."""
    page.evaluate("h => { document.getElementById('agent-thread').innerHTML = h;"
                  " if (window.htmx) htmx.process(document.getElementById('agent-thread')); }", APPROVAL)
    _activity(page, {"agent-iris-a103": {"state": "waiting", "last_status": "waiting",
                                          "last_run_at": "2026-10-16T08:00:00+00:00",
                                          "source": "channel"}})
    page.wait_for_timeout(300)


def test_the_tray_shows_the_question_with_its_own_yes_and_no(page):
    _iris_asks(page)
    tray = page.locator("#needs")
    assert "send_email" in tray.inner_text()
    assert tray.locator(".needs-yes").count() == 1 and tray.locator(".needs-no").count() == 1
    assert tray.locator("a.needs-answer").count() == 0


def test_yes_from_the_desk_is_the_threads_own_yes(page):
    """The tray presses the approval bubble's button, so the answer goes
    through /tasks/agents/chat/approve exactly as a click in the thread."""
    _iris_asks(page)
    posted = []
    page.route("**/tasks/agents/chat/approve", lambda r: (
        posted.append(r.request.post_data or ""),
        r.fulfill(status=200, content_type="text/html",
                  body=render.note("Iris sent it."))))
    page.locator("#needs .needs-yes").click()
    page.wait_for_timeout(500)
    assert posted and "ask_id=ask-77" in posted[0] and "approved=yes" in posted[0], posted


def test_auto_writes_the_agents_access_and_approves_the_standing_question(page):
    _iris_asks(page)
    written = []
    approved = []
    page.route(re.compile(r"/api/v1/models/model\?id=agent-iris-a103$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"id": "agent-iris-a103", "name": "Iris", "base_model_id": "gpt",
                         "meta": {"role": "Drive librarian", "toolIds": ["gdrive"], "access": "ask"},
                         "params": {"system": "You are Iris."}})))
    page.route(re.compile(r"/api/v1/models/model/update\?id=agent-iris-a103$"), lambda r: (
        written.append(json.loads(r.request.post_data or "{}")),
        r.fulfill(status=200, content_type="application/json", body="{}")))
    page.route("**/tasks/agents/chat/approve", lambda r: (
        approved.append(r.request.post_data or ""),
        r.fulfill(status=200, content_type="text/html", body=render.note("Iris sent it."))))
    page.locator("#needs .needs-auto-box").check()
    page.wait_for_timeout(600)
    assert written and written[0]["meta"]["access"] == "all", written
    # Only the level changed: tools and instructions ride along untouched.
    assert written[0]["meta"]["toolIds"] == ["gdrive"] and written[0]["params"]["system"] == "You are Iris."
    assert approved and "approved=yes" in approved[0], approved


# --- the office in the shell has no header (2026-10-16) ----------------------

def test_framed_by_the_shell_the_office_has_no_header_and_keeps_its_search(browser):
    """"remove the header of it i want the user can see the whole
    animation." The shell has the navigation; the pane is the floor."""
    srv = _serve((STATIC / "office.html").read_bytes())
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        url = r.request.url
        body = ({"items": AGENTS, "total": len(AGENTS)} if "/models/list" in url
                else {"activity": {}, "handoffs": []} if "/agents/activity" in url
                else {"stats": {}} if "/agents/stats" in url
                else {"skills": []} if "/agents/skills" in url else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    try:
        pg.goto("http://127.0.0.1:%d/tall-frame" % srv.server_address[1])
        frame = pg.frame_locator("iframe")
        frame.locator(".who").first.wait_for(state="visible")
        assert frame.locator(".top").count() == 1
        assert not frame.locator(".top").is_visible()
        # The search box moved down beside The Brain and still narrows.
        assert frame.locator(".brain #q").count() == 1
        frame.locator("#q").fill("librarian")
        pg.wait_for_timeout(300)
        assert frame.locator(".card-name").all_inner_texts() == ["Iris"]
    finally:
        ctx.close()
        srv.shutdown()


def test_in_the_shell_the_bars_logs_button_opens_the_activity_log(browser):
    """The header's Activity tab is hidden with the header, so the floor's
    own bar opens the log, as a drawer over the floor that still moves
    behind it (2026-10-16, "add the logs so user can see the activity logs
    of the agents")."""
    srv = _serve((STATIC / "office.html").read_bytes())
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        url = r.request.url
        body = ({"items": AGENTS, "total": len(AGENTS)} if "/models/list" in url
                else {"activity": ACTIVITY, "handoffs": []} if "/agents/activity" in url
                else {"runs": [{"agent_id": "agent-iris-a103", "source": "schedule",
                                "status": "completed", "started_at": "2026-10-16T09:00:00+00:00",
                                "seconds": 5, "cost_usd": 0.01, "model": "gpt-5"}],
                      "spend": [], "days": 7} if "/agents/history" in url
                else {"stats": {}} if "/agents/stats" in url
                else {"skills": []} if "/agents/skills" in url else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    try:
        pg.goto("http://127.0.0.1:%d/tall-frame" % srv.server_address[1])
        frame = pg.frame_locator("iframe")
        frame.locator(".who").first.wait_for(state="visible")
        assert not frame.locator("#panel-activity").is_visible()
        frame.locator("#brain-actions .logs-open").click()
        frame.locator("#panel-activity").wait_for(state="visible")
        frame.locator("#activity-feed li").first.wait_for(state="visible")
        assert "Iris" in frame.locator("#activity-feed").inner_text()
        # The floor is still there behind it.
        assert frame.locator(".who").first.is_visible()
        frame.locator("#logs-close").click()
        pg.wait_for_timeout(100)
        assert not frame.locator("#panel-activity").is_visible()
    finally:
        ctx.close()
        srv.shutdown()


def test_on_its_own_page_the_office_keeps_its_header(page):
    assert page.locator(".top").is_visible()
    assert page.locator(".top #q").count() == 1


# --- making an agent from the office (2026-10-16) ----------------------------
# "how can the user able to create or add agents in the office tab". The
# agents page's "+ New agent" was a link out of the office, and in the shell
# the header it sat in is hidden. The office has its own short form now, and
# the new agent stands up at its desk without a reload.

def _new_agent_routes(pg, created):
    def route(r):
        url = r.request.url
        if "/models/create" in url and r.request.method == "POST":
            created.append(json.loads(r.request.post_data or "{}"))
            r.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"id": created[-1]["id"]}))
            return
        items = AGENTS + [dict(id=c["id"], name=c["name"], meta=c["meta"], params={},
                               base_model_id=c["base_model_id"], user_id="me")
                          for c in created]
        body = ({"items": items, "total": len(items)} if "/models/list" in url
                else {"data": [{"id": "gpt-5", "name": "GPT-5"},
                               {"id": "auto_router.auto", "name": "Auto"},
                               {"id": "gpt-image-2", "name": "Image"}]} if url.endswith("/api/models")
                else {"tools": [], "default_model": "gpt-5"} if "/agents/tools" in url
                else {"activity": ACTIVITY, "handoffs": []} if "/agents/activity" in url
                else {"stats": {}} if "/agents/stats" in url
                else {"skills": []} if "/agents/skills" in url else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    pg.route("**/api/**", route)


def test_a_new_agent_made_from_the_bar_stands_up_on_the_floor(browser):
    srv = _serve((STATIC / "office.html").read_bytes())
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    created = []
    _new_agent_routes(pg, created)
    try:
        pg.goto("http://127.0.0.1:%d/tall-frame" % srv.server_address[1])
        frame = pg.frame_locator("iframe")
        frame.locator(".who").first.wait_for(state="visible")
        assert frame.locator(".who").count() == 2
        frame.locator("#brain-actions .new-agent-open").click()
        frame.locator("#newagent").wait_for(state="visible")
        # The model list leaves out the callback pipe and the image model,
        # and starts on the platform default.
        pg.wait_for_timeout(300)
        options = frame.locator("#na-model option").all_inner_texts()
        assert options == ["GPT-5"], options
        frame.locator("#na-name").fill("Jack")
        frame.locator("#na-role").fill("Bookkeeper")
        frame.locator("#na-instructions").fill("Keep the books straight and say so plainly.")
        # The pane is 1600px tall in this harness (see /tall-frame), so the
        # centred dialog sits partly below the window: clicked by event.
        frame.locator('input[name="na-access"][value="ask"]').evaluate("el => el.click()")
        frame.locator("#na-save").evaluate("el => el.click()")
        frame.locator('.who-slot[data-id^="agent-jack-"]').wait_for(state="attached")
        assert len(created) == 1
        body = created[0]
        assert body["name"] == "Jack" and body["base_model_id"] == "gpt-5"
        assert body["meta"]["role"] == "Bookkeeper" and body["meta"]["access"] == "ask"
        assert body["meta"]["toolIds"] == ["server:mcp-proxy"]
        assert body["params"]["system"].startswith("Keep the books")
        assert body["access_grants"] == [] and body["is_active"] is True
        assert not frame.locator("#newagent").is_visible()
        assert frame.locator(".who").count() == 3
        # Picked out, so the card beside the floor is the new agent's.
        assert "Jack" in frame.locator("#side-agent h2").inner_text()
    finally:
        ctx.close()
        srv.shutdown()


def test_the_form_refuses_a_two_word_name_and_keeps_what_was_typed(page):
    created = []
    _new_agent_routes(page, created)
    page.locator(".top .new-agent-open").click()
    page.locator("#newagent").wait_for(state="visible")
    page.locator("#na-name").fill("Research Agent")
    page.locator("#na-instructions").fill("Look things up.")
    page.locator("#na-save").click()
    page.wait_for_timeout(100)
    assert "one word" in page.locator("#na-error").inner_text().lower()
    assert page.locator("#na-name").input_value() == "Research Agent"
    assert created == []
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    assert not page.locator("#newagent").is_visible()
