"""Three things from one screenshot of a preview sitting in the chat.

    "change the icon for pencil because it colorful and the other icon
     isnt... or fix all"

    "it cant be stretch widen the preview in the chat... i can only
     stretch it straith or hight only not in the left or right like i
     want it to wide inside the chat"

    "if also creating can you load skeleton loading animation in the
     output of the chat -- because user didnt know its loading and
     working on it"

THE WIDTH ONE IS A REAL BUG IN WHAT SHIPPED YESTERDAY. The drag was
written and tested and does set symmetric negative margins, and the box
carries

    max-width: 46rem

from the day it was built. A block element with a max-width does not grow
past it however negative its margins are: the margins move it, the cap
holds the width. So the handle moved the box around inside its column and
every test of it passed, because they all measured a box with no such cap
on it.

THE SECOND HALF of the same bug is that `marginLeft` carries TWO meanings
on this box. It is the thread's avatar gutter, 3.75rem, which both
placement functions set to 0 when the panel goes inside a reply, and it is
now also half the extra width. Whichever ran last won, so a widened panel
snapped back to its column the next time Open WebUI rebuilt the message
and the panel was re-placed. They are composed now, with the gutter kept
on the box as its own value.
"""
import os
import re

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


# --- 1. the cap that made the drag look broken ----------------------------

def test_a_widened_preview_is_not_still_capped_at_its_column():
    """The whole bug. 46rem is about 736 pixels, and the message column is
    narrower than that, so the cap never showed until somebody tried to
    make the box wider than the column it sits in."""
    body = _fn("aiuiApplyAppWidth")
    assert "maxWidth" in body, (
        "the margins move the box but max-width still holds its width")


def test_an_unwidened_preview_keeps_the_cap_it_always_had():
    """Not a licence to grow. At rest it is one turn in a conversation."""
    body = _fn("aiuiApplyAppWidth")
    assert "AIUI_APP_MAXW" in body
    assert "var AIUI_APP_MAXW" in _js()


def test_the_cap_is_one_value_rather_than_a_number_in_two_places():
    src = _js()
    at = src.index("var AIUI_APP_MAXW")
    assert "46rem" in src[at:at + 80]


# --- 2. the gutter and the width stop fighting ----------------------------

def test_the_gutter_is_kept_on_the_box_rather_than_in_its_margin():
    """marginLeft meant two things at once: the thread's avatar gutter and
    half the extra width. Whichever was written last won."""
    assert "data-aiui-indent" in _js()


def test_the_width_is_added_to_the_gutter_not_instead_of_it():
    body = _fn("aiuiApplyAppWidth")
    assert "calc(" in body, (
        "the gutter and the offset have to compose, or a widened panel "
        "in a reply loses its indent")


def test_placing_a_panel_in_a_reply_no_longer_wipes_its_width():
    """Open WebUI rebuilds a message's content, so a panel is re-placed.
    Setting marginLeft directly there threw the chosen width away."""
    body = _fn("aiuiPutInReply")
    assert "style.marginLeft = '0'" not in body
    assert "aiuiSetIndent(" in body


def test_the_other_placement_does_the_same():
    body = _fn("aiuiPutUnderLastMessage")
    assert "style.marginLeft = '0'" not in body
    assert "aiuiSetIndent(" in body


def test_a_panel_moved_to_the_right_reply_keeps_its_width():
    """The one branch that re-places an ALREADY DRAWN panel."""
    body = _fn("aiuiShowAppInline")
    drawn = body[body.index("var drawn = document.getElementById(id)"):][:420]
    assert "aiuiPutInReply(drawn, inReply)" in drawn


def test_a_panel_that_cannot_be_widened_is_left_alone():
    """The video panel and the build panel share these placement
    functions and have no width of their own to restore."""
    body = _fn("aiuiSetIndent")
    assert "data-aiui-widenable" in body


def test_the_preview_is_the_thing_marked_widenable():
    body = _fn("aiuiShowAppInline")
    assert "data-aiui-widenable" in body


# --- 3. one of these icons is not like the others -------------------------

def test_every_glyph_in_the_bar_asks_for_text_rather_than_emoji():
    """The pencil is U+270E and the open-in-a-tab arrow is U+2197, and
    both have an emoji presentation a browser is free to pick. It did:
    the pencil came out orange beside five monochrome glyphs.

    U+FE0E is the variation selector that says "draw this as text". It
    changes nothing for a character that has no emoji form, which is why
    it goes on all of them rather than on the two that misbehave today.
    """
    body = _fn("aiuiShowAppInline")
    for glyph in ("✎", "↗", "▣", "◐", "⤢"):
        for found in re.finditer(re.escape(glyph), body):
            before = body[max(0, found.start() - 11):found.start()]
            assert before.endswith("aiuiGlyph('"), (
                "%r is drawn without a text-presentation request" % glyph)


def test_there_is_one_helper_rather_than_a_selector_typed_six_times():
    """Written as the JS escape rather than the character itself.

    U+FE0E is invisible. Typed literally it is a character nobody can see
    in the source, that a careless editor can strip, and that reads as a
    typo to the next person; `\\ufe0e` says what it is.
    """
    assert "\n  function aiuiGlyph(" in _js()
    body = _fn("aiuiGlyph")
    assert "\\ufe0e" in body or "︎" in body


def test_the_close_button_in_the_side_panel_matches_too():
    body = _fn("aiuiSplitOpen")
    assert "aiuiGlyph(" in body


# --- 4. something on screen from the first tick ---------------------------

def test_a_build_shows_its_shape_before_the_first_answer_comes_back():
    """The step list needs the task to have answered AND its labels to
    have loaded, which is seconds in. Until then a build in the chat
    looked like nothing happening at all."""
    body = _fn("aiuiPollBuild")
    assert "aiuiShowBuildGhost()" in body
    at = body.index("aiuiShowBuildGhost()")
    assert at < body.index("fetch("), (
        "the ghost is drawn after the first answer, which is the wait it "
        "exists to cover")


def test_the_ghost_is_drawn_once_rather_than_every_poll():
    body = _fn("aiuiShowBuildGhost")
    assert "aiui-app-skeleton" in body
    assert "return" in body


def test_the_ghost_waits_for_somewhere_to_put_itself():
    """A chat just opened can answer its first poll before any reply is
    drawn, and a panel put then goes to the end of the page and stays
    there."""
    body = _fn("aiuiShowBuildGhost")
    assert "aiuiLastReplyBody()" in body


def test_only_the_watcher_draws_the_placeholder():
    """The step panel used to draw it, because it was the earliest thing
    that ran. The watcher now draws it on its first tick, seconds before
    this panel's labels have even been fetched, so the step panel's copy
    is redundant and two callers would be two places to drift."""
    body = _fn("aiuiStepPanel")
    assert "aiuiShowBuildGhost()" not in body
    # Calls only. The declaration contains the same text.
    calls = re.findall(r"(?<!function )aiuiShowBuildGhost\(\)", _js())
    assert len(calls) == 1, (
        "%d callers draw the placeholder, which is %d places to drift"
        % (len(calls), len(calls)))


def test_the_ghost_is_the_size_the_preview_will_be():
    """It stands in for the panel that replaces it. A placeholder that is
    a different size is a layout jump dressed up as a loading state."""
    body = _fn("aiuiSkeletonPanel")
    assert "data-aiui-widenable" in body
    assert "aiuiApplyAppWidth" in body or "aiuiSavedAppExtra" in body


def test_the_ghost_still_goes_when_the_real_panel_arrives():
    body = _fn("aiuiShowAppInline")
    assert "aiuiClearSkeletonPanel()" in body
