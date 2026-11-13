"""The page after an approval, read as text.

Its behaviour is tested in a real browser
(tests/browser/test_the_connect_page_in_a_tab.py), which is where the two
bugs in it were actually found. These are the cheap guards on the two
things that would break it again silently, and they run with no browser.
"""
import routes_connections as RC


def _page(message="Connected to Airtable as aiui.teams@gmail.com.", **kw):
    return RC._oauth_done(True, message, **kw).body.decode("utf-8")


def test_an_at_sign_in_an_account_name_survives_into_the_page():
    """The page used to be assembled with "@" standing in for a double
    quote and unescaped once at the end, so every @ in the MESSAGE became
    a quote too. "aiui.teams@gmail.com" closed the JS string early and
    the whole script was a SyntaxError: no text, no postMessage, no
    close. That is what Ralph was looking at on 2026-11-11."""
    assert "aiui.teams@gmail.com" in _page()


def test_the_page_has_no_placeholder_left_to_collide_with_anybodys_data():
    """Any character that stands in for another is a character somebody's
    workspace name will contain one day."""
    page = _page("Connected.")
    assert 'style="font-family' in page, (
        "attributes are quoted with quotes, not with a stand-in")


def test_the_script_does_not_run_at_the_top_level():
    """`var opener = null` at global scope IS `window.opener = null`: the
    page blinded itself to its own opener one line before reading it, so
    every popup took the branch written for a tab. The function is what
    keeps that variable local."""
    page = _page()
    assert "<script>(function () {" in page
    assert "})();</script>" in page


def test_a_vendor_name_still_cannot_close_the_script_block():
    page = _page("Connected to </script><script>alert(1)</script>")
    assert "</script><script>alert" not in page
    assert "u003c" in page


def test_the_message_no_longer_decides_what_to_say_about_closing():
    """Whether "you can close this window" is true depends on whether
    this is a popup or a tab, and only the page knows that."""
    page = _page()
    assert "You can close this window" in page
    assert "You can go back to IO now" in page
