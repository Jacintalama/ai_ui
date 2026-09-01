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


def test_the_login_is_never_completed_for_the_user():
    """We open the door. Automating the login would mean holding somebody's
    password and second factor, which is what OAuth exists to avoid."""
    js = _js()
    for bad in ["password", "autofill", "document.forms[0].submit"]:
        assert bad not in js.lower().split("aiui-connect")[-1][:4000], bad


def test_no_dashes_in_the_new_copy():
    # Built via chr(), not a literal or escaped character, so this
    # assertion cannot be defeated by accidentally typing the very
    # character it is checking for.
    assert chr(0x2014) not in _js() and chr(0x2013) not in _js()
