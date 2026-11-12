"""Expanding puts the app beside the conversation, not under it.

Ralph's screenshots of ChatGPT's canvas, 2026-11-04: clicking expand
moves the site to its own half of the window, the chat narrows to the
other half, and the message in the thread collapses to a chip naming it.

Expanding used to make the panel taller in place, which is the cheap half
of that.
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
    start = src.index("function " + name)
    ends = [src.find(m, start + 10)
            for m in ("\n  function ", "\n  // ===== End")]
    return src[start:min(e for e in ends if e != -1)]


# --- the decision that would be quietly wrong ------------------------------

def test_the_app_is_moved_not_rebuilt():
    """Recreating the iframe reloads the app, throwing away its scroll
    position and anything typed into it. The whole point of expanding is
    to look at the thing you were already looking at."""
    body = _fn("aiuiSplitOpen")
    assert "holder.appendChild(frame)" in body
    assert "createElement('iframe')" not in body
    assert "frame.src =" not in body


def test_it_comes_home_before_the_panel_is_torn_down():
    """Removing the panel first leaves the app parentless for a tick,
    which in some browsers is enough to drop the document inside it."""
    body = _fn("aiuiSplitClose")
    home = body.index("s.home.appendChild(s.frame)")
    gone = body.index("s.panel.parentNode.removeChild(s.panel)")
    assert home < gone


def test_its_height_is_put_back():
    """It is stretched to fill the side panel. Returned at 100% it would
    collapse to nothing inside a box sized in rem."""
    body = _fn("aiuiSplitClose")
    assert "s.frame.style.height = s.homeHeight" in body


# --- finding the chat, without naming Open WebUI's classes ----------------

def test_the_pane_is_found_rather_than_named():
    """Open WebUI's class names change between versions. The pane is
    reliably the nearest ancestor of the message list that also holds the
    message box.

    It asked for the two ids directly until 2026-11-05, which meant a
    rename broke the split view as well as the placer, in two places. It
    asks the accessors now, and they are the only functions that know
    those names.
    """
    body = _fn("aiuiChatPane")
    assert "aiuiScroller()" in body
    assert "aiuiComposer()" in body
    assert "node.contains(input)" in body
    assert "getElementById(" not in body, (
        "the split view is naming Open WebUI's markup again")


def test_no_pane_means_no_split():
    """Returning early lets the caller fall back. Shrinking something
    that is not the chat would move the whole page sideways."""
    body = _fn("aiuiSplitOpen")
    assert "if (!pane) return false;" in body


def test_the_caller_falls_back_rather_than_doing_nothing():
    """A control that silently does nothing is worse than one that does
    something smaller.

    Matched on the SHAPE of the call, not its whole text: the argument
    list grew when the pencil and the appearance panel started travelling
    with the app (2026-11-12), and an exact string would have failed for a
    change that left this behaviour exactly as it was.
    """
    src = _js()
    at = src.index("if (aiuiSplitOpen(")
    call = src[at:src.index(";", at) + 1]
    assert call.endswith(") return;"), (
        "the split is no longer used as the condition it returns on, so "
        "there is no fall-back when there is no chat pane to shrink")
    after = src[at:]
    assert "AIUI_APP_H_BIG" in after[:700]


# --- what is left in the thread -------------------------------------------

def test_the_message_leaves_a_chip_behind():
    """Otherwise the message becomes a blank gap and nothing says what the
    panel beside the chat belongs to."""
    src = _js()
    assert "showing beside the chat" in src
    body = _fn("aiuiShowAppInline")
    assert "box.appendChild(chip)" in body


def test_the_chip_puts_it_back():
    assert "chip.addEventListener('click', aiuiSplitClose)" in _js()


def test_the_chip_is_hidden_until_it_is_needed():
    body = _fn("aiuiShowAppInline")
    assert "display:none" in body


# --- getting out ----------------------------------------------------------

def test_there_are_three_ways_back():
    """The expand control again, the chip, and Escape. One way out of a
    thing covering half the window is not enough."""
    src = _js()
    assert "shut.addEventListener('click', aiuiSplitClose)" in src
    assert "chip.addEventListener('click', aiuiSplitClose)" in src
    assert "e.key === 'Escape'" in src


def test_escape_is_unhooked_when_it_closes():
    """Left bound, every later Escape anywhere in the app runs this."""
    assert "removeEventListener('keydown', s.onKey)" in _fn("aiuiSplitClose")


def test_only_one_app_is_beside_the_chat():
    """Two panels would stack on the same half of the window, and only
    the last would be reachable."""
    assert _fn("aiuiSplitOpen").lstrip().startswith("function aiuiSplitOpen")
    assert "aiuiSplitClose();" in _fn("aiuiSplitOpen")[:400]


def test_the_chat_gets_its_width_back():
    """Leaving the padding behind gives somebody half a chat and no way to
    work out why."""
    body = _fn("aiuiSplitClose")
    assert "s.pane.style.paddingRight = s.panePad" in body
