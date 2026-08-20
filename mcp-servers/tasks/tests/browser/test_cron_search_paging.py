"""Finding one schedule among many, and not scrolling past the rest.

The list rendered every schedule it had. That is fine at four and useless at
forty: no way to find one by name, and the page just grows.

Two additions, and the fiddly parts are the interactions between them rather
than either alone. Filtering has to reset the page, or you filter down to three
results while sitting on page 4 and see an empty list. Acting on a schedule has
to keep you where you were, or disabling something on page 2 throws you back to
page 1 and you lose your place. And a search that matches nothing has to say so,
rather than showing the "no schedules yet, create your first" copy to somebody
who has thirteen.
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
PAGE_SIZE = 6

NAMES = [
    "morning motivational quote", "weekday email digest",
    "nightly news roundup", "friday standup reminder",
    "monthly invoice summary", "hourly uptime check",
    "quote of the day", "weekly backup report",
    "daily crypto prices", "birthday reminders",
    "sprint retro notes", "expense report nudge",
    "sunday meal plan",
]


def _rows():
    return [{
        "id": str(i + 1), "name": name,
        "prompt": "do %s please" % name, "cron_expr": "0 9 * * *",
        "tz": "Asia/Manila", "enabled": i % 2 == 0, "run_once": False,
        "delivery_platform": "discord" if i % 2 else "slack",
        "delivery_channel_id": "D1",
        "last_run_at": "2026-08-17T11:00:00Z", "last_run_status": "completed",
    } for i, name in enumerate(NAMES)]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronpaging")
    shutil.copy(STATIC / "cron.html", work / "index.html")
    body = json.dumps(_rows()).encode()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            data, ctype = ((body, "application/json") if "schedules" in self.path
                           else ((work / "index.html").read_bytes(), "text/html"))
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):                                   # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

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


@pytest.fixture
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1600, "height": 1000})
    pg.set_default_timeout(4000)
    pg.goto(server)
    pg.wait_for_selector(".sched-card", timeout=8000)
    yield pg
    pg.close()


def names(page):
    return page.locator(".sched-card .sched-name").all_inner_texts()


def search(page, text):
    box = page.locator("#sched-search")
    box.fill(text)
    page.wait_for_timeout(250)


# --- pages of six ---------------------------------------------------------

def test_only_six_schedules_are_shown_at_once(page):
    assert page.locator(".sched-card").count() == PAGE_SIZE


def test_the_pager_reports_how_many_pages_there_are(page):
    """13 schedules at 6 a page is 3 pages, not 2."""
    assert "3" in page.locator("#pager-status").inner_text()


def test_the_next_page_shows_the_next_six_and_not_the_same_six(page):
    first = names(page)
    page.locator("#pager-next").click()
    page.wait_for_timeout(200)
    second = names(page)
    assert len(second) == PAGE_SIZE
    assert set(first).isdisjoint(second)


def test_the_last_page_holds_the_remainder(page):
    page.locator("#pager-next").click()
    page.locator("#pager-next").click()
    page.wait_for_timeout(200)
    assert page.locator(".sched-card").count() == len(NAMES) - 2 * PAGE_SIZE


def test_you_cannot_page_past_either_end(page):
    """Clicking only while enabled on purpose: Playwright waits for a disabled
    button to become enabled, so the first version of this test hung on the
    very behaviour it was checking for."""
    assert page.locator("#pager-prev").is_disabled()
    clicks = 0
    while not page.locator("#pager-next").is_disabled() and clicks < 10:
        page.locator("#pager-next").click()
        page.wait_for_timeout(120)
        clicks += 1
    assert clicks == 2, "13 schedules at 6 a page should be two steps to the end"
    assert page.locator("#pager-next").is_disabled()
    assert page.locator(".sched-card").count() > 0


def test_going_back_returns_the_earlier_page(page):
    first = names(page)
    page.locator("#pager-next").click()
    page.wait_for_timeout(150)
    page.locator("#pager-prev").click()
    page.wait_for_timeout(150)
    assert names(page) == first


# --- searching ------------------------------------------------------------

def test_search_narrows_the_list(page):
    search(page, "quote")
    shown = names(page)
    assert shown and all("quote" in n.lower() for n in shown)


def test_search_ignores_case(page):
    search(page, "QUOTE")
    assert names(page)


def test_search_also_looks_at_the_prompt(page):
    """A schedule named "nightly news roundup" is findable by what it does,
    which is often what you remember."""
    search(page, "do weekly backup")
    assert len(names(page)) == 1


def test_clearing_the_search_brings_everything_back(page):
    search(page, "quote")
    search(page, "")
    assert page.locator(".sched-card").count() == PAGE_SIZE
    assert "3" in page.locator("#pager-status").inner_text()


def test_a_search_matching_nothing_says_so(page):
    """And does NOT show the "create your first schedule" copy to somebody who
    has thirteen of them."""
    search(page, "zzzzz-no-such-thing")
    assert page.locator(".sched-card").count() == 0
    text = page.locator("#list-region").inner_text().lower()
    assert "no schedules match" in text or "nothing match" in text
    assert "your first" not in text


# --- the two features meeting -------------------------------------------

def test_searching_from_a_later_page_does_not_leave_you_on_an_empty_one(page):
    """Page 3 of 3, then filter to two results. Staying on page 3 would show
    an empty list and look broken."""
    page.locator("#pager-next").click()
    page.locator("#pager-next").click()
    page.wait_for_timeout(150)
    search(page, "quote")
    assert page.locator(".sched-card").count() > 0


def test_the_pager_disappears_when_the_filter_fits_on_one_page(page):
    search(page, "quote")
    assert page.locator("#pager").count() == 0 or \
        not page.locator("#pager").is_visible()


def test_the_count_reflects_what_the_filter_found(page):
    search(page, "quote")
    assert page.locator("#sched-count").inner_text().strip() == str(len(names(page)))


def test_acting_on_a_schedule_keeps_you_on_the_same_page(page):
    """Disabling something on page 2 must not throw you back to page 1."""
    page.locator("#pager-next").click()
    page.wait_for_timeout(200)
    before = names(page)
    page.locator('.sched-card [data-act="toggle"]').first.click()
    page.wait_for_timeout(700)
    assert names(page) == before
