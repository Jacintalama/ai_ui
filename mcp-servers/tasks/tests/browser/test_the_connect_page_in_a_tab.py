"""The page you land on after approving an app, opened in a TAB.

Ralph, 2026-11-11, on the first real Airtable connect. He approved on
Airtable, landed on /connect/airtable/callback?code=...&state=... and the
page just sat there. He asked whether it was lag at his end. It was not:
the connection had already been stored by the time that page rendered,
and the server log said so:

    oauth: ralphbenitez32@gmail.com connected airtable as aiui.teams@gmail.com

The page tells its OPENER and then closes itself. Opened in the same tab
rather than a popup there is no opener to tell, and `window.close()` on a
window a script did not open does nothing at all, silently. So nothing
was broken and the person could not tell, and the natural next move is to
approve again, which spends a second code for nothing.

A REAL BROWSER, because every claim here is about what a browser does
with this page rather than what the string contains: that close is
refused, that an assignment to window.opener changes which branch runs,
that a postMessage arrives. A test that greps the HTML for "window.close"
would have passed on the day Ralph was staring at the broken page.
"""
import pathlib
import sys

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import routes_connections as RC                              # noqa: E402


def _html(ok=True, message="Connected to Airtable as aiui.teams@gmail.com.",
          link="", link_text=""):
    body = RC._oauth_done(ok, message, link=link, link_text=link_text).body
    return body.decode("utf-8")


#: Run inside the page, immediately before its own first statement.
#:
#: `window.close()` is refused for a window the script did not open, and
#: refused silently, so the only way to see the attempt is to stand in
#: front of it. `window.opener` is assignable, which is what lets one
#: test drive both branches.
#:
#: NOT an init script. Playwright runs those again for the document that
#: set_content writes, which lands AFTER the page's own script: the first
#: version of this file set window.opener and the page still read null.
STUB = (
    "window.__closed = false;"
    "window.__told = null;"
    "window.close = function () { window.__closed = true; };"
)

OPENER = STUB + (
    "window.opener = { postMessage: function (d) { window.__told = d; } };"
)


def _with(html, stub):
    """`html` with `stub` spliced into the front of its own script."""
    assert html.count("<script>") == 1, html[:200]
    return html.replace("<script>", "<script>" + stub, 1)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _page(browser, html, opener=False):
    page = browser.new_page()
    page.set_content(_with(html, OPENER if opener else STUB))
    return page


# --- in a tab, where there is nobody to tell ------------------------------

def test_a_page_with_no_opener_does_not_try_to_close_itself(browser):
    """The attempt is not harmless: it is what the whole page rested on,
    and when it is refused the person is left looking at a dead end."""
    page = _page(browser, _html())
    page.wait_for_timeout(3500)
    assert page.evaluate("window.__closed") is False
    page.close()


def test_it_says_the_connection_worked(browser):
    page = _page(browser, _html())
    said = page.inner_text("#m")
    assert "Connected to Airtable as aiui.teams@gmail.com" in said
    page.close()


def test_it_says_what_to_do_next_rather_than_waiting_to_vanish(browser):
    page = _page(browser, _html())
    assert "back to io" in page.inner_text("#m").lower()
    page.close()


def test_there_is_a_way_back(browser):
    """His original tab was navigated away to get here, so "go back" is
    not something the browser's own button does well."""
    page = _page(browser, _html())
    link = page.locator("#a")
    assert link.is_visible()
    assert link.get_attribute("href").startswith(
        RC.PUBLIC_BASE_URL.rstrip("/"))
    page.close()


def test_the_message_is_readable_across_a_whole_tab(browser):
    """Fifteen pixels in the middle of a popup is a label. The same thing
    in the middle of a 1280 pixel tab is a page that looks empty."""
    page = _page(browser, _html())
    size = page.evaluate(
        "parseFloat(getComputedStyle(document.getElementById('m')).fontSize)")
    assert size >= 20, size
    page.close()


def test_a_refusal_in_a_tab_says_what_to_do_too(browser):
    page = _page(browser, _html(False, "Cancelled, or Airtable refused."))
    said = page.inner_text("#m")
    assert "Cancelled" in said
    assert "back to io" in said.lower()
    page.close()


# --- in a popup, where the old behaviour has to survive -------------------

def test_a_popup_still_tells_the_page_that_opened_it(browser):
    page = _page(browser, _html(), opener=True)
    page.wait_for_function("window.__told !== null", timeout=5000)
    assert page.evaluate("window.__told") == {"aiuiOauth": True, "ok": True}
    page.close()


def test_a_popup_still_closes_itself(browser):
    page = _page(browser, _html(), opener=True)
    page.wait_for_function("window.__closed === true", timeout=6000)
    page.close()


def test_a_popup_says_to_close_the_window_rather_than_to_go_back(browser):
    page = _page(browser, _html(), opener=True)
    assert "close this window" in page.inner_text("#m").lower()
    page.close()


def test_a_popup_with_somewhere_to_go_still_waits(browser):
    """A popup that vanishes before anybody can read, let alone click,
    the link is the same as no link at all."""
    page = _page(browser, _html(link="https://github.com/apps/x/installations/new",
                                link_text="Choose which repositories"),
                 opener=True)
    page.wait_for_timeout(3500)
    assert page.evaluate("window.__closed") is False
    assert page.locator("#a").is_visible()
    page.close()


def test_the_only_link_in_a_tab_is_the_one_that_was_given(browser):
    """With somewhere to go already, a second link is noise."""
    page = _page(browser, _html(link="https://github.com/apps/x/installations/new",
                                link_text="Choose which repositories"))
    assert page.locator("#a").get_attribute("href").startswith("https://github.com")
    page.close()


# --- the real reason his page did nothing --------------------------------

def test_an_account_name_with_an_at_sign_does_not_break_the_page(browser):
    """THE CAUSE, found by this test rather than by reading the code.

    The markup was assembled with "@" standing in for a double quote and
    unescaped once at the end, so every "@" in the page became a quote,
    including the ones in the message. The message is "Connected to
    Airtable as aiui.teams@gmail.com", which closed the JS string early
    and made the whole script a SyntaxError.

    So nothing in it ran: not the text, not the postMessage, not the
    close. The card for this blamed the missing opener, which is real
    and is also fixed here, but a popup was just as dead: an account
    name with an @ in it is every email address there is.
    """
    errors = []
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_content(_with(_html(
        message="Connected to Airtable as aiui.teams@gmail.com."), STUB))
    page.wait_for_timeout(300)
    assert errors == [], errors
    assert "aiui.teams@gmail.com" in page.inner_text("#m")
    page.close()


def test_a_popup_is_told_even_when_the_name_has_an_at_sign(browser):
    """The same bug from the popup side, which is where it actually hurt:
    the opener was never told, so the Connections panel behind it never
    refreshed either."""
    page = _page(browser, _html(
        message="Connected to Airtable as aiui.teams@gmail.com."),
        opener=True)
    page.wait_for_function("window.__told !== null", timeout=5000)
    page.close()


# --- the name comes from a vendor ----------------------------------------

def test_a_workspace_name_cannot_run_as_code(browser):
    """The message carries a vendor-supplied account name. A workspace
    called "</script><script>..." would close the block it sits in and
    run on our own origin."""
    nasty = "</script><script>window.__owned=1;</script>"
    page = _page(browser, _html(message="Connected to " + nasty))
    assert page.evaluate("window.__owned") is None
    assert nasty in page.inner_text("#m")
    page.close()
