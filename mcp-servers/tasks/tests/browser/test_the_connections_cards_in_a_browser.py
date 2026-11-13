"""The OTHER surface that draws the Connections list: the modal's cards.

The Agents page has rows (test_the_connections_list_in_a_browser.py).
Open WebUI has this: a grid of cards in integrations-ui.js, with four
states instead of three, because a card can also say "Coming soon" for an
app with no connector behind it. Nothing had ever rendered them either.

The real APPS array, iconEl, the slot constants and makeCard are lifted
out of the shipped file by name, the way the step panel's test does it.
Only what makeCard CLOSES OVER is supplied here: which apps are
connected, what the server said about each credential, and no-op stand-ins
for the handlers a click would reach. Nothing is clicked in this file.

What it is for: the states, and the one claim that spans both files, that
a card offering a Connect is a card with a provider behind it.
"""
import json
import os
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C                                     # noqa: E402

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")

#: An account name that runs script if the card ever stops using
#: textContent. It comes from the vendor's payload, not from the person.
HOSTILE = '<img src=x onerror="window.__pwned=1">'


def _lift():
    """APPS, iconEl, the slot constants and makeCard, from the real file.

    By name and by indentation, so a rename fails here rather than
    quietly testing a stale copy.
    """
    src = JS.read_text(encoding="utf-8")

    def fn(name):
        start = src.index("    function " + name + "(")
        return src[start:src.index("\n    }\n", start) + 6]

    start = src.index("    var APPS = [")
    apps = src[start:src.index("\n    ];\n", start) + 7]

    slots = "\n".join(line.strip() for line in src.splitlines()
                      if line.strip().startswith("var SLOT_"))
    return apps + "\n" + slots + "\n" + fn("iconEl") + "\n" + fn("makeCard")


#: The handful of names makeCard closes over. State first, then no-op
#: stand-ins for the three things only a click reaches, so an accidental
#: click in a later test fails loudly instead of connecting something.
HARNESS = """
    var GMAIL_API = '/gmail', CALENDAR_API = '/calendar', GDRIVE_API = '/gdrive';
    var email = 'me@example.com';
    var connState = window.__state || {};
    var connPartial = window.__partial || {};
    var connChecked = window.__checked || {};
    var connMeta = window.__meta || {};
    function openTokenPanel() { window.__clicked = 'token'; }
    function unifiedConnect() { window.__clicked = 'google'; }
    function askConfirm() { window.__clicked = 'confirm'; }
    function renderGrid() {}
"""


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
def cards(browser):
    """Every app in the real APPS array, rendered, keyed by id.

    The states are set so that one app stands for each: trello works,
    github was rejected, clickup has never been used and carries a hostile
    account name, google is half done.
    """
    pg = browser.new_page(viewport={"width": 1000, "height": 900})
    pg.set_default_timeout(5000)
    # Measured, not assumed: `!connChecked[app.id]` is tested BEFORE
    # connected and partial, so a card whose state has not come back from
    # the server says "Checking" whatever else is true of it. Every app is
    # marked checked here except notion, which is left unchecked on
    # purpose to hold that state down.
    checked = {a: True for a in ("google", "clickup", "trello", "airtable",
                                 "hubspot", "github", "n8n", "zapier",
                                 "jira", "dropbox", "stripe", "linkedin",
                                 "facebook", "x")}
    state = {
        "__state": {"trello": True, "github": True, "clickup": True,
                    "google": False},
        "__partial": {"google": True},
        "__checked": checked,
        "__meta": {"trello": {"account_label": "ralphbenitez1",
                              "needs_reconnect": False},
                   "github": {"account_label": "aiuiteams-hub",
                              "needs_reconnect": True},
                   "clickup": {"account_label": HOSTILE,
                               "needs_reconnect": False}},
    }
    setup = "\n".join("window.%s = %s;" % (k, json.dumps(v))
                      for k, v in state.items())
    pg.set_content("<!doctype html><html><body><div id='grid'></div>"
                   "<script>" + setup + "\n(function () {\n"
                   + HARNESS + _lift()
                   + "\n  window.__render = function () {"
                     "    var g = document.getElementById('grid');"
                     "    APPS.forEach(function (a) {"
                     "      var c = makeCard(a);"
                     "      c.setAttribute('data-app', a.id);"
                     "      g.appendChild(c);"
                     "    });"
                     "    window.__apps = APPS.map(function (a) { return a.id; });"
                     "  };\n})();\n__render();</script></body></html>")
    pg.wait_for_function("() => window.__apps && window.__apps.length")
    yield pg
    pg.close()


def _card(pg, app_id):
    return pg.locator('[data-app="%s"]' % app_id)


def _said(pg, app_id):
    return _card(pg, app_id).inner_text().strip()


# --- it rendered at all ----------------------------------------------------

def test_every_app_in_the_shipped_list_drew_a_card(cards):
    ids = cards.evaluate("() => window.__apps")
    assert len(ids) >= 10
    assert cards.locator("[data-app]").count() == len(ids)


# --- the four states ------------------------------------------------------

def test_a_working_connection_says_connected(cards):
    assert "Connected" in _said(cards, "trello")
    assert "ralphbenitez1" in _said(cards, "trello")


def test_a_rejected_credential_says_so_and_not_connected(cards):
    """The bug this card's status line exists for: it read Connected for
    days while every call with that credential answered 401."""
    said = _said(cards, "github")
    assert "Needs reconnecting" in said
    assert "Connected" not in said
    assert "aiuiteams-hub" in said, "it is not a fresh setup, so name the account"


def test_silence_about_a_credential_is_not_a_rejection(cards):
    """clickup has never been used, so nothing is known. Accusing it would
    send somebody to redo a connection that is fine."""
    said = _said(cards, "clickup")
    assert "Connected" in said
    assert "Needs reconnecting" not in said


def test_a_half_finished_connect_says_finish_connecting(cards):
    """Google's three services behind one card: some granted, not all."""
    assert "Finish connecting" in _said(cards, "google")


def test_an_app_with_a_connector_and_no_credential_offers_connect(cards):
    assert "Connect" in _said(cards, "airtable")
    assert "Coming soon" not in _said(cards, "airtable")


def test_a_card_says_nothing_about_connecting_until_the_server_answered(cards):
    """notion's state has not come back. It must not say Connect: somebody
    reading that clicks it and is asked to paste a credential they already
    gave, and it must not say Connected either, which would be a guess.

    This state is checked FIRST in the real card, before connected and
    before partial, which is why it is here as its own test rather than as
    a note on another one.
    """
    said = _said(cards, "notion")
    assert "Checking" in said
    assert "Connect" not in said and "Connected" not in said


# --- the claim that spans both surfaces ----------------------------------

def test_no_card_offers_a_connect_without_a_provider_behind_it(cards):
    """A Connect that opens a form for a provider the server does not know
    is a dead end, and five of these cards are one line away from being
    exactly that."""
    offered = [i for i in cards.evaluate("() => window.__apps")
               if "Coming soon" not in _said(cards, i)]
    unbacked = sorted(set(offered) - set(C.PROVIDERS) - {"google"})
    assert unbacked == [], (
        "these cards offer a connect with no entry in connections.PROVIDERS: "
        + ", ".join(unbacked))


def test_jira_is_no_longer_coming_soon(cards):
    """The connector shipped today, and this is the surface most people
    will see it on."""
    assert "Coming soon" not in _said(cards, "jira")
    assert "Connect" in _said(cards, "jira")


def test_an_app_with_no_connector_still_says_coming_soon(cards):
    """Five are left, each with its own card on the board. A card that
    offered a Connect for one of them would open a form the server cannot
    answer."""
    for app_id in ("dropbox", "stripe", "linkedin", "facebook", "x"):
        assert "Coming soon" in _said(cards, app_id), app_id


def test_a_card_nobody_can_connect_is_dimmed(cards):
    """The status line is 11px. The opacity is what carries that at a
    glance, across a grid of sixteen."""
    assert _card(cards, "dropbox").evaluate(
        "e => e.style.opacity") == "0.45"
    assert _card(cards, "trello").evaluate("e => e.style.opacity") in ("", "1")


# --- a vendor's own words ------------------------------------------------

def test_a_hostile_account_name_is_text_and_was_not_run(cards):
    assert not cards.evaluate("window.__pwned"), "the account name executed"
    assert _card(cards, "clickup").locator("img[src^='data']").count() == 0
    assert HOSTILE in _said(cards, "clickup")


def test_nothing_in_this_file_clicked_anything(cards):
    """The handlers are stand-ins. If a test above started clicking, the
    assertions would be about this harness rather than about the real
    panel, and that is worth failing over."""
    assert cards.evaluate("window.__clicked") in (None, )
