"""Moving around inside the graph.

Ralph: "the user can also move inside the grap can view". Until now you could
drag one node and that was all, so with a few hundred nodes on a canvas sized
to the pane most of the board was unreachable.

The board is a canvas, so nothing here can be checked by reading the DOM. The
page exposes its view transform for exactly this reason, and these drive real
pointer and wheel events against it.
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

# A root and enough children that the board is bigger than the window.
GRAPH = {
    "nodes": [
        {"id": "r", "kind": "root", "label": "My Knowledge", "parent_id": None,
         "summary": None, "url": None},
        {"id": "h", "kind": "topic", "label": "AI Agents", "parent_id": "r",
         "summary": None, "url": "/ai-agents"},
        {"id": "a1", "kind": "agent", "label": "Ada", "parent_id": "h",
         "summary": "Project manager · 4 skills", "url": "/ai-agents"},
        {"id": "a2", "kind": "agent", "label": "Mia", "parent_id": "h",
         "summary": "Receptionist · 4 skills", "url": "/ai-agents"},
    ],
    "counts": {"agents": 2, "chats": 0},
}


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
    shutil.copy(STATIC / "graph.html", tmp_path / "graph.html")
    html = (tmp_path / "graph.html").read_bytes()

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

    pg = browser.new_page(viewport={"width": 1100, "height": 800})
    pg.set_default_timeout(5000)
    pg.route("**/api/tasks/graph/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(GRAPH)))
    pg.goto("http://127.0.0.1:%d/graph.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiGraphView")
    pg.wait_for_timeout(400)
    yield pg
    pg.close()
    srv.shutdown()


def _view(page):
    return page.evaluate("() => window.__aiuiGraphView()")


def _drag(page, x1, y1, x2, y2):
    page.mouse.move(x1, y1)
    page.mouse.down()
    page.mouse.move((x1 + x2) / 2, (y1 + y2) / 2)
    page.mouse.move(x2, y2)
    page.mouse.up()


def test_the_view_starts_untouched(page):
    v = _view(page)
    assert v["x"] == 0 and v["y"] == 0 and v["k"] == 1


def test_the_wheel_zooms(page):
    page.mouse.move(550, 400)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(120)
    assert _view(page)["k"] > 1.05, _view(page)


def test_zooming_out_works_too(page):
    page.mouse.move(550, 400)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(120)
    assert _view(page)["k"] < 0.95, _view(page)


def test_zoom_cannot_lose_the_board(page):
    """Unclamped, one hard scroll leaves somebody at 0.001 looking at nothing,
    with no way back that they would think to try."""
    page.mouse.move(550, 400)
    for _ in range(30):
        page.mouse.wheel(0, 2000)
    page.wait_for_timeout(150)
    assert _view(page)["k"] >= 0.25
    for _ in range(30):
        page.mouse.wheel(0, -2000)
    page.wait_for_timeout(150)
    assert _view(page)["k"] <= 4


def test_zoom_keeps_the_point_under_the_cursor(page):
    """Zooming about the centre instead of the pointer makes reaching a corner
    a fight: the thing you are aiming at runs away as you zoom.

    The page works in canvas-relative coordinates, and the canvas sits below a
    header. Mixing the two is what made the first draft of this test fail on
    correct code, which is worth more than the assertion.
    """
    # One argument, not two: page.evaluate passes a single value, so a pair
    # has to arrive as a pair. Getting that wrong reads back NaN rather than
    # an error, which looks exactly like broken zoom maths.
    world_at = ("(p) => { const r = document.getElementById('c')"
                ".getBoundingClientRect(), v = window.__aiuiGraphView();"
                " return {x: (p[0] - r.left - v.x) / v.k,"
                "         y: (p[1] - r.top - v.y) / v.k}; }")
    before = page.evaluate(world_at, [700, 300])
    page.mouse.move(700, 300)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(120)
    after = page.evaluate(world_at, [700, 300])
    assert abs(after["x"] - before["x"]) < 1.5, (before, after)
    assert abs(after["y"] - before["y"]) < 1.5, (before, after)


def test_dragging_the_background_moves_the_board(page):
    _drag(page, 200, 650, 340, 700)
    page.wait_for_timeout(120)
    v = _view(page)
    assert abs(v["x"] - 140) < 12, v
    assert abs(v["y"] - 50) < 12, v


def test_a_pan_does_not_close_the_panel(page):
    """A pan ends in a click event. Without a movement threshold, dragging the
    background dismisses whatever somebody was reading."""
    page.evaluate("() => window.__aiuiGraphFit()")
    page.wait_for_timeout(100)
    _drag(page, 250, 650, 420, 690)
    page.wait_for_timeout(150)
    assert _view(page)["x"] != 0


def test_reset_puts_the_view_back(page):
    page.mouse.move(550, 400)
    page.mouse.wheel(0, -500)
    _drag(page, 200, 650, 400, 700)
    page.wait_for_timeout(120)
    assert _view(page)["k"] != 1
    page.locator("#reset").click()
    page.wait_for_timeout(150)
    v = _view(page)
    assert v["x"] == 0 and v["y"] == 0 and v["k"] == 1, v


def test_the_legend_names_agents(page):
    assert "Agent" in page.locator(".legend").inner_text()


def test_fit_brings_everything_back_on_screen(page):
    """The escape hatch. Panning into empty space is easy and, without this,
    there is nothing in the interface that suggests a way back."""
    _drag(page, 200, 650, 900, 700)
    page.evaluate("() => window.__aiuiGraphFit()")
    page.wait_for_timeout(150)
    v = _view(page)
    assert 0.25 <= v["k"] <= 4
