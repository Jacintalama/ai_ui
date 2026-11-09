"""A rule that has stopped looking says so, whatever it watches.

Measured on production 2026-11-09. Ralph's only automation, "Watch Today
(first live test)", has been dead since the day he made it, 3 November,
and nothing on the page said so:

    trigger      trello
    enabled      True
    last run     2026-11-03 13:23, once, then never again
    checked_at   2026-11-09 09:53:37      <- it looked a minute ago
    last_error   "Your Trello connection was rejected. Reconnect..."

The poller is not broken. It looks every minute, it knows exactly why it
cannot read the list, and it writes that reason down in a sentence meant
for a person. `_cursors_for` reads BOTH cursor tables and
`list_automations` attaches checked_at and last_error for TRIGGER_EMAIL
and TRIGGER_TRELLO alike, deliberately, with a comment dated 2026-11-03
for the Trello half.

The page then drops it on the floor, because the guard that renders the
line is `if (byEmail && ...)`, and `byEmail` is `a.trigger === "email"`.
So the sentence is computed, stored, sent over the wire and never shown,
and a rule six days dead looks exactly like a rule nobody has triggered.
Which is the precise failure the comment above that guard says it exists
to prevent.

These render the real agents.html in a real browser, because the bug is
one word in a condition and a structural test that greps the file would
pass either way.
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

TRELLO_ERROR = "Your Trello connection was rejected. Reconnect it."
EMAIL_ERROR = "Your Google connection was rejected. Reconnect it."


def _rule(**over):
    """One automation as list_automations really sends it."""
    row = {
        "id": "8b180149-b3fd-4571-9281-a0ad29640873",
        "name": "Watch Today (first live test)",
        "instructions": "Tell me about the card.",
        "agent_id": "agent-research-assistant-0001",
        "agent_name": "Ada",
        "agent_missing": False,
        "trigger": "trello",
        "trigger_query": "6ae472c14cc1b6e65b622e17",
        "deliver_to": "chat",
        "run_count": 1,
        "enabled": True,
        "hook_token": "hk_x",
        "hook_url": "https://example.test/api/tasks/hooks/hk_x",
        "runs": [],
        "checked_at": "2026-11-09T09:53:37+00:00",
        "last_error": TRELLO_ERROR,
    }
    row.update(over)
    return row


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip("chromium not installed: %s" % exc)
        yield b
        b.close()


@pytest.fixture
def open_panel(browser, tmp_path):
    """Open the Automation panel with these rules listed, and hand back the
    panel's text. Served over HTTP, not file://, because Chromium's Fetch
    refuses file:// and then nothing renders at all."""
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    root = str(tmp_path)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *_a, **_kw):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    made = []

    def go(rules):
        pg = browser.new_page()
        made.append(pg)
        # Everything else answered emptily; this file is about one line.
        pg.route("**/api/**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({})))
        # Registered after the catch-all, so it wins.
        pg.route("**/api/tasks/automations", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"automations": rules})))
        pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
        pg.locator("#open-automation").click()
        pg.wait_for_selector("#automation-panel", state="visible")
        # The panel is visible before its lists are fetched, so waiting on
        # the panel alone races the render.
        pg.wait_for_selector("#automations-list .auto-rule-name",
                             state="visible")
        return pg.locator("#automations-list").inner_text()

    yield go
    for pg in made:
        pg.close()
    server.shutdown()


def test_a_trello_rule_that_cannot_look_says_why(open_panel):
    """The whole point. Six days dead and the page said nothing."""
    shown = open_panel([_rule()])
    assert "Not looking" in shown, shown
    assert TRELLO_ERROR in shown, shown


def test_a_trello_rule_that_is_looking_says_when(open_panel):
    """The other half: a healthy polled rule shows it is still looking, so
    silence means something."""
    shown = open_panel([_rule(last_error="")])
    assert "Last looked" in shown, shown


def test_an_email_rule_still_says_why(open_panel):
    """Unchanged. This is what worked before and must keep working."""
    shown = open_panel([_rule(trigger="email",
                              trigger_query="from:boss@example.com",
                              last_error=EMAIL_ERROR)])
    assert "Not looking" in shown, shown
    assert EMAIL_ERROR in shown, shown


def test_a_webhook_rule_says_nothing_about_looking(open_panel):
    """Nothing polls a webhook rule, so it never looked and saying it did
    would be a lie. The server sends no cursor for one."""
    shown = open_panel([_rule(trigger="webhook", trigger_query="",
                              checked_at=None, last_error="")])
    assert "Not looking" not in shown, shown
    assert "Last looked" not in shown, shown


def test_the_error_is_what_marks_it_rather_than_the_trigger(open_panel):
    """Both at once, so one rule's line cannot be mistaken for the other's
    and a fix that merely swaps which trigger is special is caught."""
    shown = open_panel([
        _rule(id="a1", name="Trello one"),
        _rule(id="a2", name="Email one", trigger="email",
              trigger_query="from:x@y.z", last_error=""),
    ])
    assert TRELLO_ERROR in shown, shown
    assert shown.count("Not looking") == 1, shown
    assert "Last looked" in shown, shown
