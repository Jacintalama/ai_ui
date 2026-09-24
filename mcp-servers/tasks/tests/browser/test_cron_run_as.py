"""Picking which agent a schedule runs as.

This file used to say the default had to stay "the assistant schedules have
always used", so that somebody who never touched the field got exactly what
they got before. On 2026-09-24 that stopped being something to preserve: what
they got before was the App Builder trying to build an app out of the prompt,
which delivered an AutoFix 404 report to the owner's Discord twice a day for
months. A schedule naming nobody now fails every time it fires, so the form
refuses to create one.
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
    {"id": "agent-triage-0002", "name": "Triage", "base_model_id": "gpt-4o-mini",
     "meta": {"description": "sorts mail", "toolIds": ["gmail"]},
     "params": {"system": "sort mail"}, "user_id": "me",
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 1, "updated_at": 1},
    {"id": "agent-scout-0001", "name": "Scout", "base_model_id": "gpt-4o-mini",
     "meta": {"description": "researches", "toolIds": []},
     "params": {"system": "research"}, "user_id": "me",
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 2, "updated_at": 2},
]


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    html = (STATIC / "cron.html").read_bytes()

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

    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    sent = []

    def route(r):
        url = r.request.url
        if "/api/v1/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif r.request.method == "POST":
            sent.append(json.loads(r.request.post_data or "{}"))
            body = {"id": "new"}
        else:
            body = []
        r.fulfill(status=201 if r.request.method == "POST" else 200,
                  content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    pg.goto("http://127.0.0.1:%d/cron.html" % srv.server_address[1])
    pg.wait_for_selector("#run-as", state="attached")
    pg.wait_for_timeout(400)
    pg.sent = sent
    yield pg
    pg.close()
    srv.shutdown()


def _fill(page):
    page.fill("#name", "Morning digest")
    page.fill("#prompt", "Sort my unread mail.")


def test_the_field_starts_on_no_choice(page):
    """Nothing is pre-selected, so the agent a schedule runs as is always one
    somebody picked. Pre-selecting the first one would put a stranger's name
    on a job they never chose, and the list order is not meaningful."""
    assert page.input_value("#run-as") == ""


def test_it_lists_the_agents_you_can_see(page):
    labels = page.locator("#run-as option").all_inner_texts()
    assert any("Triage" in t for t in labels), labels
    assert any("Scout" in t for t in labels), labels


# test_leaving_it_alone_sends_no_agent stood here. It asserted that an
# untouched field posts with no agent_id, which the API read as "the assistant
# schedules have always used". That reading is what built an app out of a
# quote request. The case is now covered by
# test_the_form_will_not_post_a_schedule_with_no_agent: there is no such post.


def test_picking_an_agent_sends_its_id(page):
    _fill(page)
    page.select_option("#run-as", "agent-triage-0002")
    page.locator("#create-btn").click()
    page.wait_for_timeout(400)
    assert page.sent[-1]["agent_id"] == "agent-triage-0002"


# test_a_failure_to_list_agents_still_lets_you_create_a_schedule stood here,
# on the grounds that "the form works perfectly well without an agent". It no
# longer does. Inverted by
# test_a_failed_agent_list_says_so_instead_of_posting_a_dead_schedule.


# --- showing the agent on the card -----------------------------------------
# The read path silently dropped agent_id once already (Task 1's review
# caught it). Without the card showing the choice, a user has no way to tell
# whether picking an agent actually stuck.

CARD_ROWS = [
    {"id": "s1", "name": "Sort my mail", "prompt": "sort mail",
     "cron_expr": "0 9 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": None, "last_run_status": None,
     "agent_id": "agent-triage-0002"},
    {"id": "s2", "name": "Weekly digest", "prompt": "digest",
     "cron_expr": "0 9 * * 1", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": None, "last_run_status": None,
     "agent_id": None},
    {"id": "s3", "name": "Old job", "prompt": "old",
     "cron_expr": "0 9 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": None, "last_run_status": None,
     "agent_id": "agent-deleted-0009"},
]


@pytest.fixture
def cards_page(browser):
    html = (STATIC / "cron.html").read_bytes()
    schedules_body = json.dumps(CARD_ROWS).encode()
    models_body = json.dumps({"items": AGENTS, "total": len(AGENTS)}).encode()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            if "models/list" in self.path:
                data, ctype = models_body, "application/json"
            elif "schedules" in self.path:
                data, ctype = schedules_body, "application/json"
            else:
                data, ctype = html, "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    pg.goto("http://127.0.0.1:%d/cron.html" % srv.server_address[1])
    pg.wait_for_selector(".sched-card", state="attached")
    # Agent names resolve from a separate, async request; the card refreshes
    # once that list arrives, so give it a moment before asserting on it.
    pg.wait_for_timeout(400)
    yield pg
    pg.close()
    srv.shutdown()


def _card(page, i):
    return page.locator(".sched-card").nth(i)


def test_a_card_with_a_known_agent_shows_its_name(cards_page):
    chip = _card(cards_page, 0).locator(".sched-agent")
    assert chip.count() == 1
    assert "Triage" in chip.inner_text()


def test_a_card_with_no_agent_shows_no_agent_badge_at_all(cards_page):
    assert _card(cards_page, 1).locator(".sched-agent").count() == 0


def test_a_card_naming_an_agent_not_in_the_list_still_shows_something(cards_page):
    """A deleted agent must not look identical to a schedule that never had
    one, so the id is shown as a fallback rather than nothing."""
    chip = _card(cards_page, 2).locator(".sched-agent")
    assert chip.count() == 1
    assert "agent-deleted-0009" in chip.inner_text()


# --- the agent loader must not claim the list is empty while it is loading --
# loadAgentsForRunAs() and loadSchedules() are two independent fetches to two
# different backends, started in the same pass with no ordering between them.
# loadAgentsForRunAs() ends with a recall to renderList(), added so a card
# never shows a raw agent id if the agent list arrives after the schedule
# list. But if the agents fetch answers first, that recall fires while
# allSchedules is still the initial empty array, and renderList() reads that
# as "the user has no schedules" and replaces the loading skeleton with the
# empty state -- even for a user who has plenty.
#
# The `page` and `cards_page` fixtures above both settle every fetch before
# they ever hand back control, so they cannot see this. This test holds the
# schedules response open on purpose, so the agents fetch is guaranteed to
# land and repaint first while the schedules fetch is still outstanding.

def test_agents_landing_first_does_not_claim_the_list_is_empty(browser):
    html = (STATIC / "cron.html").read_bytes()
    agents_body = json.dumps({"items": AGENTS, "total": len(AGENTS)}).encode()
    # A user with real schedules. If the race fires, this must never be
    # reported as empty, even for a moment.
    schedules_body = json.dumps(CARD_ROWS).encode()

    release_schedules = threading.Event()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            if "models/list" in self.path:
                data, ctype = agents_body, "application/json"
            elif "schedules" in self.path:
                # Held open until the test releases it, so the agents fetch
                # is guaranteed to have already resolved and repainted the
                # list before the schedules fetch is allowed to answer.
                release_schedules.wait(5)
                data, ctype = schedules_body, "application/json"
            else:
                data, ctype = html, "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    try:
        pg.goto("http://127.0.0.1:%d/cron.html" % srv.server_address[1])
        # The agents fetch is not held open, so it wins the race and repaints
        # the Run as select before the schedules fetch is allowed to answer.
        pg.wait_for_function(
            "document.querySelectorAll('#run-as option').length > 1")
        # The schedules fetch is still parked on release_schedules here. The
        # page must still be showing the loading skeleton, not a verdict
        # about whether the user has any schedules.
        assert pg.locator(".empty-title", has_text="No schedules yet").count() == 0

        release_schedules.set()
        pg.wait_for_selector(".sched-card", state="attached")
        assert pg.locator(".sched-card").count() == len(CARD_ROWS)
    finally:
        release_schedules.set()
        pg.close()
        srv.shutdown()


# --- a schedule with nobody to run it ---------------------------------------
# Until 2026-09-24 an untouched "Run as" meant the App Builder: the prompt was
# composed into a task and Claude Code built an APP out of it. Two of the
# owner's daily schedules were created that way and delivered an AutoFix 404
# report to his Discord twice a day for months. That dispatch is gone; a
# schedule naming nobody now fails every time it fires.
#
# So the field is no longer a convenience with a sensible default. Every
# option below that lets the form post without an agent creates a schedule
# that provably cannot run, at 7pm, when nobody is watching. Better to refuse
# here, while the person is standing in front of it.


def test_the_field_offers_no_way_to_choose_nobody(page):
    """"Default assistant" read like a real choice and produced a dead
    schedule. Whatever the placeholder says now, it cannot be a value."""
    values = page.locator("#run-as option").evaluate_all(
        "os => os.map(o => o.value)")
    assert "" not in [v for v in values if v is not None] or all(
        page.locator("#run-as option[value='']").evaluate_all(
            "os => os.map(o => o.disabled)")), values


def test_the_form_will_not_post_a_schedule_with_no_agent(page):
    """The whole point. Filling everything else in and pressing create must
    not produce a schedule nobody runs."""
    _fill(page)
    page.locator("#create-btn").click()
    page.wait_for_timeout(400)
    assert not page.sent, "posted a schedule with no agent: %s" % (page.sent,)


def test_choosing_an_agent_still_posts(page):
    """The refusal must be about the missing agent, not about the form."""
    _fill(page)
    page.select_option("#run-as", "agent-scout-0001")
    page.locator("#create-btn").click()
    page.wait_for_timeout(400)
    assert page.sent and page.sent[-1]["agent_id"] == "agent-scout-0001"


def test_a_failed_agent_list_says_so_instead_of_posting_a_dead_schedule(page):
    """This used to assert the opposite: that losing the list must not take
    the form with it, "because the form works perfectly well without an
    agent". It no longer does. With no list there is nobody to pick, so the
    only honest outcome is to say the list could not load."""
    page.route("**/api/v1/models/list*", lambda r: r.abort())
    page.reload()
    page.wait_for_selector("#name", state="visible")
    _fill(page)
    page.locator("#create-btn").click()
    page.wait_for_timeout(500)
    assert not page.sent, "created a schedule nobody can run"
    assert "agent" in page.locator("#run-as-hint").inner_text().lower()
