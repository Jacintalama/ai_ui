"""The office draws what happens as it happens, from /agents/stream.

The stream is answered here with a real text/event-stream body, so the
page's own EventSource parses it: this exercises the wiring the browser
really uses, not a hook that bypasses it. Spec:
docs/superpowers/specs/2026-09-29-live-agent-office-design.md
"""
import datetime
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
]
IRIS = "agent-iris-a103"
ADA = "agent-research-assistant-0001"


def _sse(*events, retry=60000):
    out = "retry: %d\n\nevent: hello\ndata: {}\n\n" % retry
    for e in events:
        out += "event: %s\ndata: %s\n\n" % (e["event"], json.dumps(e))
    return out


STREAM = {"body": _sse()}
SERVED = {"activity": {}}
HITS = {"activity": 0}


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
            # The page, or one of its own files. The office's script moved
            # out of the page on 2026-10-08, and answering every path with
            # the HTML served a module that could not parse, so no robot
            # ever appeared and every test here errored at setup.
            path = self.path.split("?", 1)[0]
            body, kind = html, "text/html"
            if "/office/" in path:
                rel = path.split("/office/", 1)[1]
                asset = STATIC / "office" / rel
                if not asset.is_file():
                    self.send_error(404, "no such asset: %s" % rel)
                    return
                body = asset.read_bytes()
                kind = "text/css" if rel.endswith(".css") else "text/javascript"
            elif path.startswith("/tasks/agents/chat/"):
                # The side column's conversation. Answered with the page
                # itself, htmx put a whole office inside the office on every
                # load: 40 copies of #rooms by the end of one test, measured
                # 2026-10-14. test_office_page.py answers it the same way.
                body, kind = b'<div class="aempty">nothing yet</div>', "text/html"
                if path.endswith("/stream"):
                    self.send_response(204)
                    self.end_headers()
                    return
            elif (path.endswith("/agent-chat.css") or path.endswith("/agent-chat.js")
                  or path.endswith("/htmx.min.js") or path.endswith("/sse.js")
                  or path.endswith("/marked.min.js") or path.endswith("/purify.min.js")):
                rel = path.rsplit("/", 1)[1]
                asset = (STATIC / rel if (STATIC / rel).is_file()
                         else STATIC / "vendor" / rel)
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
    opts = getattr(request, "param", {})
    SERVED["activity"] = opts.get("activity", {})
    HITS["activity"] = 0
    srv = _serve((STATIC / "office.html").read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    if opts.get("no_event_source"):
        pg.add_init_script("delete window.EventSource;")
    if opts.get("clock"):
        pg.clock.install()
    if opts.get("init"):
        pg.add_init_script(opts["init"])

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            r.fulfill(status=200, content_type="text/event-stream",
                      body=STREAM["body"])
            return
        if "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            HITS["activity"] += 1
            body = {"activity": SERVED["activity"], "handoffs": []}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        else:
            body = {"skills": []}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    yield pg
    pg.close()
    srv.shutdown()


@pytest.fixture
def iris_starts_a_tool():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS,
         "at": "2026-09-30T10:00:00+00:00"},
        {"event": "tool_started", "agent_id": IRIS, "tool": "search_drive",
         "at": "2026-09-30T10:00:01+00:00"})
    yield
    STREAM["body"] = _sse()


def test_an_event_moves_the_floor_without_waiting_for_the_poll(iris_starts_a_tool, page):
    working = page.locator('.who[data-id="%s"][data-state="working"]' % IRIS)
    working.wait_for(timeout=3000)
    # The same body carries hello, which starts a re-read that answers "no
    # activity". Events that land while it is in flight must survive it, so
    # the state has to still be there once the re-read is long done.
    page.wait_for_timeout(1000)
    assert working.count() == 1
    assert working.locator(".tool-now").inner_text() == "search_drive"


@pytest.fixture
def iris_runs_and_finishes():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS,
         "at": "2026-09-30T10:00:00+00:00"},
        {"event": "tool_started", "agent_id": IRIS, "tool": "search_drive",
         "at": "2026-09-30T10:00:01+00:00"},
        {"event": "tool_finished", "agent_id": IRIS, "tool": "search_drive",
         "status": "ok", "at": "2026-09-30T10:00:02+00:00"},
        {"event": "run_finished", "agent_id": IRIS, "status": "ok",
         "at": "2026-09-30T10:00:03+00:00"})
    yield
    STREAM["body"] = _sse()


def test_a_finished_run_settles_and_drops_its_badge(iris_runs_and_finishes, page):
    page.wait_for_timeout(1500)
    who = page.locator('.who[data-id="%s"]' % IRIS)
    assert who.get_attribute("data-state") == "ready"
    assert who.locator(".tool-now").count() == 0


@pytest.fixture
def a_stranger_starts():
    STREAM["body"] = _sse({"event": "run_started", "agent_id": "agent-not-mine",
                           "at": "2026-09-30T10:00:00+00:00"})
    yield
    STREAM["body"] = _sse()


def test_an_event_for_an_agent_not_on_this_floor_draws_nothing(a_stranger_starts, page):
    page.wait_for_timeout(1000)
    assert page.locator('.who[data-id="agent-not-mine"]').count() == 0
    assert page.locator('.who[data-state="working"]').count() == 0


@pytest.fixture
def fast_reconnect():
    STREAM["body"] = _sse(retry=150)
    yield
    STREAM["body"] = _sse()


def test_every_reconnect_rereads_the_floor(fast_reconnect, page):
    page.wait_for_timeout(1500)
    # One read at start, then one per connection's hello; the body ends
    # after hello, so EventSource reconnects every 150ms.
    assert HITS["activity"] >= 4, HITS


@pytest.mark.parametrize("page", [{"no_event_source": True, "clock": True}],
                         indirect=True)
def test_without_event_source_the_slow_poll_still_updates(page):
    SERVED["activity"] = {IRIS: {"state": "working", "running_for_seconds": 3,
                                 "last_run_at": "2026-09-30T10:00:00+00:00",
                                 "source": "channel"}}
    working = page.locator('.who[data-id="%s"][data-state="working"]' % IRIS)
    page.clock.fast_forward(6000)
    page.wait_for_timeout(300)
    assert working.count() == 0
    page.clock.fast_forward(25000)
    working.wait_for(timeout=3000)


# --- the activity log --------------------------------------------------------
# "add logs activity" (2026-10-12). The live activity card is a log of what
# the stream delivered, newest first, not a list of each agent's latest run
# that forgot a job the moment the next one started.

def test_an_event_is_written_to_the_activity_log(iris_starts_a_tool, page):
    page.locator('.who[data-id="%s"][data-state="working"]' % IRIS).wait_for(timeout=3000)
    page.wait_for_timeout(300)
    lines = page.locator("#live li").all_inner_texts()
    assert any("Iris" in ln and "search_drive" in ln for ln in lines), lines
    assert any("Iris" in ln and "started working" in ln for ln in lines), lines
    # Newest first: the tool call came after the run started.
    tool = next(i for i, ln in enumerate(lines) if "search_drive" in ln)
    run = next(i for i, ln in enumerate(lines) if "started working" in ln)
    assert tool < run, lines


def test_a_finished_run_stays_in_the_log(iris_runs_and_finishes, page):
    page.wait_for_timeout(1500)
    lines = page.locator("#live li").all_inner_texts()
    assert any("Iris" in ln and "finished" in ln for ln in lines), lines
    assert any("search_drive" in ln for ln in lines), lines


def test_an_agent_not_on_this_floor_is_not_logged(a_stranger_starts, page):
    page.wait_for_timeout(1000)
    assert not any("agent-not-mine" in ln for ln in page.locator("#live li").all_inner_texts())


@pytest.mark.parametrize("page", [{"no_event_source": True, "clock": True}],
                         indirect=True)
def test_the_poll_writes_to_the_log_too(page):
    """No stream: the 30 second re-read is the only source, and a run it
    finds still gets a line, once."""
    SERVED["activity"] = {IRIS: {"state": "working", "running_for_seconds": 3,
                                 "last_run_at": "2026-09-30T10:00:00+00:00",
                                 "source": "channel"}}
    page.clock.fast_forward(31000)
    page.locator('.who[data-id="%s"][data-state="working"]' % IRIS).wait_for(timeout=3000)
    lines = page.locator("#live li").all_inner_texts()
    assert [ln for ln in lines if "Iris" in ln and "is working from channel" in ln], lines
    # A second read of the same row says nothing new.
    page.clock.fast_forward(31000)
    page.wait_for_timeout(300)
    again = page.locator("#live li").all_inner_texts()
    assert sum("is working from channel" in ln for ln in again) == 1, again


# --- the mouth and the dots --------------------------------------------------
# Measured on the local stack 2026-10-13: the mouth opened about 1.55 s
# BEFORE the answer appeared in the chat and closed within 10 ms of it,
# because it was drawn from the run working and agent turns are not
# streamed. The dots are the thinking; the mouth is the answer landing,
# which the server now says with speaking_started.

def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@pytest.fixture
def iris_answers():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS, "source": "channel",
         "at": "2026-09-30T10:00:00+00:00"},
        {"event": "run_finished", "agent_id": IRIS, "status": "ok",
         "at": "2026-09-30T10:00:01+00:00"},
        {"event": "speaking_started", "agent_id": IRIS, "chars": 40,
         "at": "2026-09-30T10:00:01+00:00"})
    yield
    STREAM["body"] = _sse()


def test_the_mouth_moves_with_the_answer_and_then_stops(iris_answers, page):
    who = page.locator('.who[data-id="%s"]' % IRIS)
    page.locator('.who[data-id="%s"][data-speaking="1"]' % IRIS).wait_for(timeout=3000)
    assert who.locator(".bot-mouth").evaluate(
        "el => getComputedStyle(el).animationName") == "talk"
    # The run is over, so nothing is being thought about.
    assert who.get_attribute("data-typing") is None
    assert who.locator(".talk-dots").count() == 0
    # 40 chars = 1600 ms; gone by 2500 ms.
    page.wait_for_timeout(2500)
    assert who.get_attribute("data-speaking") is None


@pytest.fixture
def iris_thinks():
    STREAM["body"] = _sse({"event": "run_started", "agent_id": IRIS,
                           "source": "channel", "at": "2026-09-30T10:00:00+00:00"})
    yield
    STREAM["body"] = _sse()


def test_thinking_shows_dots_but_no_mouth(iris_thinks, page):
    page.locator('.who[data-id="%s"][data-typing="1"]' % IRIS).wait_for(timeout=3000)
    assert page.locator('.who[data-id="%s"] .talk-dots' % IRIS).count() == 1
    assert page.locator('.who[data-id="%s"]' % IRIS).get_attribute("data-speaking") is None


def test_the_source_on_run_started_needs_no_poll(iris_thinks, page):
    """The poll answers {} here, so the only place "channel" can come from
    is the event itself. Before, run_started carried no source and the
    robot kept whatever the last poll said, which is how a private chat drew
    three agents in a meeting."""
    typing = page.locator('.who[data-id="%s"][data-typing="1"]' % IRIS)
    typing.wait_for(timeout=3000)
    # Long after hello's re-read has answered "no activity".
    page.wait_for_timeout(1000)
    assert HITS["activity"] >= 2, HITS
    assert typing.count() == 1


@pytest.fixture
def iris_was_in_a_meeting_now_chats():
    STREAM["body"] = _sse({"event": "run_started", "agent_id": IRIS,
                           "source": "channel", "at": _now()})
    yield
    STREAM["body"] = _sse()


@pytest.mark.parametrize("page", [{"activity": {IRIS: {
    "state": "ready", "last_status": "completed",
    "last_run_at": _now(), "source": "meeting"}}}], indirect=True)
def test_a_new_run_replaces_the_source_the_poll_last_saw(
        iris_was_in_a_meeting_now_chats, page):
    page.locator('.who[data-id="%s"][data-typing="1"]' % IRIS).wait_for(timeout=3000)
    page.wait_for_function(
        "() => !document.querySelector('.who-slot.walking')", timeout=6000)
    assert page.locator("#rooms").get_attribute("data-meeting") == ""


#: Watches every change on the floor from the first paint, so the test
#: cannot miss the walk by starting to look after it began. Records whether
#: Iris ever walked, and whether any robot's mouth was on while its slot was
#: still walking.
WATCH_WALK = """
window.__walked = false; window.__spokeWalking = false;
document.addEventListener('DOMContentLoaded', function () {
  new MutationObserver(function () {
    if (document.querySelector('.who-slot.walking[data-id="%s"]')) window.__walked = true;
    if (document.querySelector('.who-slot.walking .who[data-speaking="1"]'))
      window.__spokeWalking = true;
  }).observe(document.body, {subtree: true, attributes: true, childList: true,
                             attributeFilter: ['class', 'data-speaking']});
});
""" % IRIS


@pytest.fixture
def iris_answers_in_a_meeting():
    """The order the server really sends: the run, its end, and then the
    bubble. A meeting run moves Iris to the meeting room, so the answer lands
    while she is still on her way there."""
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS, "source": "meeting",
         "at": _now()},
        {"event": "run_finished", "agent_id": IRIS, "status": "ok",
         "at": _now()},
        {"event": "speaking_started", "agent_id": IRIS, "chars": 40,
         "at": _now()})
    yield
    STREAM["body"] = _sse()


@pytest.mark.parametrize("page", [{"init": WATCH_WALK}], indirect=True)
def test_a_robot_walks_first_and_speaks_on_arrival(iris_answers_in_a_meeting, page):
    slot = page.locator('.who-slot[data-id="%s"]' % IRIS)
    page.locator('.who[data-id="%s"][data-speaking="1"]' % IRIS).wait_for(timeout=5000)
    assert "walking" not in (slot.get_attribute("class") or "")
    got = page.evaluate("() => ({ walked: window.__walked,"
                        " spokeWalking: window.__spokeWalking })")
    assert got == {"walked": True, "spokeWalking": False}, got
    # The full time, counted from the arrival rather than the event.
    page.wait_for_timeout(1200)
    assert slot.locator(".who").get_attribute("data-speaking") == "1"
    page.wait_for_timeout(1000)
    assert slot.locator(".who").get_attribute("data-speaking") is None


# --- a meeting, from the round itself -----------------------------------------
# Measured on the local stack 2026-10-13: in a real meeting 0 robots were in
# the meeting room when the first answer landed, because the room was drawn
# from each run's source and the next speaker's run had not started yet.
# The round now says when it opens, who is in it, and when it closes.

def _in_meeting_room(page, agent_id):
    return page.evaluate(
        "id => { const r = document.querySelector('.zone[data-room=\"meeting\"]')"
        "  .getBoundingClientRect();"
        " const e = document.querySelector('.who-slot[data-id=\"' + id + '\"]');"
        " if (!e) return false; const x = e.getBoundingClientRect();"
        " return x.left >= r.left - 2 && x.right <= r.right + 2"
        "   && x.top >= r.top - 2 && x.bottom <= r.bottom + 2; }", agent_id)


def _meeting_count(page):
    return page.locator("#rooms").get_attribute("data-meeting")


def _settled(page, timeout=6000):
    """`walking` comes off a slot when its walk really ends, so no slot
    walking is the floor's own word that everybody has arrived."""
    page.wait_for_function(
        "() => !document.querySelector('.who-slot.walking')", timeout=timeout)
    page.wait_for_timeout(50)


@pytest.fixture
def a_meeting_opens():
    STREAM["body"] = _sse({"event": "meeting_started", "agent_id": ADA,
                           "participants": [ADA, IRIS], "at": _now()})
    yield
    STREAM["body"] = _sse()


def test_a_meeting_gathers_everybody_at_once(a_meeting_opens, page):
    """Nobody's run has started, and both are in the room: the round says
    who is in it, so nobody waits for their turn to walk in."""
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '2'",
        timeout=3000)
    _settled(page)
    assert _in_meeting_room(page, ADA)
    assert _in_meeting_room(page, IRIS)


@pytest.fixture
def a_meeting_opens_and_closes():
    STREAM["body"] = _sse(
        {"event": "meeting_started", "agent_id": ADA,
         "participants": [ADA, IRIS], "at": _now()},
        {"event": "meeting_ended", "agent_id": IRIS, "at": _now()})
    yield
    STREAM["body"] = _sse()


def test_a_meeting_lingers_then_breaks_up_together(a_meeting_opens_and_closes, page):
    """They stay a moment after the round (the last answer is still being
    said), then all walk back at once."""
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '2'",
        timeout=3000)
    page.wait_for_timeout(2000)
    assert _meeting_count(page) == "2"
    _settled(page)
    assert _in_meeting_room(page, ADA) and _in_meeting_room(page, IRIS)
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === ''",
        timeout=4000)
    _settled(page)
    assert not _in_meeting_room(page, ADA)
    assert not _in_meeting_room(page, IRIS)


@pytest.fixture
def a_meeting_whose_end_is_missed():
    """The round's meeting_ended never reaches this page: the stream is a
    fan-out with no log, and a deploy or a network blip in between means it
    is simply gone. The reconnect's hello is the only sign. Review finding,
    2026-10-14."""
    STREAM["body"] = _sse({"event": "meeting_started", "agent_id": ADA,
                           "participants": [ADA, IRIS], "at": _now()},
                          retry=300)
    yield
    STREAM["body"] = _sse()


def test_a_reconnect_does_not_leave_a_meeting_standing(
        a_meeting_whose_end_is_missed, page):
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '2'",
        timeout=3000)
    # Every later connection says hello and nothing about a meeting.
    STREAM["body"] = _sse(retry=60000)
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === ''",
        timeout=6000)


@pytest.fixture
def a_meeting_closed_then_another_begins_unannounced():
    """One meeting ran and closed. The next round's meeting_started is lost
    (the stream dropped between the two), and all this page hears is the
    first speaker's run beginning, from a meeting. Until 2026-10-16 the
    closed meeting blocked the source rule for good, so the new round drew
    nobody in the room."""
    STREAM["body"] = _sse(
        {"event": "meeting_started", "agent_id": ADA,
         "participants": [ADA, IRIS], "at": _now()},
        {"event": "meeting_ended", "agent_id": IRIS, "at": _now()},
        retry=300)
    yield
    STREAM["body"] = _sse()


def test_a_later_meeting_still_gathers_from_its_runs(
        a_meeting_closed_then_another_begins_unannounced, page):
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '2'",
        timeout=3000)
    # The harness replays its body on every reconnect, which would close the
    # meeting afresh each time; from here the stream says hello and nothing.
    STREAM["body"] = _sse(retry=300)
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === ''",
        timeout=8000)
    _settled(page)
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS, "source": "meeting",
         "at": _now()}, retry=60000)
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '1'",
        timeout=6000)
    _settled(page)
    assert _in_meeting_room(page, IRIS)
    assert not _in_meeting_room(page, ADA)


@pytest.fixture
def the_last_word_is_long():
    """Iris answers last with 125 characters (5 s of talking), and the round
    closes a moment later: the room has to wait for her to finish."""
    STREAM["body"] = _sse(
        {"event": "meeting_started", "agent_id": ADA,
         "participants": [ADA, IRIS], "at": _now()},
        {"event": "speaking_started", "agent_id": IRIS, "chars": 125,
         "at": _now()},
        {"event": "meeting_ended", "agent_id": IRIS, "at": _now()})
    yield
    STREAM["body"] = _sse()


def test_nobody_walks_away_still_talking(the_last_word_is_long, page):
    iris = page.locator('.who[data-id="%s"]' % IRIS)
    iris.and_(page.locator('[data-speaking="1"]')).wait_for(timeout=6000)
    # Whenever her mouth is moving, she is still in the room.
    for _ in range(12):
        if iris.get_attribute("data-speaking") != "1":
            break
        assert _meeting_count(page) == "2"
        page.wait_for_timeout(400)
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === ''",
        timeout=8000)


@pytest.fixture
def two_rounds_overlap():
    """The office chat and the agents page each ran a round. The first one
    closing must not close the second, which is still answering."""
    STREAM["body"] = _sse(
        {"event": "meeting_started", "agent_id": IRIS,
         "participants": [IRIS, ADA], "at": _now()},
        {"event": "meeting_started", "agent_id": IRIS,
         "participants": [IRIS], "at": _now()},
        {"event": "meeting_ended", "agent_id": ADA, "at": _now()})
    yield
    STREAM["body"] = _sse()


def test_one_round_ending_does_not_close_another(two_rounds_overlap, page):
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '1'",
        timeout=3000)
    page.wait_for_timeout(6000)
    assert _meeting_count(page) == "1"
    _settled(page)
    assert _in_meeting_room(page, IRIS)


#: Whether Iris was ever standing in the meeting room, checked on every
#: change to the floor from the first paint, so a visit cannot be missed by
#: looking too late.
WATCH_IRIS_IN_MEETING = """
window.__irisMet = false;
document.addEventListener('DOMContentLoaded', function () {
  new MutationObserver(function () {
    var z = document.querySelector('.zone[data-room="meeting"]');
    var e = document.querySelector('.who-slot[data-id="%s"]');
    if (!z || !e || e.classList.contains('walking')) return;
    var r = z.getBoundingClientRect(), x = e.getBoundingClientRect();
    if (x.left >= r.left - 2 && x.right <= r.right + 2 &&
        x.top >= r.top - 2 && x.bottom <= r.bottom + 2) window.__irisMet = true;
  }).observe(document.body, {subtree: true, attributes: true, childList: true});
});
""" % IRIS


@pytest.fixture
def a_meeting_without_iris():
    """Iris's run says `meeting`, but the round that is on did not name her.
    The round is the truth about who is in it."""
    STREAM["body"] = _sse(
        {"event": "meeting_started", "agent_id": ADA,
         "participants": [ADA], "at": _now()},
        {"event": "run_started", "agent_id": IRIS, "source": "meeting",
         "at": _now()})
    yield
    STREAM["body"] = _sse()


@pytest.mark.parametrize("page", [{"init": WATCH_IRIS_IN_MEETING}], indirect=True)
def test_an_agent_not_in_the_round_never_enters_the_room(a_meeting_without_iris, page):
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === '1'",
        timeout=3000)
    _settled(page)
    assert _in_meeting_room(page, ADA)
    assert not _in_meeting_room(page, IRIS)
    assert page.evaluate("() => window.__irisMet") is False


@pytest.fixture
def the_round_closes():
    STREAM["body"] = _sse({"event": "meeting_ended", "agent_id": IRIS,
                           "at": _now()})
    yield
    STREAM["body"] = _sse()


@pytest.mark.parametrize("page", [{"activity": {
    ADA: {"state": "ready", "last_status": "completed",
          "last_run_at": _now(), "source": "meeting"},
    IRIS: {"state": "working", "running_for_seconds": 2,
           "last_run_at": _now(), "source": "meeting"}}}], indirect=True)
def test_a_page_opened_mid_meeting_still_breaks_up_on_the_round(
        the_round_closes, page):
    """It never heard meeting_started, so the sources put them in the room.
    meeting_ended still closes it, rather than the 90 second guess."""
    assert _meeting_count(page) == "2"
    page.wait_for_function(
        "() => document.getElementById('rooms').getAttribute('data-meeting') === ''",
        timeout=6000)
    _settled(page)
    assert not _in_meeting_room(page, ADA)
    assert not _in_meeting_room(page, IRIS)


# --- a handoff ends with the run (2026-10-16) ---------------------------------
# "if they done talking in the office they didnt stop collaborating like
# talking to each other": the line, the walk and the "Asking Iris…" bubble
# lived their whole 90 s window whatever the asker was doing. A handoff is
# the asker's run calling a colleague; it ends when that run ends.

@pytest.fixture
def ada_asks_iris_then_finishes():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": ADA, "source": "channel", "at": _now()},
        {"event": "handoff", "agent_id": ADA, "target_agent_id": IRIS,
         "status": "ok", "at": _now()},
        retry=300)
    yield
    STREAM["body"] = _sse()


def test_the_asking_stops_when_the_askers_run_ends(ada_asks_iris_then_finishes, page):
    page.locator(".talk-line").first.wait_for(state="attached", timeout=4000)
    assert "Iris" in page.locator(".say").first.inner_text()
    # The round is over: Ada's run finishes.
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": ADA, "source": "channel", "at": _now()},
        {"event": "handoff", "agent_id": ADA, "target_agent_id": IRIS,
         "status": "ok", "at": _now()},
        {"event": "run_finished", "agent_id": ADA, "status": "completed", "at": _now()},
        retry=60000)
    page.wait_for_function(
        "() => !document.querySelector('.talk-line:not(.fading)')"
        " && !document.querySelector('.say:not(.going)')", timeout=4000)
    page.wait_for_timeout(800)
    assert page.locator(".talk-line").count() == 0
    assert page.locator(".say").count() == 0


@pytest.mark.parametrize("page", [{"activity": {
    ADA: {"state": "ready", "last_status": "completed",
          "last_run_at": _now(), "source": "channel"},
    IRIS: {"state": "ready", "last_status": "completed",
           "last_run_at": _now(), "source": "colleague"}}}], indirect=True)
def test_a_finished_askers_handoff_is_not_drawn_from_the_poll(page):
    """The poll says Ada is done. A handoff row from her run, however fresh,
    is over: nothing joins the two."""
    import json
    page.route("**/agents/activity**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": {
            ADA: {"state": "ready", "last_status": "completed",
                  "last_run_at": _now(), "source": "channel"},
            IRIS: {"state": "ready", "last_status": "completed",
                   "last_run_at": _now(), "source": "colleague"}},
            "handoffs": [{"from": ADA, "to": IRIS, "status": "ok", "at": _now()}]})))
    page.evaluate("() => window.aiuiRefreshOffice()")
    page.wait_for_timeout(500)
    assert page.locator(".talk-line").count() == 0
    assert page.locator(".say").count() == 0


# --- waking up (2026-10-21) -----------------------------------------------------

@pytest.fixture
def a_quiet_stream():
    """Nothing on the stream yet, reconnecting fast, so the test can put a
    run on it once the floor has drawn the sleeper."""
    STREAM["body"] = _sse(retry=300)
    yield
    STREAM["body"] = _sse()


@pytest.mark.parametrize("page", [{"activity": {
    IRIS: {"state": "ready", "last_status": "completed",
           "last_run_at": "2026-09-24T09:00:00+00:00", "source": "schedule"}}}], indirect=True)
def test_a_run_starting_at_a_quiet_desk_wakes_the_robot(a_quiet_stream, page):
    who = page.locator('.who[data-id="%s"]' % IRIS)
    assert who.get_attribute("data-state") == "asleep"
    STREAM["body"] = _sse({"event": "run_started", "agent_id": IRIS,
                           "source": "schedule", "at": _now()}, retry=60000)
    page.wait_for_function(
        "() => document.querySelector('.who[data-id=\"%s\"]').getAttribute('data-state') === 'working'" % IRIS,
        timeout=6000)
    slot = page.locator('.who-slot[data-id="%s"]' % IRIS)
    assert "waking" in (slot.get_attribute("class") or "")
    page.wait_for_timeout(1100)
    assert "waking" not in (slot.get_attribute("class") or "")


@pytest.mark.parametrize("page", [{"activity": {
    IRIS: {"state": "ready", "last_status": "completed",
           "last_run_at": "2026-09-24T09:00:00+00:00", "source": "schedule"}}}], indirect=True)
def test_a_run_starting_ends_the_dance(a_quiet_stream, page):
    """The floor never dances over a state."""
    page.locator('.who[data-id="%s"]' % IRIS).click()
    slot = page.locator('.who-slot[data-id="%s"]' % IRIS)
    slot.locator(".dance-btn").click()
    slot.locator('.dance-menu button[data-dance="bop"]').click()
    page.wait_for_timeout(80)
    assert "dancing" in (slot.get_attribute("class") or "")
    STREAM["body"] = _sse({"event": "run_started", "agent_id": IRIS,
                           "source": "schedule", "at": _now()}, retry=60000)
    page.wait_for_function(
        "() => document.querySelector('.who[data-id=\"%s\"]').getAttribute('data-state') === 'working'" % IRIS,
        timeout=6000)
    assert "dancing" not in (slot.get_attribute("class") or "")
    assert slot.get_attribute("data-dance") is None
