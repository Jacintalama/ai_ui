"""A running build is watchable in the chat, not behind a link.

Ralph, 2026-11-04, during the first real build after the progress line
shipped: "it should inline in the chat should see the process or to watch
instead of link only!!"

The reply carried a link to preview.html and nothing else, so watching a
build meant leaving the conversation. The build now appears under the
reply while it runs, and is replaced by the finished app.

What is embedded is preview.html itself. That page already draws the live
build: the overlay, the progress bar, the status chip and the history. A
second implementation of all that, kept in step with the first, is the
kind of thing that is right for about a week.
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


def test_the_build_is_shown_while_it_runs():
    body = _fn("aiuiShowBuildInline")
    assert "preview.html?task=" in body
    assert "iframe" in body


def test_it_is_the_existing_preview_page_not_a_second_one():
    """preview.html already draws the overlay, the progress bar, the
    status chip and the history. Rebuilding that in the chat means two
    things to keep in step."""
    body = _fn("aiuiShowBuildInline")
    assert "/tasks/static/preview.html" in body
    for invented in ("progress-bar", "status-chip", "innerHTML = "):
        assert invented not in body


def test_it_is_drawn_once_per_build():
    """The watcher polls every ten seconds."""
    assert "getElementById(aiuiBuildBoxId(id))" in _fn("aiuiShowBuildInline")


def test_it_goes_away_when_the_build_settles():
    """What replaces it is the app itself. Leaving a finished build's
    frame above that is the same thing twice."""
    src = _js()
    assert "function aiuiHideBuildInline" in src
    hidden = src.index("aiuiHideBuildInline(id);")
    closed = src.index("return aiuiCloseBuild(chatId, id, text);", hidden)
    assert hidden < closed


def test_it_is_drawn_only_after_the_task_answered():
    """Drawing it when the watch STARTS would put a frame on screen for a
    build that turns out to be somebody else's or already gone, both of
    which the poll answers 403 or 404 to."""
    body = _fn("aiuiPollBuild")
    shown = body.index("aiuiShowBuildInline(chatId, id)")
    guard = body.index("if (r.status === 403 || r.status === 404)")
    assert guard < shown


def test_the_frame_cannot_navigate_the_chat():
    # The ATTRIBUTE, not the file: the comment above it says "No
    # allow-top-navigation", which contains the phrase and failed this
    # test first time.
    body = _fn("aiuiShowBuildInline")
    sandbox = re.search(r"setAttribute\('sandbox', '([^']*)'\)", body)
    assert sandbox, "the frame has no sandbox at all"
    assert "allow-top-navigation" not in sandbox.group(1)


def test_it_keeps_its_own_origin():
    """preview.html reads the signed-in token to watch a build. A sandbox
    without allow-same-origin gives it an opaque origin and no token, so
    the frame would sit there unable to load anything."""
    # The attribute again, for the same reason: the comment above it
    # explains why allow-same-origin is there, so a check over the whole
    # function passes with the flag removed.
    body = _fn("aiuiShowBuildInline")
    sandbox = re.search(r"setAttribute\('sandbox', '([^']*)'\)", body)
    assert sandbox and "allow-same-origin" in sandbox.group(1)


def test_there_is_still_a_way_out_to_a_tab():
    assert "Open in a new tab" in _fn("aiuiShowBuildInline")


# --- the step wording this sits next to ------------------------------------

def test_the_line_says_what_the_build_is_doing():
    """Measured on a real build the same day: the row held build_step
    'building' and the API served build_step_said 'Writing the code'. The
    page must read that rather than counting minutes at it."""
    body = _fn("aiuiPollBuild")
    assert "task.build_step_said" in body


def test_minutes_remain_the_fallback():
    """A build between steps, or one that predates this, has no step. An
    empty line would read as nothing happening."""
    body = _fn("aiuiPollBuild")
    assert "Still building, " in body


# --- one way to put a panel under a reply ----------------------------------

def test_the_three_panels_share_one_insert():
    """The build, the finished app and a video all sit under a reply.
    Three copies of "find the last message" drift."""
    src = _js()
    assert src.count("function aiuiPutUnderLastMessage") == 1
    assert src.count("aiuiPutUnderLastMessage(box);") == 3
    # Not a count over the whole file: reading the message list is a
    # perfectly ordinary thing to do elsewhere, and there are five other
    # uses. What matters is that none of the three PANELS does its own.
    for panel in ("aiuiShowBuildInline", "aiuiShowAppInline",
                  "aiuiShowVideoInline"):
        assert "querySelectorAll" not in _fn(panel), panel


# --- the marker nobody should have to look at ------------------------------

def test_the_marker_is_invisible_in_a_rendered_message():
    """Open WebUI renders a message as markdown and escapes the HTML in
    it, so "<!-- aiui:build-done ... -->" was PRINTED to the person under
    every finished build from the day the watcher shipped. Ralph saw it
    on his first real build.

    "[name]: #id" is a markdown link reference definition. The parser
    consumes it and emits nothing, which is what a marker is for.
    """
    src = _js()
    assert "'[aiui-build-done]: #'" in src
    assert "'[aiui-video-done]: #'" in src


def test_the_marker_still_lives_in_the_message():
    """Not in this page's memory. It has to survive a reload and be seen
    by another tab, which is the whole reason it is in the text."""
    body = _fn("aiuiBuildOutcome")
    assert "aiuiBuildDoneMarker(id)" in body


def test_the_old_marker_is_still_recognised():
    """Builds closed before today carry the HTML comment. Forgetting it
    would post "is built" again under every finished build already in
    somebody's history."""
    src = _js()
    assert "function aiuiLegacyBuildMarker" in src
    assert "<!-- aiui:build-done " in src
    assert "aiuiLegacyBuildMarker(id)" in _fn("aiuiBuildIsClosed")


def test_closing_checks_the_old_shape_too():
    """Not only the scan. Two tabs can race, and the one that writes must
    see a close the other wrote under either shape."""
    assert "aiuiLegacyBuildMarker(id)" in _fn("aiuiCloseBuild")


def test_one_marker_or_several_are_both_accepted():
    """The video watcher passes a single string. Breaking that while
    fixing the build one would stop every video being reported."""
    body = _fn("aiuiIsClosed")
    assert "typeof markers === 'string'" in body
