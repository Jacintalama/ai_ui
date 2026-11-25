"""/cronjobs/output: your cron outputs as an inbox, read and unread.

Asked for 2026-11-23 with a screenshot of the first version: "make this
unread read like an email setup", and fix the UI. The first version was one
long column of cards with raw markdown (`**…**` shown as asterisks) and most
of the screen empty.

Now it is a two-pane inbox: a list of outputs (cron name, preview, time, a
red dot and bold text while unread), and a reader that renders the answer's
markdown safely. Opening one marks it read on the server; Mark as unread and
Mark all read do what they say. Narrow screens get the list OR the reader,
with a way back.
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


def _out(rid, sid, name, result, ok=True, unread=False,
         at="2026-11-24T01:00:00+00:00"):
    return {"id": rid, "schedule_id": sid, "name": name, "at": at,
            "finished_at": at, "status": "completed" if ok else "failed",
            "ok": ok, "result": result, "unread": unread}


@pytest.fixture()
def inbox(tmp_path_factory):
    """go(rows, status=200, width=1280, want=None) -> (page, calls)."""
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

        def go(rows=None, status=200, width=1280, want=None):
            calls = {"read": [], "read_all": []}
            ctx = browser.new_context(viewport={"width": width, "height": 800})
            if want:
                ctx.add_init_script(
                    "localStorage.setItem('aiuiCronOutputWant', JSON.stringify("
                    + json.dumps({"schedule_id": want}) + ".schedule_id ? "
                    "{schedule_id: " + json.dumps(want) + ", at: Date.now()} : null));")

            def list_route(route):
                route.fulfill(status=status, content_type="application/json",
                              body=json.dumps(rows if rows is not None else []))

            def read_route(route):
                rid = route.request.url.split("/outputs/")[1].split("/read")[0]
                calls["read"].append((rid, json.loads(route.request.post_data or "{}")))
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"ok": True}))

            def read_all_route(route):
                calls["read_all"].append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"ok": True, "count": 0}))

            ctx.route("**/api/tasks/schedules/outputs?*", list_route)
            ctx.route("**/api/tasks/schedules/outputs/read-all", read_all_route)
            ctx.route("**/api/tasks/schedules/outputs/*/read", read_route)
            pg = ctx.new_page()
            pg.goto(base)
            pg.wait_for_function(
                "!document.getElementById('list-region').innerText.includes('Loading')",
                timeout=5000)
            return pg, calls

        yield go
        browser.close()
    httpd.shutdown()


ROWS = [
    _out("r1", "a", "Inbox check (Gmail)", "**Nothing new** today.\n\n- one\n- two",
         unread=True),
    _out("r2", "b", "Weekly review", "3 cards moved to Done.", unread=True),
    _out("r3", "a", "Inbox check (Gmail)", "Older answer.", unread=False),
]


def _rows(page):
    return page.locator(".row")


def test_it_is_a_list_and_a_reader_side_by_side(inbox):
    page, _ = inbox(ROWS)
    assert _rows(page).count() == 3
    assert page.locator(".list-pane").is_visible()
    assert page.locator(".reader-pane").is_visible()
    assert "Pick an output" in page.locator("#reader").inner_text()


def test_unread_ones_have_a_red_dot_and_bold_and_are_counted(inbox):
    page, _ = inbox(ROWS)
    assert page.locator(".row.unread").count() == 2
    dot = page.evaluate(
        "getComputedStyle(document.querySelector('.row.unread .dot')).backgroundColor")
    assert dot == "rgb(239, 68, 68)"
    weight = page.evaluate(
        "getComputedStyle(document.querySelector('.row.unread .row-name')).fontWeight")
    assert int(weight) >= 700
    assert page.locator("#n-unread").inner_text() == "2"
    assert page.locator("#n-all").inner_text() == "3"


def test_opening_one_reads_it_on_the_server(inbox):
    page, calls = inbox(ROWS)
    page.locator('.row[data-id="r1"]').click()
    page.wait_for_timeout(300)
    assert calls["read"] == [("r1", {"read": True})]
    assert page.locator('.row[data-id="r1"].unread').count() == 0
    assert page.locator("#n-unread").inner_text() == "1"


def test_the_reader_renders_markdown_instead_of_asterisks(inbox):
    page, _ = inbox(ROWS)
    page.locator('.row[data-id="r1"]').click()
    reader = page.locator("[data-reader]")
    assert reader.locator("strong").inner_text() == "Nothing new"
    assert reader.locator("li").count() == 2
    assert "**" not in reader.inner_text()


def test_the_preview_in_the_list_has_no_markdown_marks(inbox):
    page, _ = inbox(ROWS)
    snip = page.locator('.row[data-id="r1"] .row-snip').inner_text()
    assert snip.startswith("Nothing new today.") and "**" not in snip


def test_markup_in_an_answer_never_becomes_markup(inbox):
    page, _ = inbox([_out("x", "a", "<i id=n>name</i>",
                          "<img src=x onerror=window.__p=1> [click](javascript:alert(1))",
                          unread=True)])
    page.locator(".row").first.click()
    assert page.locator("#n").count() == 0
    assert page.locator("[data-reader] img").count() == 0
    assert page.locator("[data-reader] a").count() == 0, "only http(s) links"
    assert page.evaluate("window.__p") is None


def test_a_real_link_opens_in_a_new_tab_safely(inbox):
    page, _ = inbox([_out("x", "a", "News", "See [the post](https://example.com/a).")])
    page.locator(".row").first.click()
    a = page.locator("[data-reader] a")
    assert a.get_attribute("href") == "https://example.com/a"
    assert a.get_attribute("target") == "_blank"
    assert "noopener" in a.get_attribute("rel")


def test_mark_as_unread_puts_the_dot_back(inbox):
    page, calls = inbox(ROWS)
    page.locator('.row[data-id="r3"]').click()
    page.locator("[data-toggle-read]").click()
    page.wait_for_timeout(300)
    assert ("r3", {"read": False}) in calls["read"]
    assert page.locator('.row[data-id="r3"].unread').count() == 1


def test_the_unread_tab_shows_only_unread(inbox):
    page, _ = inbox(ROWS)
    page.locator('.tab[data-tab="unread"]').click()
    assert _rows(page).count() == 2


def test_one_read_on_the_unread_tab_stays_until_you_move_on(inbox):
    """Like mail: it does not vanish from under the cursor."""
    page, _ = inbox(ROWS)
    page.locator('.tab[data-tab="unread"]').click()
    page.locator('.row[data-id="r1"]').click()
    assert _rows(page).count() == 2
    page.locator('.row[data-id="r2"]').click()
    assert _rows(page).count() == 1


def test_mark_all_read_clears_every_dot_and_tells_the_server(inbox):
    page, calls = inbox(ROWS)
    page.locator("#mark-all").click()
    page.wait_for_timeout(300)
    assert calls["read_all"] == [{}]
    assert page.locator(".row.unread").count() == 0
    assert page.locator("#mark-all").is_disabled()


def test_mark_all_read_with_a_cron_picked_reads_only_that_cron(inbox):
    page, calls = inbox(ROWS)
    page.select_option("#filter", "b")
    page.locator("#mark-all").click()
    page.wait_for_timeout(300)
    assert calls["read_all"] == [{"schedule_id": "b"}]


def test_the_filter_shows_one_cron_at_a_time(inbox):
    page, _ = inbox(ROWS)
    page.select_option("#filter", "a")
    assert _rows(page).count() == 2


def test_view_output_on_a_cron_card_opens_that_crons_newest(inbox):
    page, calls = inbox(ROWS, want="a")
    assert page.locator("#filter").input_value() == "a"
    assert page.locator('.row[data-id="r1"]').get_attribute("aria-current") == "true"
    assert "Nothing new" in page.locator("[data-reader]").inner_text()


def test_a_failed_run_is_marked_failed(inbox):
    page, _ = inbox([_out("f", "a", "Inbox", "Gmail refused.", ok=False)])
    assert "Failed" in page.locator(".row").first.inner_text()


def test_on_a_phone_it_is_the_list_or_the_reader_with_a_way_back(inbox):
    page, _ = inbox(ROWS, width=390)
    assert page.locator(".list-pane").is_visible()
    assert not page.locator(".reader-pane").is_visible()
    page.locator('.row[data-id="r2"]').click()
    assert page.locator(".reader-pane").is_visible()
    assert not page.locator(".list-pane").is_visible()
    page.locator("[data-reader] .back").click()
    assert page.locator(".list-pane").is_visible()


def test_no_sideways_scroll_on_a_phone(inbox):
    page, _ = inbox(ROWS, width=320)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_nothing_yet_says_where_answers_will_come_from(inbox):
    page, _ = inbox([])
    assert "No outputs yet" in page.locator("#list-region").inner_text()


def test_a_failed_load_says_so_and_offers_a_retry(inbox):
    page, _ = inbox([], status=500)
    text = page.locator("#list-region").inner_text()
    assert "Could not load your outputs" in text
    assert page.locator("#list-region button").inner_text().strip() == "Try again"


# 2026-11-25, with a screenshot of the page in the shell and one of Gmail:
# "the right and left space... can you fill this all no space should be".
# The page stopped at 1280px and sat in the middle, and the answer stopped
# at 72 characters a line, so a wide screen was mostly empty on both sides.
WIDE = 1720  # the pane's width beside the sidebar on a 1920 screen


def test_on_a_wide_screen_the_inbox_fills_the_width(inbox):
    page, _ = inbox(ROWS, width=WIDE)
    box = page.locator(".inbox").bounding_box()
    assert box["x"] <= 16
    assert WIDE - (box["x"] + box["width"]) <= 16


def test_on_a_wide_screen_the_list_grows_too(inbox):
    page, _ = inbox(ROWS, width=WIDE)
    assert page.locator(".list-pane").bounding_box()["width"] > 380


def test_a_long_answer_uses_the_whole_reader(inbox):
    long = " ".join(["word"] * 600)
    page, _ = inbox([_out("r1", "a", "Long", long)], width=WIDE)
    _rows(page).first.click()
    body = page.locator("#reader .md").bounding_box()
    pane = page.locator(".reader-pane").bounding_box()
    # The reader's own padding is the only space left beside the text.
    assert body["width"] >= pane["width"] - 2 * 24 - 4


# Same screenshot: an inbox check read "1. Important first ... 1. Everything
# else". The model put a blank line between the items, which makes two lists,
# and the second one counted from 1 again because the number was dropped.
def test_a_numbered_list_split_by_a_blank_line_keeps_counting(inbox):
    answer = "Since 3pm:\n\n1. Important first: none.\n\n2. Everything else:\n\n- one\n- two"
    page, _ = inbox([_out("r1", "a", "Inbox check (Gmail)", answer)])
    _rows(page).first.click()
    lists = page.locator("#reader .md ol")
    assert lists.count() == 2
    assert lists.nth(0).get_attribute("start") in (None, "1")
    assert lists.nth(1).get_attribute("start") == "2"


def test_the_start_number_is_only_ever_digits(inbox):
    answer = "7. seventh\n8. eighth"
    page, _ = inbox([_out("r1", "a", "Count", answer)])
    _rows(page).first.click()
    ol = page.locator("#reader .md ol")
    assert ol.get_attribute("start") == "7"
    assert ol.locator("li").count() == 2
