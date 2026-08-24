"""What the Agents page shows and what it sends.

An agent is an Open WebUI model row, so almost every bug here is a shape bug:
the wrong toolIds, instructions in the wrong place, or somebody else's agent
appearing in your list. Those are invisible to a test that reads copy, so the
page is rendered and driven.

The API is stubbed. That is a known blind spot and it is why the plan also
requires a real create-and-delete round trip during verification: a stub
answers whatever it is asked, which is exactly how a card requesting thumb.png
from a route serving thumb.jpg passed a full round of tests.
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
OTHER = "user-someone-else"

MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
    {"id": "agent-mine-a1b2", "name": "My Research Agent",
     "user_id": ME, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You research things carefully."},
     "meta": {"description": "mine", "toolIds": ["server:mcp-proxy"]}},
    {"id": "agent-shared-c3d4", "name": "Meeting Summariser",
     "user_id": OTHER, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You summarise meetings."},
     "meta": {"description": "platform", "toolIds": []}},
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
def page(browser, tmp_path):
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")

    # Served over HTTP rather than opened as a file. Chromium's Fetch API
    # refuses a file:// URL outright, so on a file:// page the page's own
    # /api/... calls never reach page.route and the list renders empty no
    # matter what the stub was told to answer.
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
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = {"data": MODELS}
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


def test_your_own_agent_is_listed(page):
    assert page.locator('[data-agent-id="agent-mine-a1b2"]').count() == 1


def test_the_base_model_is_not_listed_as_an_agent(page):
    """gpt-4o-mini is a model, not an agent. Only ids we minted are agents."""
    assert page.locator('[data-agent-id="gpt-4o-mini"]').count() == 0


def test_someone_elses_agent_is_not_in_your_list(page):
    mine = page.locator("#my-agents [data-agent-id]").all()
    assert all("shared" not in (el.get_attribute("data-agent-id") or "")
               for el in mine)


def test_a_platform_agent_appears_in_its_own_group(page):
    assert page.locator('#platform-agents [data-agent-id="agent-shared-c3d4"]').count() == 1


def test_a_platform_agent_offers_no_delete(page):
    card = page.locator('#platform-agents [data-agent-id="agent-shared-c3d4"]')
    assert card.locator('[data-act="delete"]').count() == 0
