"""The office draws what happens as it happens, from /agents/stream.

The stream is answered here with a real text/event-stream body, so the
page's own EventSource parses it: this exercises the wiring the browser
really uses, not a hook that bypasses it. Spec:
docs/superpowers/specs/2026-09-29-live-agent-office-design.md
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
]
IRIS = "agent-iris-a103"


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
            elif path.endswith("/agent-chat.css") or path.endswith("/htmx.min.js"):
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
    SERVED["activity"] = {}
    HITS["activity"] = 0
    opts = getattr(request, "param", {})
    srv = _serve((STATIC / "office.html").read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    if opts.get("no_event_source"):
        pg.add_init_script("delete window.EventSource;")
    if opts.get("clock"):
        pg.clock.install()

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
