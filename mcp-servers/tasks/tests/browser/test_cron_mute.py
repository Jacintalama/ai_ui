"""Mute on a Cron Jobs card: its outputs stop ringing the red number.

Asked for 2026-11-24, after the number said 5 and none of the 5 needed
anything. Muting PATCHes notify=false (migration 073); the server also reads
what that cron already had unread, and the page tells the shell so the
sidebar number drops at once. A muted card says so, and offers Unmute.

Run inside a real parent frame, so the message to the shell can be seen,
against a tiny server that answers the routes the page calls and records
the PATCH.
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


def _row(sid, name, notify):
    return {"id": sid, "name": name, "prompt": "check my inbox",
            "cron_expr": "0 9 * * 1-5", "tz": "Asia/Manila", "enabled": True,
            "run_once": False, "delivery_platform": "discord",
            "delivery_channel_id": None, "last_run_at": None,
            "last_run_status": None, "last_result": None,
            "last_result_at": None, "runs": [], "notify": notify}


PARENT = """<!doctype html><html><body>
<script>window.__msgs = []; addEventListener('message', e => window.__msgs.push(e.data));</script>
<iframe id="f" src="/cron.html" style="width:1200px;height:900px"></iframe>
</body></html>"""


@pytest.fixture()
def framed(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronmute")
    shutil.copy(STATIC / "cron.html", work / "cron.html")
    (work / "parent.html").write_text(PARENT, encoding="utf-8")
    state = {"rows": [_row("aaaa", "Inbox check", True),
                      _row("bbbb", "Daily Quote", False)],
             "patches": []}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _send(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):                                    # noqa: N802
            if "/schedules/outputs/unread" in self.path:
                self._send(json.dumps({"count": 0, "items": []}).encode(),
                           "application/json")
            elif "/api/tasks/schedules" in self.path:
                self._send(json.dumps(state["rows"]).encode(), "application/json")
            elif "/api/" in self.path:
                self._send(b"[]", "application/json")
            else:
                name = self.path.split("?")[0].lstrip("/") or "parent.html"
                f = work / name
                self._send(f.read_bytes() if f.exists() else b"", "text/html")

        def do_PATCH(self):                                  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            sid = self.path.rstrip("/").rsplit("/", 1)[-1]
            state["patches"].append((sid, body))
            for r in state["rows"]:
                if r["id"] == sid and "notify" in body:
                    r["notify"] = body["notify"]
            self._send(b'{"status": "updated"}', "application/json")

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
        frame.locator('[data-act="mute"]').first.wait_for(timeout=8000)
        yield page, frame, state
        browser.close()
    httpd.shutdown()


def _card(frame, name):
    return frame.locator(".sched-card", has_text=name)


def test_an_ordinary_cron_offers_mute_and_a_muted_one_says_so(framed):
    _, frame, _ = framed
    loud, quiet = _card(frame, "Inbox check"), _card(frame, "Daily Quote")
    assert loud.locator('[data-act="mute"]').inner_text().strip() == "Mute"
    assert loud.locator('[data-act="mute"]').get_attribute("aria-pressed") == "false"
    assert loud.locator(".sched-muted").count() == 0
    assert quiet.locator('[data-act="mute"]').inner_text().strip() == "Unmute"
    assert quiet.locator('[data-act="mute"]').get_attribute("aria-pressed") == "true"
    assert quiet.locator(".sched-muted").inner_text().strip() == "Muted"


def test_mute_sends_notify_false_and_tells_the_shell(framed):
    page, frame, state = framed
    _card(frame, "Inbox check").locator('[data-act="mute"]').click()
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'aiui:cron-outputs-changed')",
        timeout=4000)
    assert state["patches"] == [("aaaa", {"notify": False})]
    _card(frame, "Inbox check").locator(".sched-muted").wait_for(timeout=4000)
    assert _card(frame, "Inbox check").locator(
        '[data-act="mute"]').inner_text().strip() == "Unmute"


def test_unmute_sends_notify_true(framed):
    page, frame, state = framed
    _card(frame, "Daily Quote").locator('[data-act="mute"]').click()
    page.wait_for_function("window.__msgs.length > 0", timeout=4000)
    assert state["patches"] == [("bbbb", {"notify": True})]
