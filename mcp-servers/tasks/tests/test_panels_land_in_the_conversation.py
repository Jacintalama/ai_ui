"""Everything the page adds lands in the conversation.

Ralph, 2026-11-04, looking at the build box sitting under the message
input: "its a bugg fux this - it should be in the chat" / "not below in
the chat please fix".

The cause is one selector. Open WebUI 0.12 renders the thread as:

    <div id="messages-container" class="... flex flex-col-reverse ...">
      <div id="full-messages-container"> ...the messages... </div>

There are no per-message ids in this version. The only element whose id
starts with "message-" is "message-input-container", the COMPOSER. So
'[id^="message-"]' matched the input box and nothing else, and five
places relied on it:

- the typing line and the build line were inserted after the composer
- every panel went there too, outside the conversation
- the reload check compared the composer against itself and so never saw
  the thread change
- the scan for build links read the composer's markup, where there are
  none

Checked against the running Open WebUI bundle rather than guessed.
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


def test_nothing_looks_for_a_per_message_id_any_more():
    """Only the comment that explains why may mention it."""
    src = _js()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("//"))
    assert '[id^="message-"]' not in code


def test_the_thread_is_looked_for_in_more_than_one_way():
    """"full-messages-container" came from a SOURCE MAP, not from the
    markup this version renders, and it is not in the live page. Every
    panel fell through to the page body and landed under the message box,
    which is the bug this file is about, shipped twice."""
    body = _fn("aiuiThread")
    assert "full-messages-container" in body
    assert "getElementById('messages-container')" in body


def test_a_reversed_column_is_not_simply_appended_to():
    """The chat view renders the scroller as "flex flex-col-reverse", and
    in a reversed column the FIRST child is the one at the bottom.
    Appending would put the panel above every message: a different wrong
    place from the one being fixed."""
    src = _js()
    assert "function aiuiThreadIsReversed" in src
    body = _fn("aiuiPutUnderLastMessage")
    assert "thread.insertBefore(box, thread.firstChild)" in body


def test_reading_the_layout_cannot_throw():
    """getComputedStyle on a detached or cross-document element throws in
    some browsers, and this runs on every panel."""
    assert "try {" in _fn("aiuiThreadIsReversed")


def test_falling_back_to_the_page_says_so():
    """It fell back silently for two days and looked like a styling
    problem. The one place that knows the markup has moved should say."""
    assert "no chat thread found" in _js()


def test_a_panel_is_appended_to_the_thread():
    body = _fn("aiuiPutUnderLastMessage")
    assert "thread.appendChild(box)" in body


def test_the_body_stays_as_a_last_resort():
    """Better somewhere visible than nowhere, and it is the signal that
    this markup has moved again."""
    assert "document.body.appendChild(box)" in _fn("aiuiPutUnderLastMessage")


def test_the_lines_do_not_place_themselves():
    """The typing line and the build line each had their own copy of the
    broken placement. Two copies is two things to fix next time."""
    src = _js()
    assert src.count("aiuiPutUnderLastMessage(el);") == 2
    for name in ("aiuiBuildLine", "aiuiTyping"):
        try:
            body = _fn(name)
        except ValueError:
            continue
        assert "insertBefore" not in body, name


def test_the_reload_check_can_actually_change():
    """It compared the composer with itself, so it was always equal and
    the soft reload never fired."""
    src = _js()
    hit = src[src.index("function lastRowId"):]
    hit = hit[:hit.index("\n    }") + 6]
    assert "aiuiThread()" in hit
    assert "childElementCount" in hit


def test_the_reload_check_notices_a_reply_growing():
    """A reply streams in under the same element, so counting elements
    alone would miss a turn that adds no new row."""
    src = _js()
    hit = src[src.index("function lastRowId"):]
    hit = hit[:hit.index("\n    }") + 6]
    assert "textContent" in hit


def test_the_scan_reads_the_conversation():
    """It read the composer's markup, where a build link never appears."""
    src = _js()
    assert "aiuiBuildIdsIn(thread ? thread.innerHTML : '')" in src
