"""Cron Jobs in the sidebar carries a red glowing number: unread outputs.

One unread cron output is 1, two are 2 (asked for 2026-11-23). It is the
server's unread count (migration 072), so reading an output on the
Cron Outputs page clears it everywhere.

ONLY the number. A card used to sit under the entry with the answers and
buttons in it; the owner asked the same day for it to go ("remove the
square ... only just the notif 1"), so these also pin that nothing but the
number is ever drawn, whatever is unread and whatever cron is new.

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
BADGE = "[data-aiui-cron-badge]"
ENTRY = "[data-aiui-cron-jobs]"
CARD = "[data-aiui-cron-notice]"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


def _out(rid, name, result="x"):
    return {"id": rid, "schedule_id": "s1", "name": name,
            "at": "2026-11-24T01:00:00+00:00", "status": "completed",
            "ok": True, "result": result, "unread": True}


class World:
    """What the mocked API answers. Change it and the next poll sees it."""

    def __init__(self):
        self.unread = []
        self.schedules = [{"id": "s1", "name": "Weekly review"}]


@pytest.fixture()
def shell(tmp_path_factory):
    """Yields (page, world, reload)."""
    work = tmp_path_factory.mktemp("cron-badge")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    shutil.copy(HERE / "shell_with_chrome.html", work / "index.html")
    handler = functools.partial(_Quiet, directory=str(work))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    world = World()

    def unread_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"count": len(world.unread),
                                       "items": world.unread[:3]}))

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


def test_nothing_unread_means_no_number(shell):
    page, _, _ = shell
    assert page.locator(BADGE).count() == 0


def test_the_number_is_the_unread_count(shell):
    """One unread output is Cron Jobs 1, two are Cron Jobs 2."""
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review")]
    _badge_is(page, "1")
    world.unread.append(_out("r2", "Inbox check"))
    _badge_is(page, "2")


def test_the_number_sits_on_the_cron_jobs_entry(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review")]
    _badge_is(page, "1")
    assert page.evaluate(
        "!!document.querySelector('[data-aiui-cron-jobs] [data-aiui-cron-badge]')")


def test_the_number_is_a_glowing_red_circle(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review")]
    _badge_is(page, "1")
    look = page.evaluate("""() => {
        const b = document.querySelector('[data-aiui-cron-badge]');
        const s = getComputedStyle(b);
        return {bg: s.backgroundColor, fg: s.color,
                w: b.getBoundingClientRect().width,
                h: b.getBoundingClientRect().height, shadow: s.boxShadow};
    }""")
    assert look["bg"] == "rgb(239, 68, 68)"
    assert look["fg"] == "rgb(255, 255, 255)"
    assert abs(look["w"] - look["h"]) < 1, "a circle, not a pill"
    assert look["shadow"] != "none", "it glows"


def test_reading_everything_takes_the_number_away(shell):
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review")]
    _badge_is(page, "1")
    world.unread = []
    page.wait_for_function(
        "!document.querySelector('[data-aiui-cron-badge]')", timeout=4000)


def test_a_read_on_the_outputs_page_drops_the_number_at_once(shell):
    """The outputs page posts aiui:cron-outputs-changed; the shell re-reads
    the count straight away instead of waiting for its next check."""
    page, world, _ = shell
    world.unread = [_out("r1", "Weekly review")]
    _badge_is(page, "1")
    world.unread = []
    page.evaluate("window.postMessage({type: 'aiui:cron-outputs-changed'}, location.origin)")
    page.wait_for_function(
        "!document.querySelector('[data-aiui-cron-badge]')", timeout=1500)


def test_only_the_number_never_a_card(shell):
    """Asked for 2026-11-23: remove the square, keep only the number."""
    page, world, _ = shell
    world.unread = [_out("r%d" % i, "Cron %d" % i, "an answer " * 40)
                    for i in range(4)]
    world.schedules.append({"id": "s2", "name": "A brand-new cron"})
    _badge_is(page, "4")
    page.wait_for_timeout(800)
    assert page.locator(CARD).count() == 0
    assert "an answer" not in page.locator("#sidebar").inner_text()
    assert "A brand-new cron" not in page.locator("#sidebar").inner_text()


def test_the_outputs_page_is_not_a_second_sidebar_row(shell):
    page, _, _ = shell
    assert page.locator(ENTRY).count() == 1
    assert page.locator("[data-aiui-cron-output]").count() == 0
