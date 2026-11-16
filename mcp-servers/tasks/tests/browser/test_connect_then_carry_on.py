"""Connect from the chat, then the chat carries on (2026-11-17).

Lukas, 2026-11-16: "say we have automation, so we should connect n8n and
pop up the connect field and then they connect it and then it starts using
it." The real section of integrations-ui.js, cut out by its section markers,
runs on a page served from a routed origin, so postMessage origins and
sources, fetches and timers are all real. The login the button opens is a
real frame: it goes to the vendor, then to a callback page on our origin
that posts to the page the way the real callbacks post to their opener.
The message box is a contenteditable that draws its Send button only once
it holds text, as Open WebUI's does (checked on the live site 2026-11-17:
`#chat-input` is TipTap, `#send-message-button` appears with text).

Waits for a message-driven carry-on are shorter than the 3 s poll, so they
prove the message path, not the poll (review 2026-11-17).

Design: docs/plans/2026-11-17-triage-connect-and-continue-design.md.
"""
import json
import pathlib
from urllib.parse import quote, unquote

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

UI_JS = pathlib.Path(__file__).resolve().parents[3] / "gdrive" / "integrations-ui.js"
ORIGIN = "http://aiui.test"
VENDOR = "https://vendor.example/authorize"
SAID = "I've connected %s. Please go ahead with what I asked."
LABELS = {"clickup": "ClickUp", "n8n": "n8n", "trello": "Trello",
          "github": "GitHub", "jira": "Jira"}
OAUTH_OK = {"aiuiOauth": True, "ok": True}


def _section():
    src = UI_JS.read_text(encoding="utf-8")
    start = src.index("  // ===== The assistant's connect links =====")
    end = src.index("  function wireAiuiConnectLinks()")
    # The real one-message helper the section leans on, which lives
    # further down the file.
    at = src.index("  function aiuiMessageRowOf(")
    helper = src[at:src.index("\n  }\n", at) + 5]
    return src[start:end] + "\n" + helper


PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="message-0"><div class="chat-user">save my leads somewhere</div></div>
<div id="message-1"><div class="chat-assistant"><p>Connect it.</p><p>%(links)s</p></div></div>
<div id="chat-input" contenteditable="true"></div><div id="send-slot"></div>
<script>
  window.__sent = []; window.__frames = []; window.__panels = 0; window.__busy = false;
  var GMAIL_API = '/gmail', GDRIVE_API = '/gdrive', CALENDAR_API = '/calendar';
  function getEffectiveEmail() { return 'person@example.com'; }
  window.aiuiOpenConnections = function () { window.__panels++; };
  window.open = function (u) {
    var f = document.createElement('iframe');
    f.name = 'login' + window.__frames.length;
    document.body.appendChild(f);
    if (u) f.src = u;
    window.__frames.push(f);
    return f.contentWindow;
  };
  var box = document.getElementById('chat-input');
  box.addEventListener('input', function () {
    var s = document.getElementById('send-message-button');
    if (box.innerText.trim() && !s && !window.__busy) {
      s = document.createElement('button'); s.id = 'send-message-button';
      s.onclick = function () {
        window.__sent.push(box.innerText.trim()); box.innerHTML = ''; s.remove();
      };
      document.getElementById('send-slot').appendChild(s);
    }
  });
</script>
<script>%(section)s
window.__wire = wireAiuiConnectLink;</script>
<script>document.querySelectorAll('a').forEach(function (a) { window.__wire(a); });</script>
</body></html>"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


class Site:
    """One chat page and what the service says about the person's apps."""

    def __init__(self, browser, links, connected, oauth=True):
        self.connected = dict(connected)
        self.oauth = oauth
        self.vendor_hits = []
        self.page = browser.new_page()
        self.page.route(ORIGIN + "/**", self._serve)
        self.page.route(VENDOR + "**", self._vendor)
        self.html = PAGE % {"links": " ".join(
            '<a href="#aiui-connect:%s">Connect %s</a>' % pair for pair in links),
            "section": _section()}
        self.page.goto(ORIGIN + "/c/abc")
        self.page.wait_for_timeout(300)   # the connections list is read once

    def _vendor(self, route):
        self.vendor_hits.append(route.request.url)
        route.fulfill(status=200, content_type="text/html", body="<p>log in</p>")

    def _serve(self, route):
        path = route.request.url[len(ORIGIN):].split("?")[0]
        query = route.request.url.split("?", 1)[1] if "?" in route.request.url else ""
        if path == "/api/tasks/connections":
            body = {"connections": [
                {"provider": p, "label": LABELS.get(p, p), "connected": c,
                 "oauth": self.oauth}
                for p, c in self.connected.items()
                if p not in ("gmail", "gdrive", "calendar")]}
        elif path.endswith("/oauth/start"):
            body = {"url": VENDOR}
        elif path in ("/gmail/auth/status", "/gdrive/auth/status",
                      "/calendar/auth/google/status"):
            body = {"connected": self.connected.get(path.split("/")[1], False)}
        elif path == "/callback":
            msg = json.loads(unquote(query[2:]))
            return route.fulfill(status=200, content_type="text/html", body=(
                "<script>parent.postMessage(%s, '*')</script>" % json.dumps(msg)))
        elif path.startswith(("/gmail/auth/google/link", "/calendar/auth/google/link",
                              "/gdrive/auth/google/link")):
            return route.fulfill(status=200, content_type="text/html",
                                 body="<p>google</p>")
        else:
            return route.fulfill(status=200, content_type="text/html", body=self.html)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    def click(self, n=0):
        self.page.locator(".aiui-connect-inline > button").nth(n).click()
        self.page.wait_for_timeout(400)

    def callback(self, message, frame=0):
        """The login in the frame the button opened lands on our callback."""
        self.page.evaluate(
            "([i, u]) => { window.__frames[i].src = u; }",
            [frame, ORIGIN + "/callback?m=" + quote(json.dumps(message))])

    def sent(self, ms=1500, n=1):
        try:
            self.page.wait_for_function(
                "n => window.__sent.length >= n", arg=n, timeout=ms)
        except Exception:
            pass
        return self.page.evaluate("() => window.__sent")

    def button(self, n=0):
        return self.page.locator(".aiui-connect-inline > button").nth(n).inner_text()


@pytest.fixture()
def site(browser):
    made = []

    def make(*a, **k):
        s = Site(browser, *a, **k)
        made.append(s)
        return s
    yield make
    for s in made:
        s.page.close()


# --- the connect field pops up -------------------------------------------------

def test_an_app_that_can_log_in_here_opens_its_own_login(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.page.wait_for_timeout(500)
    assert s.vendor_hits and s.vendor_hits[0].startswith(VENDOR)
    assert s.page.evaluate("() => window.__panels") == 0


def test_an_app_with_a_key_to_paste_opens_the_panel(site):
    s = site([("n8n", "n8n")], {"n8n": False}, oauth=False)
    s.click()
    assert s.page.evaluate("() => window.__frames.length") == 0
    assert s.page.evaluate("() => window.__panels") == 1


def test_a_task_tracker_opens_the_panel_not_one_trackers_login(site):
    s = site([("tracker", "a task tracker")],
             {"trello": False, "github": False, "clickup": False, "jira": False})
    s.click()
    assert s.page.evaluate("() => window.__frames.length") == 0
    assert s.page.evaluate("() => window.__panels") == 1


# --- then it carries on ----------------------------------------------------------

def test_when_the_login_finishes_the_chat_carries_on(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    assert s.sent() == [SAID % "ClickUp"]
    assert s.button() == "✓ ClickUp connected"


def test_a_key_pasted_in_the_panel_is_noticed_by_the_poll(site):
    s = site([("n8n", "n8n")], {"n8n": False}, oauth=False)
    s.click()
    s.connected["n8n"] = True          # saved in the panel: no message at all
    assert s.sent(ms=9000) == [SAID % "n8n"]


def test_whichever_tracker_they_connect_is_the_one_named(site):
    s = site([("tracker", "a task tracker")],
             {"trello": False, "github": False, "clickup": False, "jira": False})
    s.click()
    s.connected["jira"] = True
    assert s.sent(ms=9000) == [SAID % "Jira"]


def test_a_google_app_carries_on_after_its_own_callback(site):
    s = site([("gmail", "Gmail")], {"gmail": False})
    s.click()
    assert s.page.evaluate(
        "() => window.__frames.map(f => f.getAttribute('src'))") == [
        "/gmail/auth/google/link"]
    s.connected["gmail"] = True
    s.callback({"type": "aiui-gmail-connected", "connected": True})
    assert s.sent() == [SAID % "Gmail"]


def test_calendar_is_confirmed_by_its_status_too(site):
    s = site([("calendar", "Google Calendar")], {"calendar": False})
    s.click()
    s.callback({"type": "aiui-calendar-connected"})   # but the service says no
    assert s.sent() == []
    s.connected["calendar"] = True
    s.callback({"type": "aiui-calendar-connected"})
    assert s.sent() == [SAID % "Google Calendar"]


def test_one_google_sign_in_for_two_apps_is_one_message(site):
    s = site([("gmail", "Gmail"), ("calendar", "Google Calendar")],
             {"gmail": False, "calendar": False})
    s.click(0)
    s.click(1)
    s.connected.update(gmail=True, calendar=True)
    s.callback({"type": "aiui-gmail-connected"}, frame=0)
    s.callback({"type": "aiui-calendar-connected"}, frame=1)
    s.page.wait_for_timeout(2500)
    assert s.page.evaluate("() => window.__sent") == [
        SAID % "Gmail and Google Calendar"]


# --- and never sends what it should not -----------------------------------------

def test_a_signal_the_service_does_not_confirm_sends_nothing(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.callback(OAUTH_OK)
    assert s.sent(ms=2500) == []
    assert s.button() == "Connect ClickUp"


def test_a_failed_login_sends_nothing(site):
    s = site([("clickup", "ClickUp")], {"clickup": True})
    s.click()
    s.callback({"aiuiOauth": True, "ok": False})
    assert s.sent(ms=2500) == []


def test_a_message_from_any_other_window_is_ignored(site):
    """Connected already at the click, so only the login this button opened
    can finish it; the page posting to itself (any other frame or tab) is
    not that login."""
    s = site([("clickup", "ClickUp")], {"clickup": True})
    s.click()
    s.page.evaluate("m => window.postMessage(m, '*')", OAUTH_OK)
    assert s.sent(ms=4500) == []
    s.callback(OAUTH_OK)
    assert s.sent() == [SAID % "ClickUp"]


def test_text_in_the_box_is_never_overwritten(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.page.evaluate("() => { document.getElementById('chat-input').innerText = 'my draft'; }")
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    s.page.locator(".aiui-carry-on").wait_for(timeout=5000)
    assert s.page.evaluate("() => window.__sent") == []
    assert s.page.evaluate(
        "() => document.getElementById('chat-input').innerText") == "my draft"
    s.page.evaluate("() => { document.getElementById('chat-input').innerHTML = ''; }")
    s.page.locator(".aiui-carry-on").click()
    assert s.sent() == [SAID % "ClickUp"]


def test_when_send_never_comes_our_text_is_taken_back_out(site):
    """A reply still running shows Stop, not Send."""
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.page.evaluate("() => { window.__busy = true; }")
    s.click()
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    s.page.locator(".aiui-carry-on").wait_for(timeout=8000)
    assert s.page.evaluate("() => window.__sent") == []
    assert s.page.evaluate(
        "() => document.getElementById('chat-input').innerText.trim()") == ""


def _moved_on(site, how):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.page.evaluate(how)
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    s.page.locator(".aiui-carry-on").wait_for(timeout=5000)
    assert s.page.evaluate("() => window.__sent") == []


def test_a_person_who_left_the_chat_gets_a_continue_button(site):
    _moved_on(site, "() => history.pushState({}, '', '/c/another')")


def test_a_person_who_sent_something_since_gets_a_continue_button(site):
    _moved_on(site, """() => { const m = document.createElement('div');
        m.id = 'message-2'; m.innerHTML = '<div class="chat-user">never mind</div>';
        document.body.insertBefore(m, document.getElementById('chat-input')); }""")


def test_a_reply_that_is_no_longer_the_last_gets_a_continue_button(site):
    _moved_on(site, """() => { const m = document.createElement('div');
        m.id = 'message-3'; m.innerHTML = '<div class="chat-assistant">later</div>';
        document.body.insertBefore(m, document.getElementById('chat-input')); }""")


def test_a_reply_drawn_again_still_shows_it_connected(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.page.evaluate("""() => { const m = document.getElementById('message-1');
        m.innerHTML = '<div class="chat-assistant"><p>Connect it.</p><p>'
          + '<a href="#aiui-connect:clickup">Connect ClickUp</a></p></div>';
        m.querySelectorAll('a').forEach(a => window.__wire(a)); }""")
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    assert s.sent() == [SAID % "ClickUp"]
    assert s.button() == "✓ ClickUp connected"


def test_it_carries_on_once(site):
    s = site([("clickup", "ClickUp")], {"clickup": False})
    s.click()
    s.connected["clickup"] = True
    s.callback(OAUTH_OK)
    s.sent()
    s.callback(OAUTH_OK)
    s.page.wait_for_timeout(4000)
    assert s.page.evaluate("() => window.__sent") == [SAID % "ClickUp"]
