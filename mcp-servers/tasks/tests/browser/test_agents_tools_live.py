"""The form must not offer a tool the person cannot use.

Task 3 built GET /api/tasks/agents/tools, which reports whether each native
tool is actually connected for the caller. This is the page reading that
report: an unconnected tool must be visibly and functionally unavailable
(disabled, with a way to fix it), not just labelled differently, because
Playwright driving a checkbox with page.check() is a real proxy for a user
clicking it -- it fails outright on anything not visible and enabled.

Also covers POST /api/tasks/agents/seed, which this page now calls once on
every load before it lists agents (see agents.html's bootstrap Promise.all).
"""
import http.server
import json
import pathlib
import shutil
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

ME = "user-me"

# One base model is enough to make /api/v1/models/list and /api/models
# answer something real; this file is not about the agent list, so it stays
# empty (a base model has no base_model_id, so /list excludes it too, same
# as production).
MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 1, "updated_at": 1, "user": None},
]


def _models_list_envelope(rows):
    items = [dict(r) for r in rows if r.get("base_model_id")]
    return {"items": items, "total": len(items)}


def _api_models_envelope(rows):
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


# What GET /api/tasks/agents/tools answers: gmail unconnected (with a way to
# fix it), documents connected, and the rest connected so a test checking one
# tool never has to know or care about the others.
TOOLS_BODY = {"tools": [
    {"id": "gmail", "label": "Gmail", "connected": False,
     "connect_url": "/tasks/static/connections.html"},
    {"id": "calendar", "label": "Calendar", "connected": True,
     "connect_url": None},
    {"id": "gdrive", "label": "Drive", "connected": True, "connect_url": None},
    {"id": "documents", "label": "Documents", "connected": True,
     "connect_url": None},
    {"id": "excel_creator", "label": "Excel", "connected": True,
     "connect_url": None},
    {"id": "executive_dashboard", "label": "Dashboard", "connected": True,
     "connect_url": None},
    {"id": "remember", "label": "Memory", "connected": True,
     "connect_url": None},
    # The connected apps umbrella, unconnected, which is the state every user
    # on this platform is actually in: tasks.user_connections is empty.
    {"id": "server:mcp-proxy", "label": "Your connected apps",
     "connected": False, "connect_url": "/tasks/static/connections.html"},
]}


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
def page_with_tools(browser, tmp_path):
    """Same page-serving setup as test_agents_page.py's `page` fixture, with
    two routes added: seed (tracked in `.sent`, so a test can count how many
    times it was called) and tools (answers TOOLS_BODY above)."""
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    html = (tmp_path / "agents.html").read_bytes()

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
    pg.set_default_timeout(5000)

    sent = []

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/api/v1/models/list" in url:
            body = _models_list_envelope(MODELS)
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_models_envelope(MODELS)
        elif "/api/tasks/agents/seed" in url:
            sent.append({"url": url, "method": r.request.method,
                        "body": r.request.post_data})
            body = {"seeded": True, "created": 2}
        elif "/api/tasks/agents/tools" in url:
            body = TOOLS_BODY
        else:
            sent.append({"url": url, "method": r.request.method,
                        "body": r.request.post_data})
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    pg.sent = sent
    yield pg
    pg.close()
    srv.shutdown()


def test_an_unconnected_tool_cannot_be_ticked(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    box = page.locator("#tool-gmail")
    assert box.is_disabled(), "it let them pick a tool they have not connected"


def test_an_unconnected_tool_offers_a_way_to_connect(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    tile = page.locator("label:has(#tool-gmail)")
    assert "Connect" in tile.inner_text()


def test_a_connected_tool_is_selectable(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    assert page.locator("#tool-documents").is_enabled()


def test_the_page_seeds_once_on_load(page_with_tools):
    seeds = [c for c in page_with_tools.sent if "/agents/seed" in c["url"]]
    assert len(seeds) == 1


def test_the_connected_apps_switch_is_disabled_with_nothing_behind_it(
        page_with_tools):
    """It is the same tick-and-do-nothing checkbox the tiles were fixed for.
    Nobody on this platform has connected a proxy app, so for every user the
    switch was offering a capability that does not exist."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    assert page.locator("#use-my-apps").is_disabled()


def test_the_disabled_switch_says_where_to_connect_one(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    link = page.locator(".umbrella-connect")
    assert link.count() == 1
    assert link.get_attribute("href")
