"""A card showed one run, so a glitch and a dead schedule looked the same.

`last_run_status` describes the most recent run and nothing else. A
schedule that failed once this morning and a schedule that has refused
every morning for a month rendered identically: one badge, one word, one
result. The difference between those two is the only thing worth knowing
about a schedule, and the card could not say it.

Migration 071 records every run. This is the half that draws them: one
mark per run, oldest left and newest right the way a status page reads,
and a line that counts the bad ones, because seven marks are a picture
and the sentence is what someone skimming actually reads.

Rendered, not read off the source. A test that greps the file for
"run-mark" passes while the strip renders nothing: these assert the marks
exist in the page, how many there are, which colour each took, and that
the order on screen is the order of the clock.
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


def _run(at, status="completed", ok=True, seconds=12, reason=None):
    return {"at": at, "status": status, "ok": ok, "seconds": seconds,
            "reason": reason}


# Seven mornings of a schedule that has never once done its job. This is
# the live case: a daily email summary whose agent is read-only, asked to
# send mail, refusing every day while the card showed one word.
REFUSED_WEEK = [
    _run(f"2026-11-{20 - n:02d}T00:00:00Z", "refused", False, 9,
         "I cannot send email: this run is read-only.")
    for n in range(7)
]

# Six good mornings and one bad one. A card must not cry about this.
MOSTLY_FINE = (
    [_run("2026-11-20T00:00:00Z", "failed", False, 3, "Timed out.")]
    + [_run(f"2026-11-{19 - n:02d}T00:00:00Z") for n in range(6)]
)

ROWS = [
    # 0: refused all week
    {"id": "1", "name": "Daily email summary",
     "prompt": "Summarise my unread email and send it to me.",
     "cron_expr": "0 8 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": "2026-11-20T00:00:00Z", "last_run_status": "refused",
     "last_result": "I cannot send email: this run is read-only.",
     "last_result_at": "2026-11-20T00:00:09Z",
     "runs": REFUSED_WEEK},
    # 1: one bad run in an otherwise good week
    {"id": "2", "name": "nightly headlines", "prompt": "summarise the news",
     "cron_expr": "0 22 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "discord",
     "delivery_channel_id": "D1",
     "last_run_at": "2026-11-20T00:00:00Z", "last_run_status": "failed",
     "runs": MOSTLY_FINE},
    # 2: a clean week
    {"id": "3", "name": "7pm quote", "prompt": "give me a quote",
     "cron_expr": "0 19 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": "2026-11-20T00:00:00Z", "last_run_status": "completed",
     "runs": [_run(f"2026-11-{20 - n:02d}T11:00:00Z") for n in range(7)]},
    # 3: never run. The server sends [] rather than leaving the key out.
    {"id": "4", "name": "Weekday morning digest",
     "prompt": "Summarize my unread email.", "cron_expr": "0 9 * * 1-5",
     "tz": "Asia/Manila", "enabled": True, "run_once": False,
     "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": None, "last_run_status": None, "runs": []},
    # 4: ran exactly once, and it worked. Its timestamp is in the EXACT
    # shape the server sends, which is Python's isoformat: a numeric offset
    # and microseconds, not the Z the other rows here use. The first real
    # row in the table reads 2026-11-20 13:41:45.179583+00:00, and a
    # timestamp the page cannot parse costs the mark its time silently.
    {"id": "5", "name": "one off report", "prompt": "do the thing",
     "cron_expr": "0 6 * * *", "tz": "Asia/Manila", "enabled": True,
     "run_once": True, "delivery_platform": "", "delivery_channel_id": "",
     "last_run_at": "2026-11-20T13:41:45.179583+00:00",
     "last_run_status": "completed",
     "runs": [_run("2026-11-20T13:41:45.179583+00:00", seconds=7)]},
]


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronruns")
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


def marks(page, i):
    return card(page, i).locator(".run-mark")


def test_a_week_of_runs_draws_a_mark_for_every_run(page):
    assert marks(page, 0).count() == 7


def test_the_marks_run_oldest_to_newest_left_to_right(page):
    """The server sends newest first. Drawn in that order the strip reads
    backwards, which is worse than no strip: it says the week got better."""
    xs = [marks(page, 1).nth(n).bounding_box()["x"]
          for n in range(marks(page, 1).count())]
    assert xs == sorted(xs), "the marks are not laid out left to right"
    # MOSTLY_FINE has its only bad run LAST in clock order, so the bad mark
    # has to be the rightmost one on screen.
    classes = [marks(page, 1).nth(n).get_attribute("class")
               for n in range(marks(page, 1).count())]
    assert "failed" in classes[-1], "the newest run is not on the right"
    assert all("ok" in c for c in classes[:-1])


def test_a_refused_run_keeps_its_own_colour_in_the_strip(page):
    """Refused is neither done nor failed on the badge, for a reason that
    holds here too: the run happened and the job did not."""
    classes = [marks(page, 0).nth(n).get_attribute("class")
               for n in range(marks(page, 0).count())]
    assert all("refused" in c for c in classes)
    assert not any("ok" in c for c in classes)


def test_a_mark_carries_what_that_run_said(page):
    """Per run, not just the last one. The card's problem box already says
    what the latest run said; the strip is where the other six speak."""
    title = marks(page, 0).nth(0).get_attribute("title")
    assert "refused" in title
    assert "read-only" in title


def test_a_schedule_that_never_works_says_so_in_words(page):
    """Seven marks are a picture. Someone skimning a page of cards reads
    the sentence."""
    note = card(page, 0).locator(".sched-runs-note")
    assert note.count() == 1
    assert note.inner_text().strip() == "none of the last 7 did its job"


def test_one_bad_run_in_a_good_week_is_counted_not_dramatised(page):
    note = card(page, 1).locator(".sched-runs-note")
    assert note.count() == 1
    assert note.inner_text().strip() == "1 of the last 7 did not"


def test_a_clean_week_says_nothing_at_all(page):
    """A card that is fine must look fine. Nothing to report is reported
    by the absence of the line, not by a green reassurance."""
    assert card(page, 2).locator(".sched-runs-note").count() == 0
    assert marks(page, 2).count() == 7


def test_a_schedule_that_never_ran_draws_no_strip(page):
    """An empty strip is a card saying something it does not know."""
    assert card(page, 3).locator(".sched-runs").count() == 0
    assert "No runs yet" in card(page, 3).locator(".sched-chips").inner_text()


def test_a_single_run_is_not_labelled_as_a_week(page):
    label = card(page, 4).locator(".sched-runs-label")
    assert label.inner_text().strip() == "1 run so far"
    assert marks(page, 4).count() == 1


def test_a_timestamp_in_the_shape_the_server_actually_sends_is_readable(page):
    """The server sends Python isoformat, a numeric offset with
    microseconds. A timestamp the page cannot parse loses the mark its
    time with no error anywhere, so the one row here in the real shape is
    asserted to have produced a time."""
    title = marks(page, 4).nth(0).get_attribute("title")
    assert "took 7s" in title
    lines = [l for l in title.split("\n") if l.strip()]
    assert len(lines) == 3, f"expected status, when and duration, got {lines}"
    assert "ago" in lines[1] or "just now" in lines[1], \
        f"the timestamp did not become a readable time: {lines[1]!r}"


def test_the_strip_is_read_out_as_a_count_not_as_nine_blank_boxes(page):
    """Nine empty spans are nothing to a screen reader, so the group
    carries the number it is drawing."""
    label = card(page, 0).locator(".sched-runs-marks").get_attribute(
        "aria-label")
    assert label == "0 of the last 7 runs did their job"


def test_the_strip_did_not_make_the_card_grow_a_page(page):
    """The cards were pulled onto fewer lines on purpose (2026-08-17). A
    row of 9px marks must not undo that."""
    h = card(page, 2).bounding_box()["height"]
    assert h < 320, f"a card is {h}px tall; the strip cost too much"
