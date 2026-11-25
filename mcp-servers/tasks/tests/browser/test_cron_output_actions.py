"""Run now and Edit from the answer you are reading in Cron Outputs.

Proposed 2026-11-24 and built 2026-11-25. Reading a cron's answer, the
next thing is usually "run it again" or "change what it asks", and both
meant going back to Cron Jobs and finding the card.

Run now starts that cron and watches for its new answer, so it appears
without a refresh. Edit opens Cron Jobs with that cron in the form, handed
over through localStorage (aiuiCronEditWant), the same way View output
goes the other way.

Run inside a real parent frame, so the message asking the shell to open
the Cron Jobs pane can be seen.
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


def _out(rid, sid, name, result, at):
    return {"id": rid, "schedule_id": sid, "name": name, "at": at,
            "finished_at": at, "status": "completed", "ok": True,
            "result": result, "unread": False}


FIRST = _out("r1", "s-quote", "Daily Quote", "Keep going.",
             "2026-11-24T01:00:00+00:00")
NEWER = _out("r2", "s-quote", "Daily Quote", "Start where you are.",
             "2026-11-25T01:00:00+00:00")

PARENT = """<!doctype html><html><body>
<script>window.__msgs = []; addEventListener('message', e => window.__msgs.push(e.data));</script>
<iframe id="f" src="/cron-output.html" style="width:1200px;height:800px"></iframe>
</body></html>"""


@pytest.fixture()
def reader(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronoutact")
    shutil.copy(STATIC / "cron-output.html", work / "cron-output.html")
    (work / "parent.html").write_text(PARENT, encoding="utf-8")
    state = {"rows": [FIRST], "runs": [], "run_status": 200}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _send(self, data, ctype, status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):                                    # noqa: N802
            if "/schedules/outputs" in self.path:
                self._send(json.dumps(state["rows"]).encode(), "application/json")
            else:
                f = work / (self.path.split("?")[0].lstrip("/") or "parent.html")
                self._send(f.read_bytes() if f.exists() else b"", "text/html")

        def do_POST(self):                                   # noqa: N802
            if self.path.endswith("/run-now"):
                state["runs"].append(self.path)
                if state["run_status"] == 200:
                    # The answer lands a moment later, as a real run's does.
                    threading.Timer(0.3, lambda: state["rows"].insert(0, NEWER)).start()
                self._send(b'{"status": "started"}', "application/json",
                           state["run_status"])
            else:
                self._send(b'{"ok": true}', "application/json")

        def log_message(self, *a):  # noqa: D102
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            httpd.shutdown()
            pytest.skip(f"chromium not installed: {exc}")
        ctx = browser.new_context(viewport={"width": 1300, "height": 900})
        ctx.add_init_script("window.__aiuiWatchMs = 200;")
        page = ctx.new_page()
        page.goto(base + "/parent.html")
        frame = page.frame_locator("#f")
        frame.locator('.row[data-id="r1"]').click()
        frame.locator("[data-reader]").wait_for(timeout=8000)
        yield page, frame, state
        browser.close()
    httpd.shutdown()


def test_the_reader_offers_run_now_and_edit(reader):
    _, frame, _ = reader
    top = frame.locator(".reader-actions")
    assert top.locator("[data-run]").inner_text().strip() == "Run now"
    assert top.locator("[data-edit]").inner_text().strip() == "Edit"
    assert top.locator("[data-toggle-read]").count() == 1


def test_run_now_starts_that_cron_and_its_answer_appears(reader):
    _, frame, state = reader
    frame.locator("[data-run]").click()
    frame.locator("text=Run started").wait_for(timeout=4000)
    assert state["runs"] == ["/api/tasks/schedules/s-quote/run-now"]
    frame.locator('.row[data-id="r2"]').wait_for(timeout=6000)
    frame.locator("text=The new answer is in: Daily Quote.").wait_for(timeout=4000)


def test_run_now_on_a_deleted_cron_says_so(reader):
    _, frame, state = reader
    state["run_status"] = 404
    frame.locator("[data-run]").click()
    frame.locator("text=no longer exists").wait_for(timeout=4000)


def test_edit_hands_the_cron_over_and_opens_cron_jobs(reader):
    page, frame, _ = reader
    frame.locator("[data-edit]").click()
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'aiui:open-pane' "
        "&& m.path === '/cronjobs')", timeout=4000)
    want = json.loads(page.evaluate(
        "localStorage.getItem('aiuiCronEditWant')"))
    assert want["schedule_id"] == "s-quote" and want["at"] > 0
