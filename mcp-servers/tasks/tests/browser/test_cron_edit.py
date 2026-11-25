"""Edit on a Cron Jobs card: change a schedule without making it again.

Asked for 2026-11-24 ("why cant edit this cron?? please add edit"). Before
this a card could be run, disabled, muted or deleted, and changing a word of
its prompt meant deleting it and losing its run history and outputs.

Edit loads the schedule into the form on the left, which becomes "Edit
schedule" with Save changes and Cancel. Save PATCHes only what changed, so
an unchanged time is never re-checked against rules it predates.

Against a tiny server that answers the routes the page calls and records
every PATCH and POST.
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

AGENTS = {"items": [{"id": "agent-research-assistant-0001", "name": "Ada"},
                    {"id": "agent-inbox-triage-0002", "name": "Mia"}],
          "total": 2}


def _row(sid, name, cron, prompt, agent, mode, tz="Asia/Manila"):
    return {"id": sid, "name": name, "prompt": prompt, "cron_expr": cron,
            "tz": tz, "enabled": True, "run_once": False,
            "delivery_platform": "discord", "delivery_channel_id": None,
            "last_run_at": None, "last_run_status": None,
            "last_result": None, "last_result_at": None, "runs": [],
            "notify": True, "kind": "agent", "agent_id": agent,
            "tool_mode": mode}


@pytest.fixture()
def cron(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronedit")
    shutil.copy(STATIC / "cron.html", work / "cron.html")
    state = {
        "rows": [
            _row("aaaa", "Morning brief", "30 7 * * 1-5",
                 "Read my board and say what is due.",
                 "agent-research-assistant-0001", None),
            _row("bbbb", "Inbox check", "0 9,15 * * 1-5",
                 "Check my Gmail inbox.", "agent-inbox-triage-0002", "full"),
            _row("cccc", "Daily Quote", "0 0 * * *", "Send one quote.",
                 "agent-inbox-triage-0002", "read_only", tz="UTC"),
        ],
        "patches": [], "posts": [], "patch_status": 200,
    }

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _send(self, data, ctype, status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, status=200):
            self._send(json.dumps(obj).encode(), "application/json", status)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):                                    # noqa: N802
            if "/schedules/outputs/unread" in self.path:
                self._json({"count": 0, "items": []})
            elif "/api/tasks/schedules" in self.path:
                self._json(state["rows"])
            elif "/api/v1/models/list" in self.path:
                self._json(AGENTS)
            elif "/api/" in self.path:
                self._json([])
            else:
                f = work / (self.path.split("?")[0].lstrip("/") or "cron.html")
                self._send(f.read_bytes() if f.exists() else b"", "text/html")

        def do_PATCH(self):                                  # noqa: N802
            body = self._body()
            sid = self.path.rstrip("/").rsplit("/", 1)[-1]
            state["patches"].append((sid, body))
            if state["patch_status"] != 200:
                self._json({"detail": "tool_mode must be 'read_only' or 'full'"},
                           state["patch_status"])
                return
            for r in state["rows"]:
                if r["id"] == sid:
                    r.update(body)
            self._json({"status": "updated"})

        def do_POST(self):                                   # noqa: N802
            state["posts"].append((self.path, self._body()))
            self._json({"id": "new"}, 201)

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
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000},
                                  timezone_id="Asia/Manila")
        page = ctx.new_page()
        page.goto(base + "/cron.html")
        page.locator('[data-act="edit"]').first.wait_for(timeout=8000)
        page.locator('#run-as option[value="agent-inbox-triage-0002"]').wait_for(
            state="attached", timeout=8000)
        yield page, state
        browser.close()
    httpd.shutdown()


def _card(page, name):
    return page.locator(".sched-card", has_text=name)


def _edit(page, name):
    _card(page, name).locator('[data-act="edit"]').click()


def test_every_card_has_an_edit_button(cron):
    page, _ = cron
    assert page.locator(".sched-card").count() == 3
    assert page.locator('.sched-card [data-act="edit"]').count() == 3
    assert _card(page, "Morning brief").locator(
        '[data-act="edit"]').inner_text().strip() == "Edit"


def test_edit_fills_the_form_with_that_schedule(cron):
    page, _ = cron
    _edit(page, "Morning brief")
    assert page.locator("#form-title").inner_text().strip() == "Edit schedule"
    assert page.locator("#name").input_value() == "Morning brief"
    assert page.locator("#freq").input_value() == "weekday"
    assert page.locator("#time").input_value() == "07:30"
    assert page.locator("#prompt").input_value() == "Read my board and say what is due."
    assert page.locator("#run-as").input_value() == "agent-research-assistant-0001"
    # No tool_mode stored means read only, and the form must say so.
    assert page.locator("#tool-mode").input_value() == "read_only"
    assert page.locator("#create-btn").inner_text().strip() == "Save changes"
    assert page.locator("#cancel-edit").is_visible()
    card = _card(page, "Morning brief")
    assert "is-editing" in (card.get_attribute("class") or "")
    assert card.locator('[data-act="edit"]').get_attribute("aria-pressed") == "true"


def test_a_time_the_picker_cannot_show_opens_as_custom(cron):
    page, _ = cron
    _edit(page, "Inbox check")
    assert page.locator("#freq").input_value() == "custom"
    assert page.locator("#cron_expr").input_value() == "0 9,15 * * 1-5"
    assert page.locator("#cron_expr").is_visible()
    assert page.locator("#tool-mode").input_value() == "full"


def test_save_sends_only_what_changed(cron):
    page, state = cron
    _edit(page, "Morning brief")
    page.locator("#prompt").fill("Read my board and GitHub, say what is due.")
    page.locator("#tool-mode").select_option("full")
    page.locator("#create-btn").click()
    page.wait_for_function(
        "document.getElementById('form-title').textContent.trim() === 'New schedule'",
        timeout=4000)
    assert state["patches"] == [("aaaa", {
        "prompt": "Read my board and GitHub, say what is due.",
        "tool_mode": "full"})]
    assert state["posts"] == [], "an edit must never make a second schedule"
    assert page.locator("#name").input_value() == ""
    assert page.locator("#create-btn").inner_text().strip() == "Create schedule"
    assert not page.locator("#cancel-edit").is_visible()


def test_changing_the_time_and_the_agent_sends_both(cron):
    page, state = cron
    _edit(page, "Morning brief")
    page.locator("#time").fill("08:15")
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#create-btn").click()
    page.wait_for_function("document.getElementById('create-btn').textContent"
                           ".trim() === 'Create schedule'", timeout=4000)
    assert state["patches"] == [("aaaa", {
        "cron_expr": "15 8 * * 1-5",
        "agent_id": "agent-inbox-triage-0002"})]


def test_cancel_puts_the_form_back_and_sends_nothing(cron):
    page, state = cron
    _edit(page, "Inbox check")
    page.locator("#cancel-edit").click()
    assert page.locator("#form-title").inner_text().strip() == "New schedule"
    assert page.locator("#name").input_value() == ""
    assert page.locator("#prompt").input_value() == ""
    assert page.locator("#freq").input_value() == "daily"
    assert page.locator(".sched-card.is-editing").count() == 0
    assert state["patches"] == [] and state["posts"] == []


def test_saving_with_nothing_changed_sends_nothing(cron):
    page, state = cron
    _edit(page, "Inbox check")
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Nothing changed").wait_for(timeout=4000)
    assert state["patches"] == [] and state["posts"] == []
    assert page.locator("#form-title").inner_text().strip() == "New schedule"


def test_a_refused_save_says_why_and_keeps_the_edit_open(cron):
    page, state = cron
    state["patch_status"] = 400
    _edit(page, "Morning brief")
    page.locator("#name").fill("Morning brief v2")
    page.locator("#create-btn").click()
    page.locator("#form-error").wait_for(state="visible", timeout=4000)
    assert "tool_mode must be" in page.locator("#form-error").inner_text()
    assert page.locator("#form-title").inner_text().strip() == "Edit schedule"
    assert page.locator("#name").input_value() == "Morning brief v2"


def test_the_time_says_its_zone_when_it_is_not_yours(cron):
    """Daily Quote runs in UTC. 12:00 AM there is 8:00 AM in Manila, so the
    form must not let a person read it as their own midnight."""
    page, _ = cron
    _edit(page, "Daily Quote")
    assert page.locator("#time").input_value() == "00:00"
    assert "UTC" in page.locator("#time-hint").inner_text()
    _edit(page, "Morning brief")
    assert "UTC" not in page.locator("#time-hint").inner_text()


def test_editing_another_card_moves_the_edit_to_it(cron):
    page, _ = cron
    _edit(page, "Morning brief")
    _edit(page, "Inbox check")
    assert page.locator("#name").input_value() == "Inbox check"
    assert page.locator(".sched-card.is-editing").count() == 1
    assert "is-editing" in (_card(page, "Inbox check").get_attribute("class") or "")


def test_a_new_schedule_may_leave_the_name_empty(cron):
    """The server names it from the prompt (schedule_names, 2026-11-25)."""
    page, state = cron
    assert page.locator("#name-hint").is_visible()
    page.locator("#prompt").fill("give me a motivational quote")
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Schedule created").wait_for(timeout=4000)
    assert len(state["posts"]) == 1
    assert state["posts"][0][1]["name"] == ""
    assert page.locator("#form-error").is_hidden()


def test_an_edit_still_needs_a_name(cron):
    page, state = cron
    _edit(page, "Morning brief")
    assert not page.locator("#name-hint").is_visible()
    page.locator("#name").fill("")
    page.locator("#create-btn").click()
    page.locator("#form-error").wait_for(state="visible", timeout=4000)
    assert "name is required" in page.locator("#form-error").inner_text()
    assert state["patches"] == []
