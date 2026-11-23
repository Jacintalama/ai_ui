"""A new cron job says, in the sidebar, where its output will show.

A cron can be made from three places: the Cron Jobs page, the main chat
(the schedules tool) and Discord. Only the first one shows where the
answer goes. Made from the chat, nothing on screen said the result would
land on the Cron Jobs page, so people asked where to look.

So the sidebar checks this person's schedules, and when a new one appears
it puts a notice right under Cron Jobs: its name, where the output shows,
and a button that opens the page. A count on Cron Jobs says how many
things are waiting, and a finished run with a new result counts too.

Run against the real sidebar fixture over HTTP, with only the two API
routes the page calls answered by the test.
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


def _sched(sid, name, result_at=None, channel=None, platform="discord"):
    return {"id": sid, "name": name, "cron_expr": "0 9 * * 1-5",
            "tz": "Asia/Manila", "enabled": True, "prompt": "x",
            "last_result": "ok" if result_at else None,
            "last_result_at": result_at, "last_run_status":
            "completed" if result_at else None,
            "delivery_channel_id": channel, "delivery_platform": platform,
            "runs": []}


@pytest.fixture()
def shell(tmp_path_factory):
    """Yields (page, schedules, reload). `schedules` is the live list the
    mocked API answers with; change it and the next poll sees it."""
    work = tmp_path_factory.mktemp("cron-notice")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    shutil.copy(HERE / "shell_with_chrome.html", work / "index.html")
    handler = functools.partial(_Quiet, directory=str(work))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"

    schedules = [_sched("s1", "Weekly review", result_at="2026-11-20T09:00:00")]

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
        ctx.route("**/api/tasks/schedules*", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(schedules)))
        pg = ctx.new_page()

        def reload():
            pg.goto(base)
            pg.wait_for_selector(ENTRY, timeout=8000)
            # Let the first poll lay down what was already there.
            pg.wait_for_timeout(700)

        reload()
        yield pg, schedules, reload
        browser.close()
    httpd.shutdown()


def test_what_already_existed_is_not_announced(shell):
    page, _, _ = shell
    assert page.locator(NOTICE).count() == 0
    assert page.locator(BADGE).count() == 0


def test_a_new_cron_says_where_its_output_will_show(shell):
    page, schedules, _ = shell
    schedules.append(_sched("s2", "Inbox check (Gmail)"))
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "Inbox check (Gmail)" in text
    assert "Cron Jobs page" in text
    assert page.locator(BADGE).inner_text().strip() == "1"


def test_the_notice_sits_right_under_cron_jobs(shell):
    page, schedules, _ = shell
    schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    follows = page.evaluate(
        "document.querySelector('[data-aiui-cron-jobs]').nextElementSibling"
        ".hasAttribute('data-aiui-cron-notice')")
    assert follows


def test_a_cron_that_also_posts_to_discord_says_so(shell):
    page, schedules, _ = shell
    schedules.append(_sched("s2", "Quotes", channel="123", platform="discord"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "Discord" in page.locator(NOTICE).inner_text()


def test_a_name_is_shown_as_text_never_as_markup(shell):
    page, schedules, _ = shell
    schedules.append(_sched("s2", "<img src=x onerror=window.__pwned=1>"))
    page.wait_for_selector(NOTICE, timeout=4000)
    assert page.locator(NOTICE + " img").count() == 0
    assert "<img" in page.locator(NOTICE).inner_text()
    assert page.evaluate("window.__pwned") is None


def test_a_new_result_on_an_existing_cron_is_counted(shell):
    page, schedules, _ = shell
    schedules[0] = _sched("s1", "Weekly review",
                          result_at="2026-11-27T09:00:00")
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "Weekly review" in text and "new result" in text


def test_opening_cron_jobs_from_the_notice_clears_it(shell):
    page, schedules, _ = shell
    schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    page.locator(NOTICE + " [data-aiui-cron-open]").click()
    page.wait_for_selector("[data-aiui-embed][data-open]", timeout=5000)
    assert page.evaluate("location.pathname") == "/cronjobs"
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0
    assert page.locator(BADGE).count() == 0


def test_dismiss_clears_it_and_it_does_not_come_back(shell):
    page, schedules, reload = shell
    schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    page.locator(NOTICE + " [data-aiui-cron-dismiss]").click()
    assert page.locator(NOTICE).count() == 0
    reload()
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0, "seen survives a reload"


def test_an_unseen_notice_survives_a_reload(shell):
    page, schedules, reload = shell
    schedules.append(_sched("s2", "Inbox check"))
    page.wait_for_selector(NOTICE, timeout=4000)
    reload()
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "Inbox check" in page.locator(NOTICE).inner_text()
