"""The panel beside the chat was always exactly half the window.

Ralph, 2026-11-12, pointing at the app open beside the conversation: "user
can't adjust the sizez in here to the left".

`width: 50vw`, decided once for every screen and every page. A landing
page wants more than half of a 1920 screen and a short form wants less,
and the chat on the other side has the same argument in reverse.

So the panel's left edge is a handle. The same shape as the preview's grab
bar: drag it, or focus it and use the arrows, remembered per browser,
clamped so neither side can be squeezed out of existence.

TWO THINGS IT HAS TO KEEP IN STEP, and both have bitten before:

  - `pane.style.paddingRight` is what stops the panel covering the
    conversation. It is set to 50vw when the panel opens and restored when
    it closes. A panel that resizes without moving that padding slides
    over the chat, or leaves a gap beside it.
  - The frame inside is scaled to fit by `aiuiFitDesktop`. Changing the
    panel's width without re-fitting leaves the app rendered for the old
    one.
"""
import os

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    src = _js()
    start = src.index("\n  function " + name + "(")
    rest = src[start + 3:]
    return rest[:rest.index("\n  function ")]


# --- there is an edge to take hold of -------------------------------------

def test_the_panel_has_an_edge_that_can_be_dragged():
    assert "\n  function aiuiSplitHandle(" in _js()


def test_the_edge_is_on_the_left_where_the_chat_is():
    body = _fn("aiuiSplitHandle")
    assert "left:0" in body.replace(" ", "")
    assert "ew-resize" in body


def test_the_panel_is_given_one_when_it_opens():
    body = _fn("aiuiSplitOpen")
    assert "aiuiSplitHandle(" in body


def test_it_says_what_it_is_to_a_screen_reader():
    """A bare strip you can drag is invisible to anybody not using a
    mouse, and this one is the only way to change the split."""
    body = _fn("aiuiSplitHandle")
    assert "separator" in body
    assert "aria-orientation" in body
    assert "vertical" in body
    assert "tabindex" in body


def test_the_keyboard_can_move_it_too():
    body = _fn("aiuiSplitHandle")
    assert "ArrowLeft" in body and "ArrowRight" in body


# --- the two things that must keep step -----------------------------------

def test_the_chat_is_pushed_over_by_exactly_what_the_panel_takes():
    """paddingRight is the only thing stopping the panel covering the
    conversation. It is set when the panel opens and has to follow it."""
    body = _fn("aiuiSplitHandle")
    assert "paddingRight" in body


def test_the_app_is_refitted_when_the_panel_changes_size():
    """The frame is scaled to fit. Resizing without re-fitting leaves the
    app rendered for the width it used to have."""
    body = _fn("aiuiSplitHandle")
    assert "aiuiFitDesktop(" in body


def test_closing_the_panel_still_gives_the_chat_its_padding_back():
    body = _fn("aiuiSplitClose")
    assert "s.pane.style.paddingRight = s.panePad" in body


# --- neither side can be squeezed out of existence ------------------------

def test_the_panel_cannot_be_dragged_shut():
    body = _fn("aiuiClampSplit")
    assert "AIUI_SPLIT_MIN" in body


def test_the_chat_cannot_be_dragged_shut_either():
    """The half nobody thinks of: a panel dragged to the far left leaves
    the conversation as a sliver with the handle on top of it.

    A FUNCTION rather than a constant, because the ceiling is a share of
    the window and a window can be made smaller after the fact. A number
    worked out once is a ceiling that goes stale.
    """
    body = _fn("aiuiClampSplit")
    assert "aiuiSplitMax()" in body
    ceiling = _fn("aiuiSplitMax")
    assert "innerWidth" in ceiling
    assert "AIUI_SPLIT_MIN" in ceiling, (
        "a narrow window could put the ceiling under the floor")


# --- remembered, like every other size here -------------------------------

def test_the_split_is_remembered():
    assert "aiui-split-width" in _js()


def test_it_is_remembered_per_browser_rather_than_per_app():
    """The same argument the preview's height already makes: this is an
    answer about a screen, not about one landing page."""
    src = _js()
    key = src[src.index("AIUI_SPLIT_KEY"):]
    assert "slug" not in key[:key.index("\n")]


def test_a_stored_split_that_is_nonsense_is_ignored():
    body = _fn("aiuiSavedSplit")
    assert "aiuiClampSplit" in body


def test_a_browser_with_storage_off_still_resizes():
    body = _fn("aiuiSaveSplit")
    assert "try {" in body and "catch" in body


def test_the_panel_opens_at_the_width_it_was_left_at():
    body = _fn("aiuiSplitOpen")
    assert "aiuiSavedSplit()" in body
