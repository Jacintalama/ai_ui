"""Cron Jobs: "Email me the answer", and a warning that names the real reason.

2026-11-26. A job asked to email its summary was refused every morning: it
runs read only unless its agent may act on its own everywhere. Emailing
yourself the answer is now delivery the platform does (cron_email), so the
form offers it as a box to tick, and the warning under Tool access points at
it instead of at Full access, which on its own was not even enough: 8 of the
10 real agents are set to Ask or Read only, and a schedule never widens that.

Against a tiny server that answers the routes the page calls and records
every POST and PATCH.
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

AGENTS = {"items": [
    {"id": "agent-inbox-triage-0002", "name": "Mia", "meta": {"access": "ask"}},
    {"id": "agent-rex-a101", "name": "Rex", "meta": {"access": "all"}},
    {"id": "agent-old-0003", "name": "Old", "meta": {}},
], "total": 3}


def _row(sid, name, prompt, agent, mode=None, email_me=False):
    return {"id": sid, "name": name, "prompt": prompt, "cron_expr": "0 16 * * 5",
            "tz": "Asia/Manila", "enabled": True, "run_once": False,
            "delivery_platform": "discord", "delivery_channel_id": None,
            "last_run_at": None, "last_run_status": None,
            "last_result": None, "last_result_at": None, "runs": [],
            "notify": True, "kind": "agent", "agent_id": agent,
            "tool_mode": mode, "email_me": email_me}


@pytest.fixture()
def cron(tmp_path_factory):
    work = tmp_path_factory.mktemp("cronemail")
    shutil.copy(STATIC / "cron.html", work / "cron.html")
    state = {
        "rows": [
            _row("aaaa", "Weekly digest", "Summarize this week's unread Gmail.",
                 "agent-inbox-triage-0002", email_me=True),
            _row("bbbb", "Inbox check", "Check my Gmail inbox.",
                 "agent-inbox-triage-0002"),
        ],
        "patches": [], "posts": [], "post_status": 201,
        "post_detail": "To email you the answer, connect Gmail first: open "
                       "Connections, connect Gmail, then turn this on.",
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
            for r in state["rows"]:
                if r["id"] == sid:
                    r.update(body)
            self._json({"status": "updated"})

        def do_POST(self):                                   # noqa: N802
            state["posts"].append((self.path, self._body()))
            if state["post_status"] != 201:
                self._json({"detail": state["post_detail"]}, state["post_status"])
                return
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
        page.locator('#run-as option[value="agent-rex-a101"]').wait_for(
            state="attached", timeout=8000)
        yield page, state
        browser.close()
    httpd.shutdown()


def _card(page, name):
    return page.locator(".sched-card", has_text=name)


def _note(page):
    return page.locator("#tool-mismatch")


def test_the_form_offers_email_me_the_answer(cron):
    page, _ = cron
    box = page.locator("#email-me")
    assert box.is_visible() and not box.is_checked()
    label = page.locator("label[for='email-me']").inner_text()
    assert "Email me the answer" in label


def test_creating_with_the_box_ticked_asks_for_email(cron):
    page, state = cron
    page.locator("#prompt").fill("Summarize this week's unread Gmail.")
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#email-me").check()
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Schedule created").wait_for(timeout=4000)
    assert state["posts"][0][1]["email_me"] is True


def test_creating_without_it_does_not(cron):
    page, state = cron
    page.locator("#prompt").fill("Check my Gmail inbox.")
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Schedule created").wait_for(timeout=4000)
    assert state["posts"][0][1].get("email_me") is False


def test_a_refused_create_shows_the_servers_sentence_not_json(cron):
    page, state = cron
    state["post_status"] = 400
    page.locator("#prompt").fill("Summarize this week's unread Gmail.")
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#email-me").check()
    page.locator("#create-btn").click()
    err = page.locator("#form-error")
    err.wait_for(state="visible", timeout=4000)
    text = err.inner_text()
    assert "connect Gmail first" in text
    assert '{"detail"' not in text


def test_a_card_says_when_its_answer_is_emailed(cron):
    page, _ = cron
    assert _card(page, "Weekly digest").locator(".sched-emailed").count() == 1
    assert "Emailed to you" in _card(page, "Weekly digest").inner_text()
    assert _card(page, "Inbox check").locator(".sched-emailed").count() == 0
    # Emailed IS its delivery: "No delivery" beside it would contradict it.
    assert "No delivery" not in _card(page, "Weekly digest").inner_text()
    assert "No delivery" in _card(page, "Inbox check").inner_text()


def test_edit_shows_the_box_as_it_is_and_saves_only_that_change(cron):
    page, state = cron
    _card(page, "Weekly digest").locator('[data-act="edit"]').click()
    assert page.locator("#email-me").is_checked()
    page.locator("#email-me").uncheck()
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Changes saved").wait_for(timeout=4000)
    assert state["patches"] == [("aaaa", {"email_me": False})]


def test_turning_it_on_in_an_edit(cron):
    page, state = cron
    _card(page, "Inbox check").locator('[data-act="edit"]').click()
    assert not page.locator("#email-me").is_checked()
    page.locator("#email-me").check()
    page.locator("#create-btn").click()
    page.locator(".toast", has_text="Changes saved").wait_for(timeout=4000)
    assert state["patches"] == [("bbbb", {"email_me": True})]


# --- the warning ---------------------------------------------------------------

def test_email_me_in_the_prompt_points_at_the_box_not_at_full_access(cron):
    page, _ = cron
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#prompt").fill("Every Friday email me a summary of my unread mail.")
    note = _note(page)
    note.wait_for(state="visible", timeout=2000)
    assert "Email me the answer" in note.inner_text()
    assert "Full access" not in note.inner_text()
    page.locator("#email-me").check()
    note.wait_for(state="hidden", timeout=2000)


def test_another_action_names_an_agent_that_will_not_act_on_a_schedule(cron):
    page, _ = cron
    page.locator("#run-as").select_option("agent-inbox-triage-0002")
    page.locator("#tool-mode").select_option("full")
    page.locator("#prompt").fill("Post the sales numbers to the team channel.")
    note = _note(page)
    note.wait_for(state="visible", timeout=2000)
    text = note.inner_text()
    assert "Mia" in text and "AI Agents" in text


def test_an_agent_set_to_act_on_its_own_with_full_access_has_no_warning(cron):
    page, _ = cron
    page.locator("#run-as").select_option("agent-rex-a101")
    page.locator("#tool-mode").select_option("full")
    page.locator("#prompt").fill("Post the sales numbers to the team channel.")
    page.wait_for_timeout(200)
    assert _note(page).is_hidden()


def test_read_only_still_says_it_will_not_act(cron):
    page, _ = cron
    page.locator("#run-as").select_option("agent-rex-a101")
    page.locator("#prompt").fill("Post the sales numbers to the team channel.")
    note = _note(page)
    note.wait_for(state="visible", timeout=2000)
    assert "Read only" in note.inner_text()
