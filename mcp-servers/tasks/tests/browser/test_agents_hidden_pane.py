"""A hidden AI Agents pane stops asking the server what its agents are doing.

The shell keeps a pane loaded after it is closed, so that reopening it is
instant. Closing sets the whole pane to display:none, and opening another
feature sets this page's frame to display:none. document.hidden sees neither,
because it only follows the browser tab. So a pane opened once went on
polling /api/tasks/agents/activity every 5 seconds, and the office inside it
every 30, for as long as the tab lived. The cost is measured in
docs/plans/2026-10-05-ai-agents-workspace-design.md.

The shell here is the real task-panel.js over shell_with_chrome.html, and the
pane is hidden by the shell's own code (Escape, and opening another feature),
never by the test setting display:none itself. The pages inside are the real
agents.html and office.html with their real stylesheet and vendor scripts.

The clock is Playwright's fake one, paused once the pane has loaded. That
makes the office's 30 second tick a call rather than a wait, and it means a
request seen while the clock stands still can only have come from the page
noticing it is back on screen, never from a timer that happened to be due.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"
AGENTS_OPEN = '[data-aiui-embed][data-open="/tasks/agents"]'

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": []},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
]

KINDS = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}


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
    shell = (HERE / "shell_with_chrome.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            kind = "text/html"
            rel = path[len("/tasks/static/"):]
            if path == "/task-panel.js":
                body, kind = (STATIC / "task-panel.js").read_bytes(), KINDS[".js"]
            elif path.startswith("/tasks/static/") and (STATIC / rel).is_file():
                # Served for real, vendor scripts included. A stubbed asset
                # hid a broken layout through a whole deploy once already.
                body = (STATIC / rel).read_bytes()
                kind = KINDS.get((STATIC / rel).suffix, kind)
            elif path.startswith("/tasks/agents"):
                body = (STATIC / "agents.html").read_bytes()
            elif path.startswith("/tasks/office"):
                body = (STATIC / "office.html").read_bytes()
            elif path.startswith("/tasks/"):
                # Another feature's pane. What it shows does not matter here,
                # only that opening it hides the agents frame.
                body = b"<!doctype html><title>another feature</title>"
            else:
                body = shell
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
def shell(browser, server):
    """The shell with the AI Agents pane open and its office drawn, the clock
    paused, and every activity request recorded with the page that made it."""
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    ctx.clock.install()
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    hits = []

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            # 204 tells an EventSource to stop for good, so the office's live
            # feed cannot start re-reads of its own in the middle of a count.
            r.fulfill(status=204, body="")
            return
        if "/agents/activity" in url:
            made_by = r.request.frame.url
            hits.append("office" if "/tasks/office" in made_by else "agents")
            body = {"activity": {}, "handoffs": []}
        elif "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": []}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=""))
    pg.goto("http://127.0.0.1:%d/" % server.server_address[1])
    pg.wait_for_selector("[data-aiui-agents]")
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    # The office is on demand since Phase 1 (2026-10-08): no frame exists
    # until the page's own Agent Office button asks for it.
    pane = pg.frame_locator("[data-aiui-embed] iframe").first
    pane.locator("#office-open").click()
    pane.locator("#office-body iframe").wait_for(state="attached")
    # That click put keyboard focus inside the pane, where the shell's own
    # Escape (the "closed" case below) cannot hear the key. Give focus back
    # to the shell document, where it was before the click.
    pg.evaluate("() => { document.activeElement.blur(); window.focus(); }")
    agents = next(f for f in pg.frames if "/tasks/agents" in f.url)
    agents.wait_for_function(
        "() => window.__aiuiAgents && window.__aiuiAgents.ready")
    office = next(f for f in pg.frames if "/tasks/office" in f.url)
    office.wait_for_selector(".who", state="attached")
    pg.clock.pause_at(pg.evaluate("Date.now()") + 1000)
    yield pg, hits
    ctx.close()


def _hide(pg, how):
    if how == "closed":
        # Escape is the shell's own way out: closeAiuiEmbed sets the whole
        # pane to display:none and keeps it loaded.
        pg.keyboard.press("Escape")
        pg.wait_for_selector(OPEN_PANE, state="detached")
    else:
        # Another feature opened in the same pane: the agents frame alone
        # goes to display:none.
        pg.locator("[data-aiui-graph]").click()
        pg.wait_for_selector('[data-aiui-embed][data-open="/tasks/graph"]')


def _advance(pg, ms):
    """Move the paused clock on, then give the requests it started real time
    to reach the route handler."""
    pg.clock.run_for(ms)
    pg.wait_for_timeout(500)


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_a_hidden_agents_pane_stops_polling(shell, how):
    pg, hits = shell
    # On screen it polls every 5 seconds. This keeps the zero below from
    # passing because nothing polls at all.
    start = hits.count("agents")
    _advance(pg, 11000)
    assert hits.count("agents") > start, "the agents page never polled on screen"

    _hide(pg, how)
    pg.wait_for_timeout(300)
    before = hits.count("agents")
    _advance(pg, 31000)
    assert hits.count("agents") == before, (
        "the agents page went on polling /api/tasks/agents/activity while the "
        "shell had it hidden (%s): %d new requests"
        % (how, hits.count("agents") - before))


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_showing_the_pane_again_catches_up_at_once(shell, how):
    pg, hits = shell
    _hide(pg, how)
    _advance(pg, 11000)             # ticks skipped while hidden
    before = hits.count("agents")
    # The clock stays paused from here, so no timer can fire.
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    pg.wait_for_timeout(1000)
    assert hits.count("agents") > before, (
        "reopening the pane left the activity dots stale until the next tick")


# --- the office inside it ----------------------------------------------------
# The floor is a frame inside the agents page, so inside the shell it is two
# frames down, and it has its own 30 second re-read.

@pytest.mark.parametrize("how", ["closed", "switched"])
def test_the_office_in_a_hidden_pane_stops_polling(shell, how):
    pg, hits = shell
    start = hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") > start, "the office never polled on screen"

    _hide(pg, how)
    pg.wait_for_timeout(300)
    before = hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") == before, (
        "the office went on polling while the shell had the pane hidden (%s)"
        % how)


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_the_office_catches_up_when_the_pane_is_shown(shell, how):
    pg, hits = shell
    _hide(pg, how)
    _advance(pg, 31000)             # its tick skipped while hidden
    before = hits.count("office")
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    pg.wait_for_timeout(1000)
    assert hits.count("office") > before, (
        "reopening the pane left the office floor stale until its next tick")


def test_the_office_hidden_inside_the_page_stops_polling(shell):
    """The page's own Hide button on the office. The pane is on screen, so
    only the office's frame is display:none, one frame further down."""
    pg, hits = shell
    agents = pg.frame_locator("[data-aiui-embed] iframe").first
    agents.locator("#office-close").click()
    agents.locator("#office-dock").wait_for(state="hidden")
    pg.wait_for_timeout(300)
    agents_before, office_before = hits.count("agents"), hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") == office_before, (
        "the office went on polling while the agents page had it hidden")
    assert hits.count("agents") > agents_before, (
        "hiding the office stopped the agents page's own poll as well")


def test_the_office_catches_up_when_the_page_shows_it_again(shell):
    """The page's own Hide, then Show. The shell's pane never left the
    screen, so no aiuiFrameVisible comes down from the shell: the agents page
    has to tell its floor itself, or the floor waits for its next tick."""
    pg, hits = shell
    agents = pg.frame_locator("[data-aiui-embed] iframe").first
    agents.locator("#office-close").click()
    agents.locator("#office-dock").wait_for(state="hidden")
    _advance(pg, 31000)             # its tick skipped while hidden
    before = hits.count("office")
    # The clock stays paused from here, so no timer can fire.
    agents.locator("#office-open").click()
    agents.locator("#office-dock").wait_for(state="visible")
    pg.wait_for_timeout(1000)
    assert hits.count("office") > before, (
        "showing the office again left the floor stale until its next tick")
