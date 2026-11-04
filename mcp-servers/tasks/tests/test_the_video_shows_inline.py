"""A finished video plays in the chat, instead of being asked after.

make_video answers in seconds with "it is rendering ... Its id is <id>"
and then renders for minutes. The chat said nothing more unless somebody
asked for it by that id, which is the gap the build watcher closed and
this closes the same way.

Structural, like the other tests of this file, which is vanilla JS served
as a static asset. The server half, the disposition, is tested for real
because that one is a header and can be.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _section(name):
    """One function's body.

    Stops at the next function OR at the end of its watcher section. The
    last function in a section has no next one, and an index() that
    assumes otherwise raises instead of failing as a test, which reads
    like the code is broken when the helper is.
    """
    src = _js()
    start = src.index("function " + name)
    ends = [src.find(mark, start + 10)
            for mark in ("\n  function ", "\n  // ===== End")]
    return src[start:min(e for e in ends if e != -1)]


# --- the header that makes playing it possible ----------------------------

def test_the_video_is_served_to_be_watched_not_saved():
    """The link is handed to people as "Watch it here", and an attachment
    disposition makes a browser save the file instead of playing it. It is
    also what lets the chat show it: a <video> fetching an attachment
    relies on browsers ignoring a header they may honour."""
    from starlette.responses import FileResponse
    here = os.path.join(os.path.dirname(__file__), "..", "routes_video.py")
    with open(here, encoding="utf-8") as fh:
        src = fh.read()
    assert 'content_disposition_type="inline"' in src

    played = FileResponse(here, media_type="video/mp4", filename="x.mp4",
                          content_disposition_type="inline")
    assert dict(played.headers)["content-disposition"].startswith("inline")


def test_saving_it_deliberately_still_gets_a_name():
    """inline without a filename gives somebody a job id and no extension
    when they do choose to save it."""
    here = os.path.join(os.path.dirname(__file__), "..", "routes_video.py")
    with open(here, encoding="utf-8") as fh:
        src = fh.read()
    assert 'filename=f"{job_id}.mp4"' in src


# --- what the page plays ---------------------------------------------------

def test_only_our_own_host_is_ever_played():
    """The src comes from a row and goes into a media element. A link in a
    row is not a reason to fetch somebody else's host."""
    body = _section("aiuiShowVideoInline")
    assert "location.origin + '/api/video-jobs/'" in body
    assert "indexOf(" in body and "!== 0) return" in body


def test_it_is_drawn_once_per_video():
    assert "getElementById(box_id)" in _section("aiuiShowVideoInline")


def test_it_does_not_fetch_the_whole_film_to_show_a_frame():
    """A chat with several finished videos in it would otherwise pull every
    one of them on open."""
    assert "preload" in _section("aiuiShowVideoInline")


def test_only_a_finished_video_is_shown():
    src = _js()
    assert re.search(r"if \(String\(job\.status \|\| ''\) === 'done'\)"
                     r" aiuiShowVideoInline", src)


# --- the watching ----------------------------------------------------------

def test_the_id_is_read_out_of_what_the_tool_actually_writes():
    """make_video ends with "Its id is <uuid>". If that sentence changes,
    this watcher stops seeing anything, silently."""
    body = _js()
    assert re.search(r"\[Ii\]ts id is \(\[0-9a-f\]\{8\}", body)
    tool = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "open-webui-functions", "video_tool.py")
    with open(tool, encoding="utf-8") as fh:
        assert "Its id is " in fh.read(), (
            "the tool no longer writes the sentence the page looks for")


def test_a_video_is_reported_once():
    """Its own marker, not the build one, so a video and a build in the
    same chat cannot close each other."""
    src = _js()
    # The markers became markdown link reference definitions on
    # 2026-11-04, because Open WebUI escapes the HTML in a message and was
    # printing the old HTML comment to the person under every finished
    # build. What this test is about is unchanged: the two kinds are
    # DISTINCT, so a video and a build in one chat cannot close each
    # other.
    assert "aiui-video-done" in src
    assert "aiui-build-done" in src
    assert "[aiui-video-done]: #" in src


def test_both_watchers_share_one_write():
    """Two copies of "append a message without racing Open WebUI's own
    save" is two chances to get that wrong."""
    src = _js()
    assert src.count("function aiuiCloseWith(") == 1
    assert "aiuiCloseWith(chatId, [aiuiBuildDoneMarker(id)," in src
    assert "aiuiCloseWith(chatId, aiuiVideoDoneMarker(id), text);" in src


def test_the_scan_reads_the_chat_once():
    """The build watcher already fetched it. A second fetch would double
    the cost of every scan for nothing."""
    src = _js()
    # Twice: the definition and the one call. Asserting the string is
    # merely PRESENT passes on the definition alone, so deleting the call
    # reads as fine while no video is ever watched. That is the third time
    # today a presence check has passed for the wrong reason, which is why
    # this one counts.
    assert src.count("aiuiWatchVideos(chain, chatId)") == 2
    assert _section("aiuiWatchVideos").count("aiuiFetchChat") == 0


def test_an_old_video_is_not_reported_on_first_open():
    """Otherwise opening a chat posts a pile of "is ready" for videos from
    weeks ago, which is what AIUI_BUILD_RECENT_S exists to stop."""
    assert "AIUI_BUILD_RECENT_S" in _section("aiuiWatchVideos")
