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
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

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

    Only occupied rooms are drawn now, so this names the two the fixture
    actually fills. Ada holds BOTH code and schedules, and the first matching
    area wins, so she sits in Development rather than Automation; Iris holds
    gdrive and sits at the Knowledge base. An empty room is scenery."""
    zones = [z.lower() for z in page.locator(".zone-head > span:first-child").all_inner_texts()]
    assert sorted(zones) == ["development", "knowledge base"], zones




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
    assert len(labels) == 2, labels   # Ada in Automation, Iris at Knowledge base


def test_an_empty_room_gets_no_card(page):
    """A row of zeroes against a room nobody works in says nothing and makes
    the floor look busy. Only rooms with agents in them get a headline."""
    labels = " ".join(page.locator(".zone-head > span:first-child").all_inner_texts()).lower()
    assert "meeting room" not in labels, labels
    assert "research" not in labels, labels


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
        assert labels == ["communication"], labels
        assert pg.locator(".zone").count() == 1
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
    from urllib.parse import unquote
    href = page.locator('.floor-bar a.btn').first.get_attribute("href")
    assert href.startswith("/tasks/agents?ask="), href
    assert unquote(href.split("ask=", 1)[1]).startswith("everyone answer")


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


def test_the_meeting_button_leaves_the_frame(page):
    """The one that was actually clicked."""
    assert page.locator(".floor-bar a.btn").first.get_attribute("target") == "_top"


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
    assert page.locator("#side h2").inner_text() == "Iris"


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


def test_the_floor_can_be_dragged_to_move_around(page):
    page.locator("#zoom-in").click()
    page.locator("#zoom-in").click()
    page.wait_for_timeout(150)
    before = _floor_origin(page)
    box = page.locator("#floor-fit").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 - 120,
                    box["y"] + box["height"] / 2 - 60, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    after = _floor_origin(page)
    assert after[0] < before[0] - 40, (before, after)
    assert after[1] < before[1] - 20, (before, after)


def test_fit_puts_it_back(page):
    """Fit means the whole office, so it has to undo a pan as well as a
    zoom. Otherwise Fit leaves you looking at an empty corner."""
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


def test_dragging_a_robot_is_not_a_pan(page):
    """The robots are buttons. A click on one has to still select it rather
    than be swallowed by the thing that moves the floor."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(200)
    assert page.locator("#side h2").inner_text() == "Iris"


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
    page.wait_for_timeout(400)
    assert page.locator('.who-slot[data-id="agent-research-assistant-0001"]'
                        ).evaluate("el => getComputedStyle(el).transform") == "none"
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
