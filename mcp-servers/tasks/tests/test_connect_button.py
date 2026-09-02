"""The button the assistant's link becomes.

Structural, because this file is vanilla JS with no test harness. These
check the things that would silently break the flow, and the browser pass
in Task 4 is what actually proves it works.
"""
import os
import re

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def test_the_marker_link_is_recognised():
    assert "#aiui-connect:" in _js()


def test_a_blocked_popup_is_detected_and_explained():
    """Chrome blocks a window.open that no click triggered, and a blocked
    call returns null. Without checking, the user clicks and nothing at all
    happens, which reads as the feature being broken."""
    js = _js()
    assert re.search(r"window\.open\(", js)
    assert re.search(r"aiuiPopupBlocked|popupBlocked", js), (
        "nothing detects a blocked popup")


def test_there_is_a_panel_fallback():
    """Somebody who never allows popups must still be able to connect."""
    assert "aiuiOpenConnections" in _js()


def _connect_links_section(js):
    """The block this task added: from its own section comment up to the
    next pre-existing function. A structural boundary, not a text search,
    so it cannot silently exclude part of the new code the way splitting on
    the last occurrence of a common substring did before.

    Deliberately not "the whole file": mcp-servers/gdrive/integrations-ui.js
    already uses "password" and "autofill" legitimately elsewhere, for a
    manually pasted API credential field (masking it, and telling browser
    password managers to leave it alone) that predates this task and is not
    part of the connect-link flow this test is checking.
    """
    start = js.index("===== The assistant's connect links =====")
    end = js.index("function linkifyConnectButtons()")
    assert start < end
    return js[start:end]


def test_the_login_is_never_completed_for_the_user():
    """We open the door. Automating the login would mean holding somebody's
    password and second factor, which is what OAuth exists to avoid."""
    section = _connect_links_section(_js()).lower()
    for bad in ["password", "autofill", "document.forms[0].submit"]:
        assert bad not in section, bad


def test_no_dashes_in_the_new_copy():
    # Built via chr(), not a literal or escaped character, so this
    # assertion cannot be defeated by accidentally typing the very
    # character it is checking for.
    assert chr(0x2014) not in _js() and chr(0x2013) not in _js()
