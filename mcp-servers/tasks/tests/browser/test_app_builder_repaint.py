"""The App Builder polls every 8 seconds, and it used to repaint regardless.

Rebuilding the grid destroys and recreates every card, so every thumbnail is
re-requested and the page visibly flickers on a timer. It also shut any open
card menu and threw away where the reader was.

The guard has to be exact in both directions: no repaint when nothing changed,
and an immediate repaint when something did, or a build that finishes would sit
there looking unfinished until the reader reloaded.
"""
import json
import http.server
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"


def _task(slug, status="completed", prompt="build me a thing"):
    return {"id": "t-" + slug, "status": status, "built_app_slug": slug,
            "title": prompt, "prompt": prompt,
            "created_at": "2026-08-01T00:00:00+00:00",
            "completed_at": "2026-08-01T00:10:00+00:00"}


TASKS = [_task("alpha-1111"), _task("beta-2222")]


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
def page(browser):
    html = (STATIC / "projects.html").read_bytes()

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

    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.set_default_timeout(7000)

    def route(r):
        url = r.request.url
        if "/api/projects/names" in url:
            body = {"names": {}}
        elif "/vercel" in url:
            body = {"connected": False}
        elif "/api/tasks" in url or "/api/projects" in url:
            body = TASKS
        else:
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    pg.goto("http://127.0.0.1:%d/projects.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiProjects")
    pg.wait_for_timeout(400)
    yield pg
    pg.close()
    srv.shutdown()


def _mark(page):
    """Stamp the live DOM so a rebuild can be detected. A rebuilt grid loses
    the stamp, because the nodes carrying it were thrown away."""
    return page.evaluate("""() => {
      const nodes = document.querySelectorAll('#content *');
      if (!nodes.length) return 0;
      nodes.forEach(n => n.setAttribute('data-repaint-probe', '1'));
      return nodes.length;
    }""")


def _survivors(page):
    return page.evaluate(
        "() => document.querySelectorAll('[data-repaint-probe]').length")


def test_rendering_the_same_data_again_does_not_rebuild_the_grid(page):
    """This is the flicker. The poll fires every 8 seconds whether or not
    anything changed."""
    marked = _mark(page)
    assert marked > 0, "nothing rendered, so this test proves nothing"

    # Render the exact payload the page already loaded, which is what the
    # 8 second poll does when nothing has happened.
    page.evaluate("""(tasks) => window.__aiuiProjects.renderCards(tasks)""",
                  TASKS)
    page.wait_for_timeout(200)

    assert _survivors(page) == marked, (
        "the grid was rebuilt even though nothing changed, which is the flicker")


def test_a_real_change_repaints_immediately(page):
    """The guard must not become a stale page: a build that finishes has to
    show up without the reader reloading."""
    _mark(page)

    changed = TASKS + [_task("gamma-3333", prompt="a brand new project")]
    page.evaluate("""(tasks) => window.__aiuiProjects.renderCards(tasks)""",
                  changed)
    page.wait_for_timeout(200)

    assert _survivors(page) == 0, "a changed project list did not repaint"


def test_a_status_change_alone_repaints(page):
    """Status badges flipping from building to built is the whole reason the
    poll exists."""
    _mark(page)

    building = [_task("alpha-1111", status="running"), TASKS[1]]
    page.evaluate("""(tasks) => window.__aiuiProjects.renderCards(tasks)""",
                  building)
    page.wait_for_timeout(200)

    assert _survivors(page) == 0, "a status change did not repaint"


def test_the_signature_ignores_nothing_the_cards_show(page):
    """A signature that missed an input would freeze that part of the card."""
    a = page.evaluate("(t) => window.__aiuiProjects.signature(t)", TASKS)
    b = page.evaluate("(t) => window.__aiuiProjects.signature(t)",
                      [_task("alpha-1111", prompt="different prompt"), TASKS[1]])
    assert a != b, "the prompt is shown on the card but not in the signature"
