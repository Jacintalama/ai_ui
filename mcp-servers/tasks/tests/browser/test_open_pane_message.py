"""A page in a pane can open another pane, and can hand AI Agents a question.

The agents page and the office had no way to reach another feature except
sending the whole window there, which loads a bare page outside Open WebUI.
The shell now listens for {type: "aiui:open-pane", path} and opens that pane
exactly as its sidebar entry would. With path "/ai-agents" and an `ask`, it
hands the question to the agents page once that page has loaded, as
{type: "aiui-agents-ask", ask}. The agents page only PREFILLS its composer
with it; nothing is ever sent for the person.

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
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin || e.source !== window.parent) return;
    if (e.data && e.data.type === "aiui-agents-ask") window.__asks.push(e.data.ask);
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
    it to load rather than be posted into a page with no listener."""
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents",
        "ask": "  Ada, what changed today?  "})
    page.wait_for_function("() => location.pathname === '/ai-agents'", timeout=4000)
    agents = _frame(page, "/tasks/agents")
    agents.wait_for_function("() => window.__asks.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__asks") == ["Ada, what changed today?"]


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
