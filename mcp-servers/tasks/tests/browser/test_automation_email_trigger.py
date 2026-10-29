"""The email trigger on the Automation panel.

The page composes a Gmail query from boxes, and the server composes one from
the same boxes (`email_trigger.compose_query`). Two implementations of one
rule drift, and the way they drift here is silent: a subject with a space,
unquoted, stops being one phrase and the rule starts matching mail the
person never asked about. So the cases below are run through BOTH and
compared, rather than each being checked against a hand-written string.

The filter boxes are also hidden for a webhook rule, because for a webhook
they mean nothing, and a form that asks for things it will ignore is how a
person ends up believing a rule filters when it does not.
"""
import json
import pathlib
import shutil
import threading
import http.server

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

import email_trigger                                        # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"


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
def page(browser, tmp_path):
    """The real agents.html, served over HTTP.

    Over HTTP and not file://, for the reason test_agents_page.py records:
    Chromium's Fetch API refuses a file:// URL, so the page's own calls
    never reach page.route and nothing renders.
    """
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    root = str(tmp_path)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *_a, **_kw):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pg = browser.new_page()
    # Everything the page asks for on load, answered emptily: this file is
    # about the form, not about the lists.
    pg.route("**/api/**", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({})))
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    # The form lives inside the Automation panel, which starts closed.
    pg.locator("#open-automation").click()
    pg.wait_for_selector("#automation-panel", state="visible")
    # The panel is visible before its lists have been fetched, so waiting on
    # the panel alone races the render; the same trap four tests in
    # test_agents_page.py fell into. Wait for the control this file drives.
    pg.wait_for_selector("#auto-trigger", state="visible")
    yield pg
    pg.close()
    server.shutdown()


def _compose(page, **boxes):
    """Fill the boxes, press Add, and return what the page actually POSTed.

    Reading the page's own `emailQuery` would be easier and worth less: it
    lives inside the page's closure, and exposing it on `window` purely to
    be read by a test would prove the function and not the form. What the
    rule ends up being is whatever this request says.
    """
    sent = {}

    def capture(route):
        if route.request.method == "POST":
            sent.update(route.request.post_data_json or {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"id": "a1", "name": "x",
                                       "trigger": boxes.get("trigger", "email"),
                                       "runs": []}))

    page.route("**/api/tasks/automations", capture)
    page.evaluate(
        """(b) => {
            document.getElementById("auto-name").value = "A rule";
            document.getElementById("auto-instructions").value = "Do it.";
            document.getElementById("auto-trigger").value = b.trigger;
            document.getElementById("auto-trigger").dispatchEvent(
                new Event("change"));
            document.getElementById("auto-email-from").value = b.from_address;
            document.getElementById("auto-email-subject").value = b.subject;
            document.getElementById("auto-email-advanced").value = b.advanced;
            document.getElementById("auto-email-unread").checked = b.unread;
        }""",
        {"trigger": boxes.get("trigger", "email"),
         "from_address": boxes.get("from_address", ""),
         "subject": boxes.get("subject", ""),
         "advanced": boxes.get("advanced", ""),
         "unread": bool(boxes.get("unread_only", False))})
    page.locator("#auto-create").click()
    page.wait_for_function("() => !document.getElementById('auto-create').disabled")
    assert sent, "the page sent nothing"
    return sent.get("trigger_query", "")


CASES = [
    {"from_address": "boss@example.com"},
    {"subject": "invoice"},
    {"subject": "sales report"},                    # the space is the point
    {"subject": 'the "big" one'},                   # and the quote
    {"from_address": "boss@example.com", "unread_only": True},
    {"from_address": "a@b.c", "subject": "late invoice", "unread_only": True},
    {"advanced": "from:a@b.c OR from:d@e.f"},
    {"advanced": "from:a@b.c", "from_address": "ignored@example.com"},
    {},                                             # nothing filled in
]


@pytest.mark.parametrize("boxes", CASES)
def test_the_page_and_the_server_compose_the_same_query(page, boxes):
    """One rule, two implementations, compared rather than hand-written.

    The server is the one that counts, since it composes and validates
    again, but a page that shows a different filter from the one that will
    be used is a lie about what the rule does.
    """
    assert _compose(page, **boxes) == email_trigger.compose_query(
        from_address=boxes.get("from_address", ""),
        subject=boxes.get("subject", ""),
        unread_only=boxes.get("unread_only", False),
        advanced=boxes.get("advanced", ""))


def test_a_webhook_rule_sends_no_query(page):
    """The boxes mean nothing for a webhook, so whatever is in them must not
    travel. The server drops it too; this stops the page from showing a
    filter that will be ignored."""
    assert _compose(page, trigger="webhook",
                    from_address="boss@example.com", unread_only=True) == ""


def test_the_filter_boxes_are_hidden_until_the_email_trigger_is_chosen(page):
    """A form that asks for things it will ignore is how somebody ends up
    believing a rule filters when it does not."""
    when = page.locator("#auto-email-when")
    assert when.is_hidden(), "the email boxes show for a webhook rule"
    page.select_option("#auto-trigger", "email")
    assert when.is_visible(), "choosing email did not reveal the boxes"
    page.select_option("#auto-trigger", "webhook")
    assert when.is_hidden(), "going back to a webhook left them showing"


def test_choosing_the_email_trigger_says_it_never_fires_on_old_mail(page):
    """The thing a person most needs to be told before they make the rule:
    adding it does not reply to a year of email."""
    page.select_option("#auto-trigger", "email")
    text = page.locator("#auto-email-when").inner_text().lower()
    assert "since it last looked" in text or "old email" in text
