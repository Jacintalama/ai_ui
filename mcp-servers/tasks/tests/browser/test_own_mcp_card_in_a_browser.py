"""Connections: add your own MCP server, in a real browser.

The functions are lifted out of the shipped integrations-ui.js by name, the
way test_the_connections_cards_in_a_browser.py does it, and the server is a
page.route stub. What is pinned:

  * the add card is last in the grid and opens the form;
  * Test shows the tools and which only read, or the server's sentence;
  * Save adds a card that shows the host, never the path or the token;
  * anything the server or the person typed stays text;
  * Remove asks first, then removes the card;
  * a server that stopped answering says so.
"""
import json
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")

HOSTILE = '<img src=x onerror="window.__pwned=1">'


def _lift():
    src = JS.read_text(encoding="utf-8")

    def fn(name):
        start = src.index("    function " + name + "(")
        return src[start:src.index("\n    }\n", start) + 6]
    slots = "\n".join(line.strip() for line in src.splitlines()
                      if line.strip().startswith("var SLOT_"))
    return "\n".join([slots] + [fn(n) for n in (
        "ownMcpAddCard", "ownMcpCard", "ownMcpLoad", "openOwnMcpPanel")])


HARNESS = """
    var ownServers = [];
    function authHeaders() { return {'Content-Type': 'application/json'}; }
    function askConfirm(opts) { window.__asked = opts.title; opts.onConfirm(); }
    function renderGrid() {
      var grid = document.getElementById('grid');
      grid.innerHTML = '';
      ownServers.forEach(function (s) { grid.appendChild(ownMcpCard(s)); });
      grid.appendChild(ownMcpAddCard());
    }
"""

SERVER = {"id": "s1", "label": "Acme", "host": "mcp.example.com",
          "tool_count": 2, "read_only_count": 1,
          "tools": ["list_customers", "create_invoice"], "not_used": [],
          "check_ok": True, "checked_at": "2026-11-27T10:00:00+00:00"}


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip("chromium not installed: %s" % exc)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page(viewport={"width": 1000, "height": 900})
    pg.set_default_timeout(5000)
    state = {"servers": [], "sent": []}

    def handle(route, request):
        url, method = request.url, request.method
        body = json.loads(request.post_data) if request.post_data else None
        state["sent"].append((method, url.split("/api/tasks")[-1], body))
        if url.endswith("/own-mcp/servers") and method == "GET":
            return route.fulfill(json={"servers": state["servers"]})
        if url.endswith("/own-mcp/servers/test"):
            return route.fulfill(json=state.get("test", {
                "ok": True, "not_used": [],
                "tools": [{"name": "list_customers", "read_only": True},
                          {"name": "create_invoice", "read_only": False}]}))
        if url.endswith("/own-mcp/servers") and method == "POST":
            if state.get("save_error"):
                return route.fulfill(status=400, json={"detail": state["save_error"]})
            state["servers"].append(dict(SERVER))
            return route.fulfill(json=dict(SERVER))
        if method == "DELETE":
            state["servers"] = []
            return route.fulfill(json={"removed": True})
        if url.endswith("/refresh"):
            return route.fulfill(json=dict(SERVER, tool_count=3))
        return route.fulfill(status=404, json={"detail": "nope"})

    pg.route("**/api/tasks/own-mcp/**", handle)
    pg.goto("about:blank")
    pg.route("http://app.test/", lambda r, q: r.fulfill(
        body="<html><body><div id=grid></div></body></html>", content_type="text/html"))
    pg.goto("http://app.test/")
    pg.add_script_tag(content=HARNESS + _lift())
    pg.state = state
    yield pg
    pg.close()


def _open_form(pg):
    pg.evaluate("renderGrid()")
    pg.locator("#grid > *").last.click()
    pg.wait_for_selector("#aiui-own-mcp-panel")


def test_the_add_card_is_last_and_opens_the_form(page):
    page.state["servers"] = [dict(SERVER)]
    page.evaluate("ownMcpLoad()")
    page.wait_for_function("ownServers.length === 1")
    page.evaluate("renderGrid()")
    assert "Add your own MCP server" in page.locator("#grid > *").last.inner_text()
    _open_form(page)
    for field in ("label", "url", "token"):
        assert page.locator(f"#aiui-own-mcp-{field}").count() == 1
    assert page.get_attribute("#aiui-own-mcp-token", "type") == "password"


def test_test_shows_the_tools_and_which_only_read(page):
    _open_form(page)
    page.fill("#aiui-own-mcp-label", "Acme")
    page.fill("#aiui-own-mcp-url", "https://mcp.example.com/k/abc123/mcp")
    page.click("#aiui-own-mcp-test")
    page.wait_for_selector("text=list_customers")
    result = page.inner_text("#aiui-own-mcp-result")
    assert "2 tools" in result and "only reads" in result
    assert page.state["servers"] == [], "Test stores nothing"


def test_a_refusal_shows_the_sentence_not_json(page):
    page.state["test"] = {"ok": False, "problem": "The address must start with https://."}
    _open_form(page)
    page.fill("#aiui-own-mcp-label", "Acme")
    page.fill("#aiui-own-mcp-url", "http://x")
    page.click("#aiui-own-mcp-test")
    page.wait_for_selector("text=must start with https")
    assert "{" not in page.inner_text("#aiui-own-mcp-result")


def test_save_adds_a_card_with_the_host_only(page):
    _open_form(page)
    page.fill("#aiui-own-mcp-label", "Acme")
    page.fill("#aiui-own-mcp-url", "https://mcp.example.com/k/abc123/mcp")
    page.fill("#aiui-own-mcp-token", "sk-SECRET123")
    page.click("#aiui-own-mcp-save")
    page.wait_for_selector("#aiui-own-mcp-panel", state="detached")
    page.wait_for_function("ownServers.length === 1")
    grid = page.inner_text("#grid")
    assert "Acme" in grid and "mcp.example.com" in grid and "2 tools" in grid
    assert "abc123" not in grid and "sk-SECRET123" not in page.content()
    posted = [b for m, p, b in page.state["sent"] if m == "POST" and p == "/own-mcp/servers"]
    assert posted == [{"label": "Acme", "url": "https://mcp.example.com/k/abc123/mcp",
                       "token": "sk-SECRET123"}]


def test_a_refused_save_keeps_the_form_and_says_why(page):
    page.state["save_error"] = "You can add up to 5 of your own servers."
    _open_form(page)
    page.fill("#aiui-own-mcp-label", "Acme")
    page.fill("#aiui-own-mcp-url", "https://mcp.example.com/mcp")
    page.click("#aiui-own-mcp-save")
    page.wait_for_selector("text=up to 5")
    assert page.locator("#aiui-own-mcp-panel").count() == 1


def test_hostile_text_stays_text(page):
    page.evaluate("s => { ownServers = [s]; renderGrid(); }",
                  dict(SERVER, label=HOSTILE, tools=[HOSTILE]))
    assert page.evaluate("window.__pwned") is None
    assert HOSTILE in page.inner_text("#grid")


def test_remove_asks_first_then_removes_the_card(page):
    page.state["servers"] = [dict(SERVER)]
    page.evaluate("ownMcpLoad()")
    page.wait_for_function("ownServers.length === 1")
    page.evaluate("renderGrid()")
    page.click("text=Remove")
    page.wait_for_function("ownServers.length === 0")
    assert "Acme" in page.evaluate("window.__asked")
    assert ("DELETE", "/own-mcp/servers/s1", None) in page.state["sent"]


def test_a_server_not_answering_says_so(page):
    page.evaluate("s => { ownServers = [s]; renderGrid(); }",
                  dict(SERVER, check_ok=False))
    assert "Not answering since" in page.inner_text("#grid")


def test_refresh_updates_the_card(page):
    page.state["servers"] = [dict(SERVER)]
    page.evaluate("ownMcpLoad()")
    page.wait_for_function("ownServers.length === 1")
    page.evaluate("renderGrid()")
    page.click("text=Refresh tools")
    page.wait_for_function("ownServers[0].tool_count === 3")
