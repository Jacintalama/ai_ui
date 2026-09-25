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
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

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
            body = {"activity": ACTIVITY}
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

def test_the_floor_has_named_areas(page):
    """Case-insensitive on purpose: the labels are upper-cased by CSS, and
    inner_text reports what is rendered rather than what is written."""
    zones = [z.lower() for z in page.locator(".zone span").all_inner_texts()]
    assert "communication" in zones and "development" in zones, zones
    assert "knowledge base" in zones, zones


def test_an_agent_stands_where_its_tools_are(page):
    """Iris holds gdrive, so she belongs at the knowledge base and not in
    development. Position is a percentage of the floor, so the check is that
    she is inside that zone's box rather than at any exact pixel."""
    box = page.locator('.who[data-id="agent-iris-a103"]').evaluate(
        "el => ({ left: parseFloat(el.style.left), top: parseFloat(el.style.top) })")
    # Knowledge base occupies left 37%..65%, top 52%..94%.
    assert 37 <= box["left"] <= 65, box
    assert 52 <= box["top"] <= 94, box


def test_two_agents_in_one_area_do_not_stand_on_each_other(page):
    """Ada holds code and so does any other developer. Sharing a zone must
    spread them, or the second is invisible under the first."""
    spots = page.locator(".who").evaluate_all(
        "els => els.map(e => e.style.left + ':' + e.style.top)")
    assert len(set(spots)) == len(spots), spots


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


def test_no_two_agents_are_close_enough_to_cover_each_other(page):
    """Owner's screenshot 2026-09-25: Ada and Rex sat on top of each other and
    one name chip was hidden behind the other, so the floor showed six agents
    where there were seven.

    Distinct coordinates are not enough, because the isometric squash brings
    rows visually closer than their numbers suggest. This measures the drawn
    boxes rather than the percentages."""
    boxes = page.locator(".who").evaluate_all(
        "els => els.map(e => { const b = e.getBoundingClientRect();"
        " return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; })")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            dx = boxes[i]["x"] - boxes[j]["x"]
            dy = boxes[i]["y"] - boxes[j]["y"]
            assert (dx * dx + dy * dy) ** 0.5 > 60, (boxes[i], boxes[j])


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


def test_all_seven_of_the_owners_agents_stay_apart(browser):
    """The collision in the screenshot needed seven, not two: Kai and Rex both
    hold only `code` so they share Development, and Ada holds code too."""
    html = (STATIC / "office.html").read_bytes()
    srv = _serve(html)
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)

    def route(r):
        url = r.request.url
        if "/models/list" in url:
            body = {"items": SEVEN, "total": len(SEVEN)}
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": SKILLS}
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    pg.wait_for_timeout(300)
    try:
        assert pg.locator(".who").count() == 7
        boxes = pg.locator(".who").evaluate_all(
            "els => els.map(e => { const b = e.getBoundingClientRect();"
            " return { x: b.x + b.width / 2, y: b.y + b.height / 2,"
            "          n: e.getAttribute('data-id') }; })")
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                dx = boxes[i]["x"] - boxes[j]["x"]
                dy = boxes[i]["y"] - boxes[j]["y"]
                gap = (dx * dx + dy * dy) ** 0.5
                assert gap > 60, (boxes[i]["n"], boxes[j]["n"], round(gap))
    finally:
        pg.close()
        srv.shutdown()


# --- a headline per room ----------------------------------------------------
# From the reference the owner sent: a room is worth a number. Every figure is
# an aggregate of the agents standing in THAT room, so a room that sums
# somebody else's runs is the bug that looks perfectly fine.

def test_each_room_with_somebody_in_it_gets_a_card(page):
    labels = [t.lower() for t in page.locator(".card-room .rn").all_inner_texts()]
    assert any("knowledge base" in t for t in labels), labels
    assert len(labels) == 2, labels   # Ada in Automation, Iris at Knowledge base


def test_an_empty_room_gets_no_card(page):
    """A row of zeroes against a room nobody works in says nothing and makes
    the floor look busy. Only rooms with agents in them get a headline."""
    labels = " ".join(page.locator(".card-room .rn").all_inner_texts()).lower()
    assert "meeting room" not in labels, labels
    assert "research" not in labels, labels


def test_a_room_counts_only_its_own_agents_runs(page):
    """Ada is alone in Automation with 801 runs; Iris is alone at the
    knowledge base with 26. Neither card may carry the other's."""
    cards = page.locator(".card-room").all_inner_texts()
    joined = " ".join(cards)
    assert "801" in joined and "26" in joined, cards
    for text in cards:
        assert not ("801" in text and "26" in text), text


def test_the_room_card_weights_success_by_runs(page):
    """success_pct is a percentage of one agent's own runs. Averaging two
    agents' percentages would let an agent with three runs outvote one with
    eight hundred, so it is weighted back into runs first. Alone in a room,
    an agent's own rate must survive the arithmetic unchanged."""
    cards = page.locator(".card-room").all_inner_texts()
    ada = [c for c in cards if "801" in c][0]
    assert "40%" in ada, ada


# --- people, not tokens -----------------------------------------------------
# The reference the owner kept sending reads as an office because there are
# people sitting in it. Ours read as coloured discs on a board. The figure is
# drawn here rather than taken: that repository is PolyForm Noncommercial with
# terms forbidding its use to front another agent system, so its art is not
# ours to lift.

def test_every_agent_is_drawn_as_a_person(page):
    assert page.locator(".who .ring svg").count() == page.locator(".who").count()
    assert page.locator(".who .ring .seat-head").count() == page.locator(".who").count()


def test_the_figure_wears_the_agents_colour(page):
    """One figure per agent in its own colour, so the floor is readable at a
    glance rather than a row of identical silhouettes."""
    colours = page.locator(".who .who-inner").evaluate_all(
        "els => els.map(e => getComputedStyle(e).color)")
    assert len(set(colours)) == len(colours), colours


def test_the_initial_still_identifies_the_figure(page):
    """A name chip sits below, but at this size the initial on the chest is
    what makes one figure tellable from another mid-glance."""
    # textContent, not inner_text: an SVG <text> node has no rendered inner
    # text and Playwright hands back None for every one of them.
    inits = page.locator(".who .seat-init").evaluate_all(
        "els => els.map(e => e.textContent)")
    assert sorted(inits) == ["A", "I"], inits


def test_a_working_agent_still_pulses(page):
    """The halo moved from around a disc to around the chair. It has to
    survive the redraw, because it is the only thing on the floor that says
    something is happening right now."""
    assert page.locator('.who[data-state="working"]').count() == 1


# --- legible, which is the whole reason the floor went light ----------------
# "i want them same in the repo image please not the current i can't
# understand it". Dark navy rooms on a dark shell could not be read, so the
# office is lit and the furniture is dark, the way the reference does it.

def test_the_floor_is_light_enough_to_read(page):
    """A guard on the thing that was actually wrong. If somebody restyles
    this back to dark-on-dark, the office stops being readable again."""
    bg = page.locator(".stage-wrap").evaluate(
        "el => getComputedStyle(el).backgroundColor")
    nums = [int(n) for n in bg.replace("rgb(", "").replace(")", "").split(",")[:3]]
    assert sum(nums) / 3 > 180, bg


def test_the_room_name_reads_against_the_room(page):
    """The labels were unreadable once already. Dark text on a pale pill now,
    and this fails if either side of that flips."""
    got = page.locator(".zone span").first.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return { c: s.color, b: s.backgroundColor }; }")
    text = [int(n) for n in got["c"].replace("rgb(", "").replace(")", "").split(",")[:3]]
    assert sum(text) / 3 < 120, got


def test_the_brain_is_on_the_floor_and_goes_somewhere_real(page):
    """The reference puts the Brain in the middle. Ours is a real page every
    agent reads before answering, so it links there rather than decorating."""
    assert page.locator(".brain a").get_attribute("href") == "/tasks/graph"


def test_the_brain_claims_no_note_count(page):
    """The reference shows "37 NOTES". Nothing on this page counts notes, and
    a number nobody computed is the one thing this office must not draw."""
    said = page.locator(".brain").inner_text().lower()
    assert "notes" not in said, said


def test_the_rooms_do_not_touch(page):
    """Six rectangles sharing edges read as one grid. The reference separates
    departments into islands, and the gap is what makes them countable."""
    boxes = page.locator(".zone").evaluate_all(
        "els => els.map(e => ({ l: parseFloat(e.style.left), t: parseFloat(e.style.top),"
        " w: parseFloat(e.style.width), h: parseFloat(e.style.height) }))")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            apart = (a["l"] + a["w"] <= b["l"] or b["l"] + b["w"] <= a["l"]
                     or a["t"] + a["h"] <= b["t"] or b["t"] + b["h"] <= a["t"])
            assert apart, (a, b)
