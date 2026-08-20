"""How much of the screen the Cron page actually uses.

The page was capped at 1080px wide. On a 1920px monitor that left roughly 840px
of empty background, and the schedules queued up in a single tall column inside
the part that was left, so seeing the fourth one meant scrolling past three.

The fix is not "make it wider": a line of text stretched across 1900px is worse
than a narrow one. It is to give the width to the thing that benefits, which is
the list, by letting schedules sit side by side once there is room for two.

These are the facts that are easy to break again and impossible to see in a
diff, so they are measured at several viewport widths rather than eyeballed at
one.
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


def _rows(n):
    return [{
        "id": str(i), "name": "schedule number %d" % i,
        "prompt": "do the thing number %d" % i, "cron_expr": "0 9 * * *",
        "tz": "Asia/Manila", "enabled": i % 2 == 0, "run_once": False,
        "delivery_platform": "discord" if i % 2 else "slack",
        "delivery_channel_id": "D1",
        "last_run_at": "2026-08-17T11:00:00Z", "last_run_status": "completed",
    } for i in range(1, n + 1)]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronlayout")
    shutil.copy(STATIC / "cron.html", work / "index.html")
    body = json.dumps(_rows(6)).encode()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            if "schedules" in self.path:
                data, ctype = body, "application/json"
            else:
                data, ctype = (work / "index.html").read_bytes(), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                             # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def measure(browser, url, width, height=1000):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.goto(url)
    page.wait_for_selector(".sched-card", timeout=8000)
    page.wait_for_timeout(300)
    data = page.evaluate("""() => {
      const c = document.querySelector('.container');
      const cards = [...document.querySelectorAll('.sched-card')];
      const cb = c.getBoundingClientRect();
      // The container is full-width with padding, so its own left edge is 0.
      // The gutter a reader sees is where the CONTENT starts, which is the
      // padding when the container is fluid and the margin once it is capped.
      const cs = getComputedStyle(c);
      const padL = parseFloat(cs.paddingLeft) || 0;
      const padR = parseFloat(cs.paddingRight) || 0;
      const contentLeft = cb.left + padL;
      const contentWidth = cb.width - padL - padR;
      const overflowing = cards.filter(card => {
        const b = card.getBoundingClientRect();
        return [...card.querySelectorAll('*')].some(el => {
          const e = el.getBoundingClientRect();
          return e.width > 0 && (e.right > b.right + 0.5 || e.left < b.left - 0.5);
        });
      }).length;
      return {
        viewport: window.innerWidth,
        container: Math.round(contentWidth),
        gutter: Math.round(contentLeft),
        columns: new Set(cards.map(x =>
          Math.round(x.getBoundingClientRect().left))).size,
        cards: cards.length,
        overflowing,
        sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    }""")
    page.close()
    return data


# --- the width is used, and used for something ----------------------------

def test_a_wide_screen_is_not_mostly_empty(browser, server):
    """1080px of content on a 1920px monitor left 840px of background."""
    m = measure(browser, server, 1920)
    assert m["container"] >= 1500, m


def test_schedules_sit_side_by_side_when_there_is_room(browser, server):
    """The point of the extra width. One tall column meant scrolling past
    three schedules to reach the fourth."""
    m = measure(browser, server, 1920)
    assert m["columns"] >= 2, m


def test_a_laptop_still_gets_one_readable_column(browser, server):
    """Two columns squeezed into 1280px would be worse than one."""
    m = measure(browser, server, 1280)
    assert m["columns"] == 1, m


# --- and it still behaves at every size -----------------------------------

@pytest.mark.parametrize("width", [1280, 1500, 1920, 2560])
def test_the_content_keeps_a_gutter_on_both_sides(browser, server, width):
    """Ralph asked for the space at the edges specifically. Content running to
    the very edge of a wide monitor reads worse than content that is boxed."""
    m = measure(browser, server, width)
    assert m["gutter"] >= 16, m
    assert m["container"] + 2 * m["gutter"] <= width + 2, m


@pytest.mark.parametrize("width", [1024, 1280, 1500, 1920, 2560])
def test_nothing_overflows_a_card_and_the_page_never_scrolls_sideways(
        browser, server, width):
    m = measure(browser, server, width)
    assert m["overflowing"] == 0, m
    assert m["sideways"] is False, m


# --- the destructive action is not the neighbour of the useful one --------

def test_delete_is_separated_from_run_now(browser, server):
    """Three identical buttons, one of which deletes the schedule. Run now is
    what you reach for repeatedly; Delete is what you reach for once."""
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(server)
    page.wait_for_selector(".sched-card", timeout=8000)
    card = page.locator(".sched-card").first
    run = card.locator('[data-act="run"]').bounding_box()
    delete = card.locator('[data-act="delete"]').bounding_box()
    assert delete["x"] > run["x"] + run["width"] + 40, \
        "Delete is sitting right next to Run now"
    page.close()


def test_run_now_is_the_emphasised_action(browser, server):
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(server)
    page.wait_for_selector(".sched-card", timeout=8000)
    card = page.locator(".sched-card").first
    assert "primary" in (card.locator('[data-act="run"]').get_attribute("class") or "")
    page.close()
