"""Seven agents and a conversation, on one screen.

Ralph, with a screenshot, 2026-09-18: "make it fit no need to scroll". The page
was built as a document, so the card grid grew it, the window scrolled, the
conversation scrolled inside that, and getting back to the composer meant
scrolling the window down again.

Rendered rather than read: whether a page scrolls is not visible in its CSS.
The rule that mattered was on .agent-panel, and the rule that broke it was the
card column growing past the window, which no amount of reading either
selector would have shown.
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

#: The page ships ten skeleton cards for the moment before the list arrives.
#: They carry the same class, so anything counting ".card" counts those too.
CARD = ".card:not([aria-hidden='true'])"

#: Ralph's actual roster, in the shape /api/v1/models/list returns. Seven,
#: because seven is what he has and six fitted before this change.
ROSTER = [
    ("Ada", "Project manager", ["code", "schedules", "remember"],
     ["daily-standup", "research-and-cite"]),
    ("Mia", "Receptionist", ["gmail"], ["draft-reply", "follow-up-chaser"]),
    ("Kai", "App reviewer", ["code"], ["app-bug-hunt", "review-my-app"]),
    ("Rex", "Programmer", ["code"], ["build-a-page"]),
    ("Nora", "Calendar keeper", ["calendar", "remember"], ["day-ahead"]),
    ("Iris", "Drive librarian", ["gdrive"], ["find-a-file"]),
    ("Vera", "Researcher", ["server:mcp-proxy", "remember"], ["web-check"]),
]

AGENTS = [
    {"id": "agent-%s" % name.lower(), "name": name,
     "user_id": ME, "base_model_id": "nvidia/nemotron-3-super-120b:free",
     "params": {"system": "You are %s. %s" % (name, role)},
     "meta": {"description": role, "toolIds": tools, "role": role,
              "toolScope": "picked", "skillIds": skills},
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": i, "updated_at": i,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}}
    for i, (name, role, tools, skills) in enumerate(ROSTER)
]


def _list_envelope(rows):
    return {"items": [dict(r) for r in rows if r.get("base_model_id")],
            "total": len(rows)}


def _api_envelope(rows):
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, tmp_path):
    """The page at a laptop's size, with seven agents in it.

    1440x900 rather than something generous: a screen that fits at 1500x1000
    and not on a laptop has not been made to fit.
    """
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    html = (tmp_path / "agents.html").read_bytes()
    css = (STATIC / "agent-chat.css").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                   # noqa: N802
            body, ctype = html, "text/html"
            if self.path.endswith(".css"):
                body, ctype = css, "text/css"
            elif self.path.endswith(".js"):
                # The page loads its panel script and vendored libraries from
                # /tasks/static. They are not what is under test and an empty
                # body keeps the layout honest: nothing here depends on a
                # script having run.
                body, ctype = b"", "application/javascript"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(5000)

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/agents/activity" in url:
            body = {"activity": {a["id"]: {"state": "ready"} for a in AGENTS}}
        elif url.rstrip("/").endswith("/api/tasks/agents/memory"):
            # Nothing learned yet, which is the case that used to cost every
            # card a line of text and a Show button.
            body = {"counts": {}}
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/skills" in url:
            body = {"skills": []}
        elif "/agents/tools" in url:
            body = {"tools": []}
        elif "/api/v1/models/list" in url:
            body = _list_envelope(AGENTS)
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_envelope(AGENTS)
        else:
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    # A real card, not one of the ten aria-hidden skeletons the page ships
    # with. Waiting on ".card" waits on a placeholder that is never visible.
    pg.wait_for_selector(CARD)
    yield pg
    pg.close()
    srv.shutdown()


def test_all_seven_agents_are_actually_rendered(page):
    """The rest of this file is worthless if the column is empty: a page with
    no cards in it fits trivially."""
    assert page.locator(CARD).count() == len(ROSTER)


def test_the_window_does_not_scroll(page):
    """Tried, not calculated. scrollHeight can exceed the window while the
    page is perfectly still; what a person notices is the page moving under
    them when they reach for the wheel."""
    page.mouse.move(700, 500)
    page.mouse.wheel(0, 1200)
    page.wait_for_timeout(120)
    assert page.evaluate("() => window.scrollY") == 0, (
        "the page scrolled under the panel")


def test_the_composer_is_on_screen_without_scrolling(page):
    """The thing the page is for. It sat below the fold whenever the agent
    list was long enough, which is every account with more than a few."""
    box = page.locator(".ap-composer").bounding_box()
    height = page.viewport_size["height"]
    assert box is not None, "the composer is not rendered at all"
    assert box["y"] + box["height"] <= height + 1, (
        "the composer is below the fold: %s in a %spx window" % (box, height))


def test_the_cards_column_carries_its_own_scrolling(page):
    """Seven cards will not always fit, and that is fine: the column scrolls,
    not the page. This is what stops a long roster taking the composer with
    it."""
    overflow = page.evaluate(
        "() => getComputedStyle(document.querySelector('.agents-main')).overflowY")
    assert overflow in ("auto", "scroll"), overflow


def test_the_conversation_is_the_only_thing_that_moves_inside_the_panel(page):
    """The panel is a column with a fixed foot: head, thread, composer. Only
    the thread may scroll, or the composer would drift again."""
    thread = page.evaluate(
        "() => getComputedStyle(document.querySelector('.ap-thread')).overflowY")
    panel = page.evaluate(
        "() => getComputedStyle(document.querySelector('.agent-panel')).overflowY")
    assert thread in ("auto", "scroll"), thread
    assert panel in ("visible", "hidden"), panel


def test_the_panel_fills_the_window_rather_than_a_guess_at_it(page):
    """It was calc(100vh - 32px), which is a guess about what else is on the
    page. Anything above it, a topbar or a banner, pushed its foot off the
    bottom of the screen."""
    height = page.viewport_size["height"]
    box = page.locator(".agent-panel").bounding_box()
    assert box["height"] <= height, "the panel is taller than the window"
    assert box["y"] + box["height"] <= height + 1
