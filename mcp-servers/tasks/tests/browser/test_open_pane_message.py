"""A page in a pane can open another pane, and can hand AI Agents a question.

The agents page and the office had no way to reach another feature except
sending the whole window there, which loads a bare page outside Open WebUI.
The shell now listens for {type: "aiui:open-pane", path} and opens that pane
exactly as its sidebar entry would. With path "/ai-agents" and an `ask`, it
hands the question to the agents page once that page has loaded, as
{type: "aiui-agents-ask", ask}, plus `agent` and `name` when the office named
the agent it asked. The agents page only PREFILLS its composer with it;
nothing is ever sent for the person.

Only same-origin messages that come straight from one of the shell's own pane
frames count. Open WebUI renders chat artifacts in frames, and App Builder
shows app previews (/api/template-preview/, this same origin) in frames inside
its pane. Neither may drive the shell, and the last three tests pin that.

The shell is sidebar_collapsed_rail.html, the live v0.11.4 DOM. The pane
pages are stubs that record what they are handed, with the origin and source
checks the real agents page must make. These run over HTTP: file:// has an
opaque origin, and postMessage cannot target it.
"""
import functools
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

STUB = b"""<!doctype html><html><head><meta charset="utf-8"><title>stub pane</title></head>
<body><script>
  window.__asks = [];
  window.__msgs = [];
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin || e.source !== window.parent) return;
    if (e.data && e.data.type === "aiui-agents-ask") {
      window.__asks.push(e.data.ask);
      window.__msgs.push(e.data);
    }
  });
</script></body></html>"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
        else:
            body, ctype = (HERE / "sidebar_collapsed_rail.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(f"http://127.0.0.1:{server}/")
    pg.wait_for_selector("#sidebar [data-aiui-office]", timeout=8000)
    yield pg
    pg.close()


def _open(page, attr):
    page.locator(f"#sidebar [{attr}]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)


def _frame(page, href):
    """The pane frame that loaded `href`, once it has loaded."""
    for _ in range(40):
        for f in page.frames:
            if f.url.split("?")[0].endswith(href):
                f.wait_for_function("() => Array.isArray(window.__asks)")
                return f
        page.wait_for_timeout(100)
    raise AssertionError(f"no frame for {href}: {[f.url for f in page.frames]}")


def _post(frame, msg, target="location.origin", to="parent"):
    frame.evaluate(f"m => {to}.postMessage(m, {target})", msg)


def _shown(page):
    return page.evaluate(
        "Array.from(document.querySelectorAll('[data-aiui-embed] iframe'))"
        ".filter(f => f.style.display !== 'none').map(f => f.getAttribute('src'))")


# --- what it is for -------------------------------------------------------

def test_a_pane_opens_another_pane(page):
    _open(page, "data-aiui-agents")
    _post(_frame(page, "/tasks/agents"), {"type": "aiui:open-pane", "path": "/graph"})
    page.wait_for_function("() => location.pathname === '/graph'", timeout=4000)
    shown = _shown(page)
    assert len(shown) == 1 and shown[0].startswith("/tasks/graph"), shown


def test_the_office_hands_the_agents_page_a_question(page):
    """The agents frame does not exist yet, so the question has to wait for
    it to load rather than be posted into a page with no listener.

    The words arrive as the office wrote them. The meeting button's
    "everyone answer: " (office.html) keeps its trailing space here exactly
    as it does when the office is docked in the agents page, so the person
    types straight after it either way. The shell trimmed it until
    2026-10-05."""
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents",
        "ask": "everyone answer: "})
    page.wait_for_function("() => location.pathname === '/ai-agents'", timeout=4000)
    agents = _frame(page, "/tasks/agents")
    agents.wait_for_function("() => window.__asks.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__asks") == ["everyone answer: "]


def test_the_office_says_which_agent_it_asked(page):
    """A robot's Chat pill in the Agent Office pane. Docked, the same click
    opens that agent's own conversation because the office names the agent;
    the shell has to pass that on, or the click lands in the room instead."""
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents", "ask": "Iris, ",
        "agent": "agent-iris-a103", "name": "Iris"})
    agents = _frame(page, "/tasks/agents")
    agents.wait_for_function("() => window.__msgs.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__msgs") == [
        {"type": "aiui-agents-ask", "ask": "Iris, ",
         "agent": "agent-iris-a103", "name": "Iris"}]


def _hand_over_each(page, extras):
    """Post one Chat-pill ask per entry of `extras` from the office pane and
    return what the agents page was handed, in order."""
    _open(page, "data-aiui-office")
    office = _frame(page, "/tasks/office")
    for extra in extras:
        msg = {"type": "aiui:open-pane", "path": "/ai-agents", "ask": "Iris, "}
        msg.update(extra)
        _post(office, msg)
        page.wait_for_timeout(50)
    agents = _frame(page, "/tasks/agents")
    agents.wait_for_function(
        "n => window.__msgs.length === n", arg=len(extras), timeout=4000)
    return agents.evaluate("() => window.__msgs")


def test_only_an_agent_id_is_handed_over_as_one(page):
    """The id rides into the agents page's conversation switcher, so only
    the shape an agent id has goes with the question. Anything else is
    left off and the question still arrives, for the room."""
    got = _hand_over_each(page, [
        {"agent": "agent-iris-a103"},
        {"agent": "../../admin"},
        {"agent": "agent iris"},
        {"agent": "a" * 101},
        {"agent": ""},
        {"agent": 42},
        {"agent": ["agent-iris-a103"]},
    ])
    plain = {"type": "aiui-agents-ask", "ask": "Iris, "}
    assert got == [dict(plain, agent="agent-iris-a103")] + [plain] * 6, got


def test_only_a_short_name_is_handed_over(page):
    """The name is display text for the conversation header. Forty
    characters at most, and only with an agent it names."""
    got = _hand_over_each(page, [
        {"agent": "agent-iris-a103", "name": "I" * 40},
        {"agent": "agent-iris-a103", "name": "I" * 41},
        {"agent": "agent-iris-a103", "name": 7},
        {"name": "Iris"},
    ])
    base = {"type": "aiui-agents-ask", "ask": "Iris, "}
    assert got == [
        dict(base, agent="agent-iris-a103", name="I" * 40),
        dict(base, agent="agent-iris-a103"),
        dict(base, agent="agent-iris-a103"),
        base,
    ], got


def test_an_agents_page_already_loaded_gets_the_question_too(page):
    _open(page, "data-aiui-agents")
    agents = _frame(page, "/tasks/agents")
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents", "ask": "Mia, plan my week"})
    agents.wait_for_function("() => window.__asks.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__asks") == ["Mia, plan my week"]
    assert page.locator("[data-aiui-embed] iframe[src^='/tasks/agents']").count() == 1, \
        "the agents page was rebuilt instead of reused"


# --- what it must ignore --------------------------------------------------

def test_a_question_goes_to_no_other_page(page):
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"),
          {"type": "aiui:open-pane", "path": "/graph", "ask": "hello"})
    page.wait_for_function("() => location.pathname === '/graph'", timeout=4000)
    graph = _frame(page, "/tasks/graph")
    page.wait_for_timeout(500)
    assert graph.evaluate("() => window.__asks") == []


def test_an_overlong_question_is_not_handed_over(page):
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"),
          {"type": "aiui:open-pane", "path": "/ai-agents", "ask": "x" * 2001})
    page.wait_for_function("() => location.pathname === '/ai-agents'", timeout=4000)
    agents = _frame(page, "/tasks/agents")
    page.wait_for_timeout(800)
    assert agents.evaluate("() => window.__asks") == []


@pytest.mark.parametrize("path", ["/admin/settings", "/tasks/graph", "graph", ""])
def test_a_path_that_is_not_a_nav_entry_is_ignored(page, path):
    _open(page, "data-aiui-agents")
    _post(_frame(page, "/tasks/agents"), {"type": "aiui:open-pane", "path": path})
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"
    assert [s.split("?")[0] for s in _shown(page)] == ["/tasks/agents"]


def test_a_same_origin_frame_that_is_not_a_pane_is_ignored(page):
    """Like a chat artifact: same origin, but not one of the shell's panes."""
    page.evaluate("""() => new Promise((done) => {
      const f = document.createElement("iframe");
      f.name = "stranger"; f.srcdoc = "<p>stranger</p>"; f.onload = done;
      document.body.appendChild(f);
    })""")
    # An about:srcdoc frame reports location.origin as "null" while really
    # sharing the parent's origin, so it names the parent's as the target.
    _post(page.frame(name="stranger"), {"type": "aiui:open-pane", "path": "/graph"},
          target="parent.location.origin")
    page.wait_for_timeout(500)
    assert page.locator(OPEN_PANE).count() == 0


def test_a_frame_inside_a_pane_is_ignored(page):
    """Like an app preview inside App Builder: same origin, nested in one of
    our panes, and still not allowed to drive the shell."""
    _open(page, "data-aiui-agents")
    _frame(page, "/tasks/agents").evaluate("""() => new Promise((done) => {
      const f = document.createElement("iframe");
      f.name = "nested"; f.srcdoc = "<p>nested</p>"; f.onload = done;
      document.body.appendChild(f);
    })""")
    _post(page.frame(name="nested"),
          {"type": "aiui:open-pane", "path": "/graph"},
          target="top.location.origin", to="top")
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"


def test_another_origin_is_ignored_even_in_a_pane_frame(page, server):
    """The pane frame itself, navigated to a different origin (localhost is
    not 127.0.0.1 to a browser)."""
    _open(page, "data-aiui-agents")
    page.evaluate(
        "port => { document.querySelector(\"[data-aiui-embed] iframe[src^='/tasks/agents']\")"
        ".src = 'http://localhost:' + port + '/tasks/agents'; }", server)
    page.wait_for_timeout(800)
    other = next(f for f in page.frames if f.url.startswith("http://localhost"))
    _post(other, {"type": "aiui:open-pane", "path": "/graph"}, target="'*'")
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"


# --- the same click, end to end -------------------------------------------
#
# The real shell (task-panel.js in the live sidebar DOM), the real office as
# the Agent Office pane and the real agents page as the AI Agents pane, with
# only the API stubbed. Docked in the agents page, a robot's Chat pill opens
# that agent's own conversation (test_office_inline pins it). In the Agent
# Office pane the same click has to end in the same place, through
# aiui:open-pane and aiui-agents-ask, and not in the room.

ROSTER = [
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
]


class _RealPages(_Handler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        asset = STATIC / path[len("/tasks/static/"):] if path.startswith(
            "/tasks/static/") else None
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif asset is not None and asset.is_file():
            body = asset.read_bytes()
            ctype = "text/css" if path.endswith(".css") else "application/javascript"
        elif path.startswith("/tasks/office"):
            body, ctype = (STATIC / "office.html").read_bytes(), "text/html"
        elif path.startswith("/tasks/agents"):
            body, ctype = (STATIC / "agents.html").read_bytes(), "text/html"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
        else:
            body, ctype = (HERE / "sidebar_collapsed_rail.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def real_server():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_RealPages, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _api(route):
    url = route.request.url
    if "/api/v1/auths/" in url:
        body = {"id": "me", "email": "me@example.test", "role": "user"}
    elif "/models/list" in url:
        body = {"items": ROSTER, "total": len(ROSTER)}
    else:
        body = {"items": [], "total": 0}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _pane_frame(page, path):
    """The shell's own pane frame for `path`, not a frame nested in a pane."""
    for _ in range(60):
        for f in page.main_frame.child_frames:
            if f.url.split("?")[0].endswith(path):
                return f
        page.wait_for_timeout(100)
    raise AssertionError(f"no pane for {path}: {[f.url for f in page.frames]}")


def test_a_robots_chat_in_the_office_pane_opens_that_agents_conversation(
        browser, real_server):
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.set_default_timeout(8000)
    try:
        page.route("**/api/**", _api)
        page.route("**/tasks/agents/chat/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=""))
        page.goto(f"http://127.0.0.1:{real_server}/")
        page.wait_for_selector("#sidebar [data-aiui-office]")
        _open(page, "data-aiui-office")
        office = _pane_frame(page, "/tasks/office")
        pill = office.locator('.who-chat[data-id="agent-iris-a103"]')
        pill.wait_for()
        pill.click()
        page.wait_for_function("() => location.pathname === '/ai-agents'")
        agents = _pane_frame(page, "/tasks/agents")
        try:
            agents.wait_for_function(
                "() => (document.getElementById('ap-agent') || {}).value"
                " === 'agent-iris-a103'", timeout=6000)
        except playwright_api.TimeoutError:
            raise AssertionError(
                "the click did not open Iris's conversation: talking to %r,"
                " box %r" % (agents.locator("#ap-agent").input_value(),
                             agents.locator(".ap-composer input[name=message]"
                                            ).input_value()))
        assert agents.locator("#ap-who").inner_text() == "Iris"
        assert agents.locator(".ap-composer input[name=message]").input_value() == ""
    finally:
        page.close()
