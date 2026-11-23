"""The Cron Jobs page leads to Cron Outputs, and says how many are unread.

Asked for 2026-11-23: "add also button in cronjob to redirect in here".
Two ways in:

  - View outputs, above the list, carrying the server's unread count in the
    same red as the sidebar;
  - View output on each schedule that has answered, which opens the inbox on
    THAT cron's newest answer.

Inside the shell the page asks the parent to open the pane (aiui:open-pane),
exactly as the sidebar would; the cron to open is handed over through
localStorage, which both pages share. Run inside a real parent frame so the
message can be seen.
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
    {"id": "aaaa", "name": "Inbox check (Gmail)", "prompt": "check my inbox",
     "cron_expr": "0 9 * * 1-5", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "discord",
     "delivery_channel_id": None, "last_run_at": "2026-11-23T13:39:00Z",
     "last_run_status": "completed", "last_result": "Nothing new.",
     "last_result_at": "2026-11-23T13:39:44Z", "runs": []},
    {"id": "bbbb", "name": "Never ran yet", "prompt": "x",
     "cron_expr": "0 9 * * 1-5", "tz": "Asia/Manila", "enabled": True,
     "run_once": False, "delivery_platform": "discord",
     "delivery_channel_id": None, "last_run_at": None,
     "last_run_status": None, "last_result": None, "last_result_at": None,
     "runs": []},
]

PARENT = """<!doctype html><html><body>
<script>window.__msgs = []; addEventListener('message', e => window.__msgs.push(e.data));</script>
<iframe id="f" src="/cron.html" style="width:1200px;height:900px"></iframe>
</body></html>"""


@pytest.fixture()
def framed(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronpage")
    shutil.copy(STATIC / "cron.html", work / "cron.html")
    (work / "parent.html").write_text(PARENT, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            if "/schedules/outputs/unread" in self.path:
                data, ctype = json.dumps({"count": 2, "items": []}).encode(), "application/json"
            elif "/api/tasks/schedules" in self.path:
                data, ctype = json.dumps(ROWS).encode(), "application/json"
            elif "/api/" in self.path:
                data, ctype = b"[]", "application/json"
            else:
                name = self.path.split("?")[0].lstrip("/") or "parent.html"
                f = work / name
                data = f.read_bytes() if f.exists() else b""
                ctype = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.goto(base + "/parent.html")
        frame = page.frame_locator("#f")
        frame.locator(".sched-card, [data-act='run']").first.wait_for(timeout=8000)
        yield page, frame
        browser.close()
    httpd.shutdown()


def test_view_outputs_carries_the_unread_count(framed):
    _, frame = framed
    count = frame.locator("#outputs-count")
    count.wait_for(state="visible", timeout=4000)
    assert count.inner_text().strip() == "2"


def test_view_outputs_asks_the_shell_to_open_the_inbox(framed):
    page, frame = framed
    frame.locator("#outputs-btn").click()
    page.wait_for_function("window.__msgs.length > 0", timeout=3000)
    assert page.evaluate("window.__msgs[0]") == {
        "type": "aiui:open-pane", "path": "/cronjobs/output"}


def test_a_schedule_that_answered_has_view_output_and_one_that_did_not_has_none(framed):
    _, frame = framed
    assert frame.locator('[data-act="outputs"]').count() == 1


def test_view_output_on_a_card_opens_the_inbox_on_that_cron(framed):
    page, frame = framed
    frame.locator('[data-act="outputs"]').click()
    page.wait_for_function("window.__msgs.length > 0", timeout=3000)
    assert page.evaluate("window.__msgs[0].path") == "/cronjobs/output"
    want = page.evaluate("JSON.parse(localStorage.getItem('aiuiCronOutputWant'))")
    assert want["schedule_id"] == "aaaa"
