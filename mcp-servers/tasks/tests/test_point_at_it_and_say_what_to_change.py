"""Point at a part of the site and say what to change.

Ralph's screenshots of ChatGPT's canvas, 2026-11-04: click an element in
the preview, a box asks "What would you like to change?", and the answer
edits that part.

The panel already shows the running app, so the thing somebody wants to
change is under the pointer. This turns that into the ordinary enhance a
build already knows how to do.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")
GATEWAY = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "api-gateway", "main.py")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    src = _js()
    start = src.index("function " + name)
    ends = [src.find(m, start + 10)
            for m in ("\n  function ", "\n  // ===== End")]
    return src[start:min(e for e in ends if e != -1)]


# --- it has to be able to reach it at all ---------------------------------

def test_the_user_scoped_builder_is_reachable_from_a_browser():
    """/api/tasks/enhance is admin-only and keyed by a task id. The
    user-scoped one takes a slug and checks the owner's email, and until
    now the gateway did not route it, so a browser could not call it."""
    with open(GATEWAY, encoding="utf-8") as fh:
        src = fh.read()
    assert 'full_path.startswith("/api/aiuibuilder")' in src


def test_it_asks_the_user_scoped_route():
    body = _fn("aiuiShowAppInline")
    assert "/api/aiuibuilder/" in body
    assert "/enhance" in body


# --- naming what was pointed at -------------------------------------------

def test_the_element_is_described_three_ways():
    """A selector alone is brittle, and the visible words are what the
    person was actually pointing at."""
    body = _fn("aiuiAnnotatePrompt")
    assert "selector:" in body
    assert "tag:" in body
    assert "it currently reads:" in body


def test_the_agent_is_told_to_leave_the_rest_alone():
    """Otherwise a request to change one heading comes back as a redesign
    of the page."""
    assert "Leave the rest of the page alone" in _fn("aiuiAnnotatePrompt")


def test_an_id_is_the_whole_selector():
    """Walking further up past an id adds noise to something already
    unambiguous."""
    body = _fn("aiuiSelectorFor")
    assert "if (el.id) return '#' + el.id;" in body


def test_the_selector_does_not_run_away_up_the_tree():
    """A path from <html> down is unreadable and no more precise."""
    # The bound WITH its semicolon: "depth < 40" contains "depth < 4",
    # so the looser check passed on a selector walking ten times further.
    assert "depth < 4;" in _fn("aiuiSelectorFor")


def test_our_own_outline_is_never_part_of_the_selector():
    """The class is added to whatever is under the pointer. Including it
    would describe the element by the fact we were pointing at it."""
    assert "c !== AIUI_MARK" in _fn("aiuiSelectorFor")


# --- pointing, not using --------------------------------------------------

def test_a_click_does_not_work_the_app():
    """The app is live. Pointing at a link would otherwise navigate the
    frame away from the page being changed."""
    body = _fn("aiuiAnnotateOn")
    assert "e.preventDefault()" in body
    assert "e.stopPropagation()" in body


def test_a_frame_it_cannot_read_is_said_out_loud():
    """No document means the app has not finished loading. A button that
    looks armed and does nothing is worse than one that says why."""
    body = _fn("aiuiAnnotateOn")
    assert "if (!doc || !doc.body) return null;" in body
    assert "Wait for the app to finish loading" in _js()


def test_turning_it_off_puts_the_page_back():
    """Listeners, the injected stylesheet, and every outline it left."""
    body = _fn("aiuiAnnotateOff")
    assert "removeEventListener('click'" in body
    assert "removeEventListener('mouseover'" in body
    assert "style.parentNode.removeChild" in body
    assert "classList.remove(AIUI_MARK)" in body


def test_reaching_into_the_frame_is_guarded():
    """contentDocument throws across origins. It is our own app today,
    and a try is what stops that being an assumption."""
    assert "try {" in _fn("aiuiAnnotateOn")


# --- what happens after ----------------------------------------------------

def test_the_app_is_reloaded_when_the_change_lands():
    """An app whose code changed five minutes ago and still shows the old
    page looks like the change was ignored."""
    body = _fn("aiuiWatchChange")
    assert "frame.src = at + '?changed=' + Date.now()" in body


def test_a_failed_change_says_the_app_is_unharmed():
    """The regression guard rolls back. Somebody who is not told that
    assumes their app is broken."""
    assert "The app is" in _fn("aiuiWatchChange")


def test_it_gives_up_eventually():
    body = _fn("aiuiWatchChange")
    assert "AIUI_CHANGE_GIVE_UP_MS" in body


def test_it_does_not_poll_faster_than_a_build_moves():
    """An enhance is a build: minutes, not seconds."""
    src = _js()
    ms = re.search(r"AIUI_CHANGE_POLL_MS = (\d+)", src)
    assert ms and int(ms.group(1)) >= 5000
