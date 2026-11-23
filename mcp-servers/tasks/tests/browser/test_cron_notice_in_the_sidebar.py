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


def _with_result(name, text, at="2026-11-27T09:00:00", status="completed"):
    s = _sched("s1", name, result_at=at)
    s["last_result"] = text
    s["last_run_status"] = status
    return s


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
    # The count is OUTPUTS waiting, and a brand-new cron has none yet.
    assert page.locator(BADGE).count() == 0


def test_the_count_is_how_many_crons_have_output_waiting(shell):
    """Asked for 2026-11-23: one cron with output is Cron Jobs 1, two are
    Cron Jobs 2."""
    page, schedules, _ = shell
    schedules[0] = _with_result("Weekly review", "done")
    page.wait_for_selector(BADGE, timeout=4000)
    assert page.locator(BADGE).inner_text().strip() == "1"
    schedules.append(_with_result("Inbox check", "nothing new"))
    schedules[1]["id"] = "s2"
    page.wait_for_function(
        "(document.querySelector('[data-aiui-cron-badge]')||{}).textContent"
        " === '2'", timeout=4000)


def test_the_count_is_a_glowing_red_circle(shell):
    page, schedules, _ = shell
    schedules[0] = _with_result("Weekly review", "done")
    page.wait_for_selector(BADGE, timeout=4000)
    look = page.evaluate("""() => {
        const b = document.querySelector('[data-aiui-cron-badge]');
        const s = getComputedStyle(b);
        return {bg: s.backgroundColor, radius: s.borderRadius,
                w: b.getBoundingClientRect().width,
                h: b.getBoundingClientRect().height, shadow: s.boxShadow};
    }""")
    assert look["bg"] == "rgb(239, 68, 68)"
    assert abs(look["w"] - look["h"]) < 1, "a circle, not a pill"
    assert look["shadow"] != "none", "it glows"


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


def test_the_result_itself_is_in_the_notice(shell):
    """Asked for 2026-11-23: the answer, in the sidebar, not a pointer to
    another page."""
    page, schedules, _ = shell
    schedules[0] = _with_result("Inbox check (Gmail)",
                                "Nothing new in the last 24 hours.")
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "Inbox check (Gmail)" in text
    assert "Nothing new in the last 24 hours." in text


def test_a_long_result_is_cut_short_until_show_more(shell):
    page, schedules, _ = shell
    long = "Important: " + "word " * 200 + "THE END"
    schedules[0] = _with_result("Inbox check", long)
    page.wait_for_selector(NOTICE, timeout=4000)
    assert "THE END" not in page.locator(NOTICE).inner_text()
    more = page.locator(NOTICE + " [data-aiui-cron-more]")
    assert more.inner_text().strip() == "Show more"
    more.click()
    assert "THE END" in page.locator(NOTICE).inner_text()
    assert more.inner_text().strip() == "Show less"


def test_markup_in_a_result_stays_text(shell):
    page, schedules, _ = shell
    schedules[0] = _with_result("Inbox", "<b id=boom>hi</b>")
    page.wait_for_selector(NOTICE, timeout=4000)
    assert page.locator("#boom").count() == 0
    assert "<b id=boom>" in page.locator(NOTICE).inner_text()


def test_a_second_result_replaces_the_first_rather_than_stacking(shell):
    page, schedules, _ = shell
    schedules[0] = _with_result("Inbox", "first answer",
                                at="2026-11-27T09:00:00")
    page.wait_for_selector(NOTICE, timeout=4000)
    schedules[0] = _with_result("Inbox", "second answer",
                                at="2026-11-27T15:00:00")
    page.wait_for_function(
        "document.querySelector('[data-aiui-cron-notice]')"
        ".innerText.includes('second answer')", timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "first answer" not in text
    assert page.locator(BADGE).inner_text().strip() == "1"


def test_a_failed_run_says_it_failed_and_shows_why(shell):
    page, schedules, _ = shell
    schedules[0] = _with_result("Inbox", "Gmail refused: reconnect it.",
                                status="failed")
    page.wait_for_selector(NOTICE, timeout=4000)
    text = page.locator(NOTICE).inner_text()
    assert "failed" in text.lower()
    assert "Gmail refused: reconnect it." in text


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


def test_with_output_waiting_the_button_opens_the_outputs_page(shell):
    """Asked for 2026-11-23: the output has its own page,
    /cronjobs/output, and the notice goes straight to it."""
    page, schedules, _ = shell
    schedules[0] = _with_result("Inbox check", "nothing new")
    page.wait_for_selector(NOTICE, timeout=4000)
    btn = page.locator(NOTICE + " [data-aiui-cron-open]")
    assert btn.inner_text().strip() == "View output"
    btn.click()
    page.wait_for_selector("[data-aiui-embed][data-open]", timeout=5000)
    assert page.evaluate("location.pathname") == "/cronjobs/output"
    page.wait_for_timeout(600)
    assert page.locator(NOTICE).count() == 0
    assert page.locator(BADGE).count() == 0


def test_the_outputs_page_is_not_a_second_sidebar_row(shell):
    page, _, _ = shell
    assert page.locator("[data-aiui-cron-jobs]").count() == 1
    assert page.locator("[data-aiui-cron-output]").count() == 0
