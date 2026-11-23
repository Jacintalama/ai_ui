"""The sidebar says what your cron jobs are doing, right under Cron Jobs.

Two things, from two places:

  - A NEW CRON (made in the chat, on the page or in Discord) gets a notice
    saying where its answers will land. This browser compares the person's
    schedules with what it saw last; what existed at the first check is never
    announced.
  - UNREAD OUTPUTS come from the server, read and unread like an email
    (migration 072, asked for 2026-11-23). The red glowing number on Cron
    Jobs IS the unread count: one unread output is 1, two are 2. The card
    shows the newest unread answers with View output, Mark all read and Hide.

Run against the real sidebar fixture over HTTP, with only the API routes the
page calls answered by the test.
"""
import functools
import http.server
import json
import pathlib
import shutil
import socketserver
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
NOTICE = "[data-aiui-cron-notice]"
BADGE = "[data-aiui-cron-badge]"
ENTRY = "[data-aiui-cron-jobs]"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


def _sched(sid, name, channel=None, platform="discord"):
    return {"id": sid, "name": name, "cron_expr": "0 9 * * 1-5",
            "tz": "Asia/Manila", "enabled": True, "prompt": "x",
            "delivery_channel_id": channel, "delivery_platform": platform,
            "runs": []}


def _out(rid, name, result, ok=True):
    return {"id": rid, "schedule_id": "s1", "name": name,
            "at": "2026-11-24T01:00:00+00:00", "status":
            "completed" if ok else "failed", "ok": ok, "result": result,
            "unread": True}


class World:
    """What the mocked API answers. Change it and the next poll sees it."""

    def __init__(self):
        self.schedules = [_sched("s1", "Weekly review")]
        self.unread = []
        self.read_all_calls = 0


@pytest.fixture()
def shell(tmp_path_factory):
    """Yields (page, world, reload)."""
    work = tmp_path_factory.mktemp("cron-notice")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    shutil.copy(HERE / "shell_with_chrome.html", work / "index.html")
    handler = functools.partial(_Quiet, directory=str(work))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    world = World()

    def unread_route(route):
        body = {"count": len(world.unread), "items": world.unread[:3]}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    def read_all_route(route):
        world.read_all_calls += 1
        world.unread = []
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "count": 0}))

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            httpd.shutdown()
            pytest.skip(f"chromium not installed: {exc}")
        ctx = browser.new_context()
        ctx.add_init_script(
            "localStorage.setItem('token', 't'); window.__aiuiCronPollMs = 250;")
        ctx.route("**/api/v1/auths/", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"email": "me@example.com", "role": "user"})))
        ctx.route("**/api/tasks/schedules", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(world.schedules)))
        ctx.route("**/api/tasks/schedules/outputs/unread*", unread_route)
        ctx.route("**/api/tasks/schedules/outputs/read-all", read_all_route)
        pg = ctx.new_page()

        def reload():
            pg.goto(base)
            pg.wait_for_selector(ENTRY, timeout=8000)
            pg.wait_for_timeout(700)

        reload()
        yield pg, world, reload
        browser.close()
    httpd.shutdown()


def _badge_is(page, text):
    page.wait_for_function(
        "(document.querySelector('[data-aiui-cron-badge]')||{}).textContent"
        f" === {json.dumps(text)}", timeout=4000)


# --- a new cron ------------------------------------------------------------

def test_what_already_existed_is_not_announced(shell):
    page, _, _ = shell
    assert page.locator(NOTICE).count() == 0
    assert page.locator(BADGE).count() == 0


def test_a_new_cron_says_where_its_answers_will_land(shell):
    page, world, _ = shell
    world.schedules.append(_sched("s2", "Inbox check (Gmail)"))
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "Inbox check (Gmail)" in text
    assert "Cron Outputs" in text
    assert page.locator(BADGE).count() == 0, "nothing unread yet"


def test_the_notice_sits_right_under_cron_jobs(shell):
    page, world, _ = shell
    world.schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert page.evaluate(
        "document.querySelector('[data-aiui-cron-jobs]').nextElementSibling"
        ".hasAttribute('data-aiui-cron-notice')")


def test_a_cron_that_also_posts_to_discord_says_so(shell):
    page, world, _ = shell
    world.schedules.append(_sched("s2", "Quotes", channel="123"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "Discord" in page.locator(NOTICE).inner_text()


def test_a_name_is_shown_as_text_never_as_markup(shell):
    page, world, _ = shell
    world.schedules.append(_sched("s2", "<img src=x onerror=window.__pwned=1>"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert page.locator(NOTICE + " img").count() == 0
    assert "<img" in page.locator(NOTICE).inner_text()
    assert page.evaluate("window.__pwned") is None


def test_a_new_cron_alone_opens_cron_jobs_and_clears(shell):
    page, world, _ = shell
    world.schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    btn = page.locator(NOTICE + " [data-aiui-cron-open]")
    assert btn.inner_text().strip() == "Open Cron Jobs"
    btn.click()
    page.wait_for_selector("[data-aiui-embed][data-open]", timeout=5000)
    assert page.evaluate("location.pathname") == "/cronjobs"
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0


def test_dismiss_clears_a_new_cron_and_it_does_not_come_back(shell):
    page, world, reload = shell
    world.schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    page.locator(NOTICE + " [data-aiui-cron-dismiss]").click()
    assert page.locator(NOTICE).count() == 0
    reload()
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0


def test_an_unseen_new_cron_survives_a_reload(shell):
    page, world, reload = shell
    world.schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    reload()
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "Inbox check" in page.locator(NOTICE).inner_text()


# --- unread outputs -----------------------------------------------------------

def test_the_count_is_the_number_of_unread_outputs(shell):
    """One unread output is Cron Jobs 1, two are Cron Jobs 2."""
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review", "done")]
    _badge_is(page, "1")
    world.unread.append(_out("r2", "Inbox check", "nothing new"))
    _badge_is(page, "2")


def test_the_count_is_a_glowing_red_circle(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review", "done")]
    _badge_is(page, "1")
    look = page.evaluate("""() => {
        const b = document.querySelector('[data-aiui-cron-badge]');
        const s = getComputedStyle(b);
        return {bg: s.backgroundColor, w: b.getBoundingClientRect().width,
                h: b.getBoundingClientRect().height, shadow: s.boxShadow};
    }""")
    assert look["bg"] == "rgb(239, 68, 68)"
    assert abs(look["w"] - look["h"]) < 1, "a circle, not a pill"
    assert look["shadow"] != "none", "it glows"


def test_the_unread_answer_itself_is_in_the_notice(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox check (Gmail)",
                         "Nothing new in the last 24 hours.")]
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "Inbox check (Gmail) has a new result" in text
    assert "Nothing new in the last 24 hours." in text


def test_a_long_answer_is_cut_short_until_show_more(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox", "Important: " + "word " * 200 + "THE END")]
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "THE END" not in page.locator(NOTICE).inner_text()
    more = page.locator(NOTICE + " [data-aiui-cron-more]")
    more.click()
    assert "THE END" in page.locator(NOTICE).inner_text()
    assert more.inner_text().strip() == "Show less"


def test_markup_in_an_answer_stays_text(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox", "<b id=boom>hi</b>")]
    page.wait_for_selector(NOTICE, timeout=4000)
    assert page.locator("#boom").count() == 0
    assert "<b id=boom>" in page.locator(NOTICE).inner_text()


def test_a_failed_run_says_it_failed_and_shows_why(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox", "Gmail refused: reconnect it.", ok=False)]
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "failed" in text.lower() and "Gmail refused: reconnect it." in text


def test_more_unread_than_shown_says_how_many_more(shell):
    page, world, _ = shell
    world.unread = [_out("r%d" % i, "Cron %d" % i, "x") for i in range(5)]
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "+2 more unread" in page.locator(NOTICE).inner_text()
    _badge_is(page, "5")


def test_view_output_opens_the_inbox_and_the_count_stays_until_read(shell):
    """Opening the page is not reading every email in it."""
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox check", "nothing new")]
    page.wait_for_selector(NOTICE, timeout=4000)
    btn = page.locator(NOTICE + " [data-aiui-cron-open]")
    assert btn.inner_text().strip() == "View output"
    btn.click()
    page.wait_for_selector("[data-aiui-embed][data-open]", timeout=5000)
    assert page.evaluate("location.pathname") == "/cronjobs/output"
    page.wait_for_timeout(800)
    assert page.locator(NOTICE).count() == 0, "no card over the inbox itself"
    assert page.locator(BADGE).inner_text().strip() == "1"


def test_mark_all_read_asks_the_server_and_clears_the_count(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "A", "x"), _out("r2", "B", "y")]
    _badge_is(page, "2")
    page.locator(NOTICE + " [data-aiui-cron-read-all]").click()
    page.wait_for_timeout(600)
    assert world.read_all_calls == 1
    assert page.locator(BADGE).count() == 0
    assert page.locator(NOTICE).count() == 0


def test_hide_keeps_the_count_and_a_newer_output_brings_the_card_back(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Inbox", "first")]
    page.wait_for_selector(NOTICE, timeout=4000)
    page.locator(NOTICE + " [data-aiui-cron-hide]").click()
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0
    assert page.locator(BADGE).inner_text().strip() == "1"
    world.unread.insert(0, _out("r2", "Inbox", "second"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "second" in page.locator(NOTICE).inner_text()


def test_the_outputs_page_is_not_a_second_sidebar_row(shell):
    page, _, _ = shell
    assert page.locator("[data-aiui-cron-jobs]").count() == 1
    assert page.locator("[data-aiui-cron-output]").count() == 0
