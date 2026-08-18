"""What a schedule card shows, rendered.

Three things were wrong and none of them was visible to a test that reads
copy:

  Everything about a run was on three stacked lines. Where it goes, which
  timezone, and how it last ended are one thought, and they were three rows,
  which made a card describing one small job nearly as tall as the form that
  creates one.

  The prompt was printed under the title even when the title WAS the prompt.
  Schedules made from Discord and Slack are named after what they were asked
  to do, so most cards said the same sentence twice.

  The Enabled/Disabled badge dropped onto its own line the moment a title ran
  to two lines, so it sat somewhere different on every card depending on how
  long the name happened to be.
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

ROWS = [
    # name IS the prompt: the echo case
    {"id": "1", "name": "give me a motivational quote",
     "prompt": "give me a motivational quote", "cron_expr": "0 20 * * *",
     "tz": "Asia/Manila", "enabled": False, "run_once": False,
     "delivery_platform": "slack", "delivery_channel_id": "C1",
     "last_run_at": "2026-06-15T12:00:00Z", "last_run_status": "completed"},
    # name is a time prefix + the prompt: still an echo
    {"id": "2", "name": "every day at 7:00 PM: give me the best quote",
     "prompt": "give me the best quote", "cron_expr": "0 19 * * *",
     "tz": "Asia/Manila", "enabled": True, "run_once": False,
     "delivery_platform": "discord", "delivery_channel_id": "D1",
     "last_run_at": "2026-08-17T11:00:00Z", "last_run_status": "pending"},
    # a genuinely different prompt, which must still be shown
    {"id": "3", "name": "Weekday morning digest",
     "prompt": "Summarize my unread email and post the highlights.",
     "cron_expr": "0 9 * * 1-5", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": None, "last_run_status": None},
    # a long name, which is what used to displace the badge
    {"id": "4",
     "name": "every day at 7:00 PM: give me the best quote for this day "
             "and send give me news up",
     "prompt": "give me the best quote and the news for today, here in ph",
     "cron_expr": "0 19 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "discord",
     "delivery_channel_id": "D1", "last_run_at": "2026-08-17T11:00:00Z",
     "last_run_status": "pending"},
]


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = tmp_path_factory.mktemp("cron")
    shutil.copy(STATIC / "cron.html", work / "index.html")
    body = json.dumps(ROWS).encode()

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
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                             # noqa: BLE001
            srv.shutdown()
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page(viewport={"width": 1600, "height": 1000})
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        pg.wait_for_selector(".sched-card", timeout=8000)
        yield pg
        browser.close()
    srv.shutdown()


def card(page, i):
    return page.locator(".sched-card").nth(i)


def test_a_card_says_everything_about_a_run_on_one_line(page):
    """Where it goes, which timezone, how it last ended. One thought, one row."""
    chips = card(page, 0).locator(".sched-chips")
    assert chips.count() == 1
    text = chips.inner_text()
    for expected in ("Asia/Manila", "Slack", "Completed", "last run"):
        assert expected in text, f"{expected!r} left the meta line"


def test_the_prompt_is_not_printed_when_the_title_already_is_the_prompt(page):
    assert card(page, 0).locator(".sched-prompt").count() == 0


def test_a_title_that_is_a_time_prefix_plus_the_prompt_still_counts_as_an_echo(page):
    """Discord and Slack name a schedule "every day at 7:00 PM: <prompt>",
    which is the same sentence with a heading attached."""
    assert card(page, 1).locator(".sched-prompt").count() == 0


def test_a_prompt_that_says_something_new_is_still_shown(page):
    """The rule must not hide the one thing a card is for."""
    p = card(page, 2).locator(".sched-prompt")
    assert p.count() == 1
    assert "unread email" in p.inner_text()


def test_the_state_badge_stays_put_when_the_title_wraps(page):
    """It used to drop below a two-line title, so Enabled sat in a different
    place on every card depending on the length of its name."""
    long_card = card(page, 3)
    title = long_card.locator(".sched-name").bounding_box()
    badge = long_card.locator(".sched-badges").bounding_box()
    assert title["height"] > 20, "this case needs a title that actually wraps"
    assert badge["y"] < title["y"] + title["height"], \
        "the badge fell below the title instead of staying at the top right"


def test_a_card_is_not_as_tall_as_the_form_that_creates_one(page):
    for i in range(2):
        h = card(page, i).bounding_box()["height"]
        assert h <= 220, f"card {i} is {h}px tall"
