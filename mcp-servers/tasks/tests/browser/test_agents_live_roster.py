"""The agents list in miniature: the live feed on the conversation list.

The Agent Office already moves on /api/tasks/agents/stream. The agents page
only polled /api/tasks/agents/activity every 5 seconds, so an agent at work
looked the same as one at rest until the poll caught up. Now the page reads
the same feed: an avatar in the conversation list pulses while its agent is
working, rings while its answer has just gone out, and the open conversation
gets a plain line when a meeting opens or one agent asks another.

The page is the real agents.html with its real stylesheet and vendor
scripts, served the way test_agents_roster.py serves it. The stream answers
the way test_office_live.py's does, with one change: events are handed out
once, on the first request after the test queues them, with a short retry.
So nothing reaches the page before its list is drawn, and no event is seen
twice.
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

ADA = {"id": "agent-ada-0001", "name": "Ada",
       "meta": {"role": "Project manager", "toolIds": []},
       "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1}
IRIS = {"id": "agent-iris-a103", "name": "Iris",
        "meta": {"role": "Drive librarian", "toolIds": []},
        "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2}
BO = {"id": "agent-bo-0002", "name": "Bo",
      "meta": {"role": "Researcher", "toolIds": []},
      "params": {}, "user_id": "me", "created_at": 3, "updated_at": 3}
ROSTER = [ADA, IRIS, BO]
STRANGER = "agent-not-mine-9999"


def _av(agent_id):
    return ('#roster-list .roster-row[data-agent-id="%s"] .roster-av'
            % agent_id)


def _sse(events, retry):
    out = "retry: %d\n\nevent: hello\ndata: {}\n\n" % retry
    for e in events:
        out += "event: %s\ndata: %s\n\n" % (e["event"], json.dumps(e))
    return out


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
            if path.startswith("/tasks/static/") and (STATIC / rel).is_file():
                body = (STATIC / rel).read_bytes()
                kind = KINDS.get((STATIC / rel).suffix, kind)
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


class Live:
    """The agents page signed in as the owner of the roster, with a stream
    the test feeds."""

    def __init__(self, pg):
        self.pg = pg
        self.pending = []
        self.served = 0
        self.errors = []

    def send(self, *events):
        """Queue events and wait until a request to the stream took them."""
        self.pending.extend(events)
        want = self.served + len(events)
        for _ in range(60):
            if self.served >= want:
                break
            self.pg.wait_for_timeout(100)
        assert self.served >= want, "the page never read the live feed"
        # Let the page handle what it was just handed.
        self.pg.wait_for_timeout(300)


def _open(browser, server, roster=None, init_script=None):
    agents = list(ROSTER if roster is None else roster)
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    live = Live(pg)
    pg.on("pageerror", lambda exc: live.errors.append(str(exc)))
    if init_script:
        pg.add_init_script(init_script)

    def route(r):
        u = r.request.url
        if "/agents/stream" in u:
            events, live.pending[:] = list(live.pending), []
            live.served += len(events)
            r.fulfill(status=200, content_type="text/event-stream",
                      body=_sse(events, retry=200))
            return
        if "/api/v1/auths/" in u:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in u:
            body = {"items": agents, "total": len(agents)}
        elif "/agents/activity" in u:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/chat/" in u:
            r.fulfill(status=200, content_type="text/html", body="")
            return
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.locator("#roster-list .roster-row[data-agent-id]").first.wait_for(
        state="attached")
    pg.wait_for_timeout(300)
    return pg, live


def _sys_lines(pg):
    return pg.locator("#agent-thread .am.sys").all_inner_texts()


def test_a_running_agent_pulses_until_its_run_finishes(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "run_started", "agent_id": ADA["id"], "at": 1})
        pg.wait_for_selector(_av(ADA["id"]) + '[data-live="working"]')
        # Only that agent.
        assert pg.locator(_av(IRIS["id"]) + "[data-live]").count() == 0
        live.send({"event": "run_finished", "agent_id": ADA["id"], "at": 2,
                   "status": "done"})
        pg.wait_for_selector(_av(ADA["id"]) + "[data-live]", state="detached")
        assert not live.errors, live.errors
    finally:
        pg.close()


def test_a_speaking_agent_rings_for_as_long_as_its_answer(browser, server):
    pg, live = _open(browser, server)
    try:
        # 40 characters is 1600 ms, past the 1500 ms floor.
        live.send({"event": "speaking_started", "agent_id": IRIS["id"],
                   "at": 1, "chars": 40})
        assert pg.locator(
            _av(IRIS["id"]) + '[data-live="speaking"]').count() == 1
        pg.wait_for_timeout(2500)
        assert pg.locator(_av(IRIS["id"]) + "[data-live]").count() == 0, (
            "the ring outlived its answer")
        assert not live.errors, live.errors
    finally:
        pg.close()


def test_speaking_wins_over_working_and_hands_back(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "run_started", "agent_id": ADA["id"], "at": 1},
                  {"event": "speaking_started", "agent_id": ADA["id"],
                   "at": 2, "chars": 1})
        assert pg.locator(
            _av(ADA["id"]) + '[data-live="speaking"]').count() == 1
        # The 1500 ms floor passes and the run is still going.
        pg.wait_for_selector(_av(ADA["id"]) + '[data-live="working"]',
                             timeout=3000)
    finally:
        pg.close()


def test_the_live_state_survives_the_list_being_redrawn(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "run_started", "agent_id": ADA["id"], "at": 1})
        pg.wait_for_selector(_av(ADA["id"]) + '[data-live="working"]')
        # A search redraws the cards, and the list is rebuilt from them:
        # Ada's row goes, then comes back as a new element.
        pg.fill("#agent-search", "Iris")
        pg.wait_for_selector(_av(ADA["id"]), state="detached")
        pg.fill("#agent-search", "")
        pg.wait_for_selector(_av(ADA["id"]), state="attached")
        pg.wait_for_timeout(300)
        assert pg.locator(
            _av(ADA["id"]) + '[data-live="working"]').count() == 1
    finally:
        pg.close()


def test_a_meeting_is_a_line_in_the_room(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "meeting_started", "agent_id": ADA["id"],
                   "at": 1, "participants": [ADA["id"], IRIS["id"]]})
        assert _sys_lines(pg) == ["Meeting: Ada, Iris"]
        assert not live.errors, live.errors
    finally:
        pg.close()


#: The markup agent_chat_render.turn_open writes for one message: the
#: answers stream into .aturn-body later, by id. Seen on the local stack
#: 2026-10-13: a line appended to the thread itself landed BELOW the answers
#: of the round it opened, because those went into this body.
_TURNS = """
document.getElementById('agent-thread').insertAdjacentHTML('beforeend',
  '<div class="aturn" id="aturn-old"><div class="am user"><div class="ab">hi</div></div>' +
  '<div class="aturn-status"></div><div class="aturn-body">' +
  '<div class="am agent"><div class="ab">old answer</div></div></div></div>' +
  '<div class="aturn" id="aturn-new"><div class="am user"><div class="ab">team</div></div>' +
  '<div class="aturn-status"></div><div class="aturn-body"></div></div>');
"""


def test_a_meeting_line_opens_the_round_it_belongs_to(browser, server):
    pg, live = _open(browser, server)
    try:
        pg.evaluate(_TURNS)
        live.send({"event": "meeting_started", "agent_id": ADA["id"],
                   "at": 1, "participants": [ADA["id"], IRIS["id"]]})
        pg.wait_for_selector("#agent-thread .am.sys", state="attached")
        body = pg.locator("#aturn-new .aturn-body")
        assert body.locator(".am.sys").all_inner_texts() == ["Meeting: Ada, Iris"]
        # An answer streamed in afterwards goes below it, as the server does.
        pg.evaluate("""document.querySelector('#aturn-new .aturn-body')
          .insertAdjacentHTML('beforeend', '<div class="am agent">Ada here</div>')""")
        kids = pg.evaluate("""[...document.querySelector('#aturn-new .aturn-body')
          .children].map(e => e.className)""")
        assert kids == ["am sys", "am agent"], kids
        assert pg.locator("#aturn-old .am.sys").count() == 0
    finally:
        pg.close()


def test_a_handoff_line_goes_to_the_round_being_answered(browser, server):
    pg, live = _open(browser, server)
    try:
        pg.evaluate(_TURNS)
        # Ada is answering the newer message: its status line says so.
        pg.evaluate("""document.querySelector('#aturn-new .aturn-status')
          .textContent = 'Ada is working...'""")
        live.send({"event": "handoff", "agent_id": ADA["id"],
                   "target_agent_id": IRIS["id"], "at": 1})
        pg.wait_for_selector("#agent-thread .am.sys", state="attached")
        assert pg.locator("#aturn-new .aturn-body .am.sys").all_inner_texts() == [
            "Ada asked Iris"]
    finally:
        pg.close()


def test_a_handoff_is_a_line_in_the_room(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "handoff", "agent_id": ADA["id"],
                   "target_agent_id": IRIS["id"], "at": 1})
        assert _sys_lines(pg) == ["Ada asked Iris"]
    finally:
        pg.close()


def test_a_private_conversation_shows_only_lines_about_its_agent(
        browser, server):
    pg, live = _open(browser, server)
    try:
        pg.click('#roster-list .roster-row[data-agent-id="%s"]' % BO["id"])
        pg.wait_for_timeout(400)
        live.send({"event": "meeting_started", "agent_id": ADA["id"],
                   "at": 1, "participants": [ADA["id"], IRIS["id"]]},
                  {"event": "handoff", "agent_id": ADA["id"],
                   "target_agent_id": IRIS["id"], "at": 2},
                  {"event": "handoff", "agent_id": IRIS["id"],
                   "target_agent_id": BO["id"], "at": 3})
        assert _sys_lines(pg) == ["Iris asked Bo"]
    finally:
        pg.close()


def test_an_agent_not_on_the_list_changes_nothing(browser, server):
    pg, live = _open(browser, server)
    try:
        live.send({"event": "run_started", "agent_id": STRANGER, "at": 1},
                  {"event": "speaking_started", "agent_id": STRANGER,
                   "at": 2, "chars": 200},
                  {"event": "meeting_started", "agent_id": STRANGER, "at": 3,
                   "participants": [STRANGER, ADA["id"]]},
                  {"event": "handoff", "agent_id": STRANGER,
                   "target_agent_id": ADA["id"], "at": 4},
                  {"event": "handoff", "agent_id": ADA["id"],
                   "target_agent_id": ADA["id"], "at": 5})
        assert pg.locator("#roster-list [data-live]").count() == 0
        assert _sys_lines(pg) == []
        assert not live.errors, live.errors
    finally:
        pg.close()


def test_a_name_is_shown_as_text_not_markup(browser, server):
    bold = dict(ADA, name="<b>Bold</b>")
    pg, live = _open(browser, server, roster=[bold, IRIS])
    try:
        live.send({"event": "meeting_started", "agent_id": ADA["id"],
                   "at": 1, "participants": [ADA["id"], IRIS["id"]]},
                  {"event": "handoff", "agent_id": IRIS["id"],
                   "target_agent_id": ADA["id"], "at": 2})
        assert _sys_lines(pg) == ["Meeting: <b>Bold</b>, Iris",
                                  "Iris asked <b>Bold</b>"]
        assert pg.locator("#agent-thread .am.sys b").count() == 0
    finally:
        pg.close()


def test_without_event_source_the_page_still_works(browser, server):
    pg, live = _open(browser, server,
                     init_script="delete window.EventSource;")
    try:
        names = pg.locator(
            "#roster-list .roster-row .roster-name").all_inner_texts()
        assert names == ["Everyone", "Ada", "Iris", "Bo"]
        assert not live.errors, live.errors
    finally:
        pg.close()


# --- a running job (agent jobs, Part A Task 12) ------------------------------
# A job's steps are posted into the team chat by the background worker, not
# by the round this page streams, so the page has to fetch the thread again
# when the feed says a step or the job moved.

def _thread_fetches(pg):
    seen = []
    pg.on("request", lambda r: seen.append(r.url)
          if "/agents/chat/thread" in r.url else None)
    return seen


def test_a_finished_step_redraws_the_open_team_chat(browser, server):
    pg, live = _open(browser, server)
    try:
        seen = _thread_fetches(pg)
        live.send({"event": "step_finished", "agent_id": ADA["id"],
                   "job_id": "job-1", "step": 1, "of": 3, "status": "ok",
                   "at": 1})
        pg.wait_for_timeout(700)
        assert len(seen) == 1, seen
        assert not live.errors, live.errors
    finally:
        pg.close()


def test_a_burst_of_job_events_redraws_once(browser, server):
    pg, live = _open(browser, server)
    try:
        seen = _thread_fetches(pg)
        live.send({"event": "step_finished", "agent_id": ADA["id"],
                   "job_id": "job-1", "step": 1, "of": 2, "at": 1},
                  {"event": "step_started", "agent_id": IRIS["id"],
                   "job_id": "job-1", "step": 2, "of": 2, "at": 1},
                  {"event": "job_finished", "agent_id": ADA["id"],
                   "job_id": "job-1", "status": "done", "at": 1})
        pg.wait_for_timeout(700)
        assert len(seen) == 1, seen
    finally:
        pg.close()


def test_a_private_conversation_is_not_redrawn_for_a_job(browser, server):
    pg, live = _open(browser, server)
    try:
        pg.evaluate("id => { document.getElementById('ap-agent').value = id; }",
                    IRIS["id"])
        seen = _thread_fetches(pg)
        live.send({"event": "job_finished", "agent_id": ADA["id"],
                   "job_id": "job-1", "status": "done", "at": 1})
        pg.wait_for_timeout(700)
        assert seen == [], seen
    finally:
        pg.close()
