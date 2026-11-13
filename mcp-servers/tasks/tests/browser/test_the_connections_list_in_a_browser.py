"""The Connections list on the Agents page, rendered and driven.

Nothing had ever rendered this list. Every test of it read Python or read
the file as text, which cannot see a row that says Connected for a
credential the vendor rejected, a secret field rendered as a visible text
box, or a workspace name that lands as markup. All three have been real
here:

- A card read "Connected" for days while every call with that credential
  answered 401 (PR #197, then #208 for the chat's version of the same
  lie). The fix is three states, not two, and this is the first test that
  looks at the rendered state.
- `account_label` comes from the VENDOR's own payload, so esc() is the
  only thing between a workspace somebody else named and script running
  in this session.

The stub is BUILT FROM THE REAL REGISTRY: `routes_connections._describe`
over `connections.PROVIDERS`, the same two things the live route uses. A
hand-written payload would answer whatever it was asked, which is how a
card requesting thumb.png from a route serving thumb.jpg passed a full
round of tests.
"""
import http.server
import json
import os
import pathlib
import shutil
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C                                     # noqa: E402
import routes_connections as RC                             # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
ME = "user-me"

#: A workspace name that runs script if the row ever stops escaping. It
#: arrives from the vendor, not from the person, which is why it is the
#: account label and not something typed into the form.
HOSTILE = '<img src=x onerror="window.__pwned=1">'

#: What the database holds, in the shape `_stored` returns. One connection
#: that works, one the vendor has rejected, one whose account name is
#: hostile, and everything else absent.
STORED = {
    "trello": {"account_label": "ralphbenitez1", "check_ok": True,
               "checked_at": "2026-11-13T09:00:00", "updated_at": "x"},
    "github": {"account_label": "aiuiteams-hub", "check_ok": False,
               "checked_at": "2026-11-13T09:29:44", "updated_at": "x"},
    "clickup": {"account_label": HOSTILE, "check_ok": None,
                "checked_at": None, "updated_at": "x"},
}


def _connections_payload():
    """Exactly what GET /api/tasks/connections sends, from the real
    registry and the real describer."""
    return {"connections": [RC._describe(p, STORED)
                            for p in C.PROVIDERS.values()]}


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
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    html = (tmp_path / "agents.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                   # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1400, "height": 1000})
    pg.set_default_timeout(5000)
    sent = []

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif "/agents/stream" in url:
            r.fulfill(status=204, body="")
            return
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/skills" in url:
            body = {"skills": []}
        # Before the connections match, because this URL contains the word.
        elif "/connections/" in url:
            sent.append({"url": url, "method": r.request.method})
            body = {"url": "https://vendor.example/authorize?x=1"}
        elif url.rstrip("/").endswith("/api/tasks/connections"):
            body = _connections_payload()
        elif "/agents/tools" in url:
            # Google's three, the only ones this page reads from here. Not
            # connected, so the Google row is the one "Not connected" that
            # does not come from the registry.
            body = {"tools": [{"id": t, "label": t, "connected": False,
                               "connect_url": ""}
                              for t in ("gmail", "calendar", "gdrive")]}
        elif "/api/v1/models/list" in url:
            body = {"items": [], "total": 0}
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = {"data": []}
        elif url.rstrip("/").endswith("/api/tasks/agents/memory"):
            body = {"counts": {}}
        else:
            sent.append({"url": url, "method": r.request.method})
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    pg.click("#open-connections")
    pg.wait_for_selector('#connections-list [data-provider="trello"]')
    pg.sent = sent
    yield pg
    pg.close()
    srv.shutdown()


def _row(page, provider):
    return page.locator('#connections-list [data-provider="%s"]' % provider)


def _state(page, provider):
    return _row(page, provider).locator(".conn-state").inner_text().strip()


def _button(page, provider):
    return _row(page, provider).locator("button[data-conn]").inner_text().strip()


# --- the list itself -------------------------------------------------------

def test_the_list_holds_a_row_for_every_provider_plus_google(page):
    """Read off the registry, so an app added to connections.PROVIDERS and
    missing from this page fails here rather than being noticed by
    somebody looking for it."""
    rows = page.locator("#connections-list [data-provider]")
    assert rows.count() == len(C.PROVIDERS) + 1
    got = [e.get_attribute("data-provider") for e in rows.all()]
    assert got[0] == "__google__"
    assert set(got[1:]) == set(C.PROVIDERS)


def test_jira_is_one_of_them(page):
    """The connector shipped today. This is the second of the two surfaces
    that draw the list, and the one the Agents page uses."""
    assert _row(page, "jira").count() == 1
    assert "Jira" in _row(page, "jira").locator(".conn-name").inner_text()


# --- the three states, which is where the real bug was ---------------------

def test_a_working_connection_says_connected_and_offers_reconnect(page):
    assert _state(page, "trello") == "Connected"
    assert _button(page, "trello") == "Reconnect"
    assert "ralphbenitez1" in _row(page, "trello").inner_text()


def test_a_rejected_credential_does_not_say_connected(page):
    """The bug, rendered. GitHub's token answers 401, so `check_ok` is
    false, and a row saying Connected is the whole lie: a person reading
    this screen has no reason to reconnect and every call keeps failing."""
    assert _state(page, "github") == "Needs reconnecting"
    assert "Connected" not in _state(page, "github")
    assert "warn" in (_row(page, "github").locator(".conn-state")
                      .get_attribute("class") or "")


def test_a_rejected_credential_still_names_the_account_it_belongs_to(page):
    """It is not a fresh setup. Something is stored and it has a name on
    it, which is why the button says Reconnect."""
    assert "aiuiteams-hub" in _row(page, "github").inner_text()
    assert _button(page, "github") == "Reconnect"


def test_an_app_nobody_connected_says_so(page):
    assert _state(page, "jira") == "Not connected"
    assert _button(page, "jira") == "Connect"


def test_silence_is_not_a_rejection(page):
    """`check_ok` is None for a credential nobody has used yet. That must
    read as Connected, not as Needs reconnecting: accusing a credential
    nothing has tested sends people to redo work that was fine."""
    assert _state(page, "clickup") == "Connected"


# --- a vendor's own words, rendered ---------------------------------------

def test_a_hostile_account_name_is_shown_as_text_not_run(page):
    """`account_label` comes from the vendor's payload. The row is built
    with innerHTML, so esc() is the only thing in the way."""
    row = _row(page, "clickup")
    assert not page.evaluate("window.__pwned"), "the account name executed"
    assert row.locator("img").count() == 0
    assert HOSTILE in row.inner_text()


# --- the form ------------------------------------------------------------

def test_connect_opens_a_form_with_one_box_per_field(page):
    """Jira is the one with three, which is why it is the one used here: a
    page that renders only the first field passes on every other
    provider."""
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    form = _row(page, "jira").locator(".conn-form")
    page.wait_for_selector('[data-provider="jira"] .conn-form input')
    names = [e.get_attribute("data-field")
             for e in form.locator("input").all()]
    assert names == [f.name for f in C.provider("jira").fields]


def test_a_secret_is_a_password_box_and_the_rest_are_not(page):
    """Jira's token is secret; the site address and the email are not, and
    a person has to be able to read back what they typed to fix a typo in
    a URL."""
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    page.wait_for_selector('[data-provider="jira"] .conn-form input')
    form = _row(page, "jira").locator(".conn-form")
    kinds = {e.get_attribute("data-field"): e.get_attribute("type")
             for e in form.locator("input").all()}
    assert kinds == {"site_url": "text", "email": "text", "token": "password"}


def test_the_form_says_where_to_get_the_credential(page):
    """A box asking for an API token is useless to somebody who does not
    know where theirs lives, and the words come from connections.py so the
    page and the assistant cannot drift apart."""
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    page.wait_for_selector('[data-provider="jira"] .conn-where')
    said = _row(page, "jira").locator(".conn-where").inner_text()
    assert "id.atlassian.com" in said
    assert said.strip() in C.provider("jira").where


def test_a_second_click_closes_the_form_again(page):
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    page.wait_for_selector('[data-provider="jira"] .conn-form input')
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    assert _row(page, "jira").locator(".conn-form").is_hidden()


def test_an_oauth_app_opens_a_sign_in_instead_of_asking_for_a_token(page):
    """A provider with a configured OAuth app must not be handed a token
    box: the person has nothing to paste. Which providers those are
    depends on this box's environment, so the row is driven by the `oauth`
    flag rather than by a provider name.
    """
    page.evaluate("""() => {
        const row = document.querySelector('[data-provider="jira"]');
        row._meta.oauth = true;
    }""")
    page.click('#connections-list [data-provider="jira"] button[data-conn]')
    page.wait_for_selector('[data-provider="jira"] .conn-where')
    assert "sign in" in _row(page, "jira").locator(".conn-where").inner_text()
    assert _row(page, "jira").locator(".conn-form input").count() == 0
    assert any("/oauth/start" in c["url"] for c in page.sent), page.sent
