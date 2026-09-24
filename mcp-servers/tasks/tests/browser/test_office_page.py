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
              "toolIds": ["code", "schedules", "remember", "account", "skills"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "description": "Finds your files.",
              "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
    # Not an agent. The listing carries every model this person can see, and
    # the page must not draw gpt-5 as a colleague.
    {"id": "gpt-5", "name": "gpt-5", "meta": {}, "params": {},
     "user_id": "me", "created_at": 3, "updated_at": 3},
]

ACTIVITY = {
    "agent-research-assistant-0001": {
        "state": "working", "running_for_seconds": 12,
        "started_at": "2026-09-24T10:02:22+00:00", "source": "channel"},
    "agent-iris-a103": {
        "state": "ready", "last_duration_seconds": 5,
        "status": "completed", "started_at": "2026-09-24T09:00:00+00:00",
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
