"""/cronjobs/output: every answer your cron jobs gave, with the text.

Asked for 2026-11-23, after the sidebar notice: a place to READ the output,
not only a pointer to it. The page loads /api/tasks/schedules/outputs,
which only ever answers for the signed-in person.
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


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


def _out(sid, name, result, ok=True, at="2026-11-24T01:00:00+00:00"):
    return {"schedule_id": sid, "name": name, "at": at, "finished_at": at,
            "status": "completed" if ok else "failed", "ok": ok,
            "result": result}


@pytest.fixture()
def open_page(tmp_path_factory):
    work = tmp_path_factory.mktemp("cron-output")
    shutil.copy(STATIC / "cron-output.html", work / "cron-output.html")
    handler = functools.partial(_Quiet, directory=str(work))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/cron-output.html"

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            httpd.shutdown()
            pytest.skip(f"chromium not installed: {exc}")

        def go(rows=None, status=200):
            ctx = browser.new_context()
            ctx.route("**/api/tasks/schedules/outputs*", lambda r: r.fulfill(
                status=status, content_type="application/json",
                body=json.dumps(rows if rows is not None else [])))
            pg = ctx.new_page()
            pg.goto(base)
            pg.wait_for_function(
                "!document.getElementById('region').innerText.includes('Loading')",
                timeout=5000)
            return pg

        yield go
        browser.close()
    httpd.shutdown()


def test_each_output_shows_its_cron_and_its_answer(open_page):
    page = open_page([_out("a", "Inbox check (Gmail)", "Nothing new today."),
                      _out("b", "Weekly review", "3 cards moved to Done.")])
    text = page.locator("#region").inner_text()
    assert "Inbox check (Gmail)" in text and "Nothing new today." in text
    assert "Weekly review" in text and "3 cards moved to Done." in text
    assert page.locator("[data-output]").count() == 2


def test_a_failed_run_is_marked_failed(open_page):
    page = open_page([_out("a", "Inbox", "Gmail refused.", ok=False)])
    assert "Failed" in page.locator("[data-output]").inner_text()


def test_a_long_answer_folds_until_show_all(open_page):
    page = open_page([_out("a", "Inbox", "line\n" * 400 + "THE END")])
    more = page.locator("[data-output] .more")
    assert more.inner_text().strip() == "Show all"
    assert page.locator("[data-output] .out-text.clip").count() == 1
    more.click()
    assert page.locator("[data-output] .out-text.clip").count() == 0
    assert more.inner_text().strip() == "Show less"


def test_markup_in_an_answer_stays_text(open_page):
    page = open_page([_out("a", "<i id=n>x</i>", "<img src=x onerror=window.__p=1>")])
    assert page.locator("#n").count() == 0
    assert page.locator("[data-output] img").count() == 0
    assert page.evaluate("window.__p") is None


def test_the_filter_shows_one_cron_at_a_time(open_page):
    page = open_page([_out("a", "Inbox", "one"), _out("b", "Review", "two"),
                      _out("a", "Inbox", "three")])
    page.select_option("#filter", "a")
    assert page.locator("[data-output]").count() == 2
    assert "two" not in page.locator("#region").inner_text()


def test_nothing_yet_says_where_answers_will_come_from(open_page):
    page = open_page([])
    assert "No outputs yet" in page.locator("#region").inner_text()


def test_a_failed_load_says_so_and_offers_a_retry(open_page):
    page = open_page([], status=500)
    text = page.locator("#region").inner_text()
    assert "Could not load your outputs" in text
    assert page.locator("#region button").inner_text().strip() == "Try again"
