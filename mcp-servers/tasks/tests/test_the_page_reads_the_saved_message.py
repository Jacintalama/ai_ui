"""The page reads what a reply declares from the saved message (2026-11-09).

A declared artifact is a markdown link reference definition, on purpose: the
parser consumes it and the person never sees it. That means it is never in
the rendered page either, so a scan of the rendered page can only find
nothing. Measured live 2026-11-09 on a real build: the saved message held
"[aiui-artifact]: #app/kilometers-miles-converter-2c21", the page held
neither that nor a preview link, and the chat said "is built." with nothing
to look at, after a reload too. It had worked only while replies still
carried a link.

The real section of integrations-ui.js, under node, with the browser and the
network replaced.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")
START = "// ===== Build watcher ====="
END = "// ===== End build watcher ====="
BUILD = "0f2b8c1e-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
VIDEO = "55785e0a-a4e4-4d4c-a2d5-5747c8899019"

STUBS = r"""
var drawn = [], fetches = 0, stored = null, failNext = false, polled = [], videoPolls = [], videoShown = [], jobFetches = [];
var nowS = Math.floor(Date.now() / 1000);
function msg(id, role, content, ts) { return {id: id, role: role, content: content, timestamp: ts === undefined ? nowS : ts, done: true}; }
function setChat(list) {
  var messages = {}, prev = null;
  list.forEach(function (m) { m.parentId = prev; messages[m.id] = m; prev = m.id; });
  stored = {chat: {history: {messages: messages, currentId: prev}}};
}
function aiuiChainFromHistory(history) {
  var msgs = history.messages, id = history.currentId, chain = [];
  for (var g = 0; id && msgs[id] && g < 500; g++) { chain.unshift(msgs[id]); id = msgs[id].parentId; }
  return chain;
}
function aiuiFetchChat() {
  fetches++;
  if (failNext) { failNext = false; return Promise.reject(new Error('down')); }
  return Promise.resolve(JSON.parse(JSON.stringify(stored)));
}
function aiuiSaveChat() { return Promise.resolve(); }
function aiuiSoftReload() {}
function aiuiChatIdFromUrl() { return 'chat-1'; }
function aiuiUuid() { return 'new-1'; }
function aiuiAuthHeaders() { return {}; }
var location = {origin: 'https://x.test', pathname: '/c/chat-1'};
var document = {getElementById: function () { return null; }, querySelectorAll: function () { return []; }};
"""

OVERRIDES = r"""
function aiuiShowAppInline(chatId, slug, messageId) { drawn.push([slug, messageId]); }
function aiuiPollBuild(chatId, id) { polled.push(id); }
function aiuiPollVideo(chatId, id) { videoPolls.push(id); }
function aiuiShowVideoInline(chatId, job, id, messageId) { videoShown.push([id, messageId]); }
function fetch(url) { jobFetches.push(url); return Promise.resolve({ok: true, json: function () { return Promise.resolve({status: 'done', share_url: 'https://x.test/api/video-jobs/v'}); }}); }
function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }
"""


def _section():
    with open(JS, encoding="utf-8") as fh:
        js = fh.read()
    start, end = js.index(START), js.index(END)
    return js[start:end]


def _node(script, overrides=OVERRIDES):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    body = (STUBS + _section() + overrides
            + "\n(async function () {\n" + script
            + "\n})().catch(function (e) { console.log('THREW ' + e.stack); process.exit(1); });")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        path = fh.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(path)
    assert out.returncode == 0, out.stdout + out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_an_app_is_found_in_the_saved_message_with_the_message_that_declared_it():
    got = _node(r"""
    var apps = aiuiSavedApps([msg('u', 'user', 'build it'),
                              msg('a1', 'assistant', 'Building.'),
                              msg('a2', 'assistant', 'kilo-2c21 is built.\n\n[aiui-artifact]: #app/kilo-2c21')]);
    console.log(JSON.stringify(apps));""")
    assert got == [{"slug": "kilo-2c21", "messageId": "a2"}]


def test_the_last_message_to_mention_an_app_is_where_it_goes():
    got = _node(r"""
    var apps = aiuiSavedApps([msg('a1', 'assistant', '[aiui-artifact]: #app/shop'),
                              msg('a2', 'assistant', 'x\n\n[aiui-artifact]: #app/blog'),
                              msg('a3', 'assistant', 'again\n\n[aiui-artifact]: #app/shop')]);
    console.log(JSON.stringify(apps));""")
    assert got == [{"slug": "shop", "messageId": "a3"},
                   {"slug": "blog", "messageId": "a2"}]


def test_what_a_person_typed_does_not_draw_anything():
    got = _node(r"""
    console.log(JSON.stringify(aiuiSavedApps([msg('u', 'user', '[aiui-artifact]: #app/evil')])));""")
    assert got == []


def test_a_rendered_page_with_no_marker_still_gets_its_panel():
    """The bug, through the read: nothing in the page, the marker only in the
    saved message."""
    got = _node(r"""
    setChat([msg('a', 'assistant', 'kilo-2c21 is built.\n\n[aiui-artifact]: #app/kilo-2c21')]);
    await aiuiReadSaved('chat-1', '<p>kilo-2c21 is built.</p>');
    await tick();
    console.log(JSON.stringify({drawn: drawn, fetches: fetches}));""")
    assert got == {"drawn": [["kilo-2c21", "a"]], "fetches": 1}


def test_an_unchanged_thread_is_not_fetched_again_but_is_redrawn():
    """A scan runs every few seconds. Open WebUI rebuilds a message and throws
    our panel away, so each scan redraws; only a change costs a fetch."""
    got = _node(r"""
    setChat([msg('a', 'assistant', '[aiui-artifact]: #app/kilo-2c21')]);
    await aiuiReadSaved('chat-1', 'same'); await tick();
    await aiuiReadSaved('chat-1', 'same'); await tick();
    await aiuiReadSaved('chat-1', 'same'); await tick();
    console.log(JSON.stringify({fetches: fetches, draws: drawn.length}));""")
    assert got["fetches"] == 1
    assert got["draws"] >= 3


def test_a_thread_still_changing_waits_until_it_holds_still():
    """Streaming changes the page every scan and the message is not saved
    yet, so a fetch then is wasted and reads the wrong thing."""
    got = _node(r"""
    setChat([msg('a', 'assistant', 'one')]);
    await aiuiReadSaved('chat-1', 'x'); await tick();
    var first = fetches;
    await aiuiReadSaved('chat-1', 'xy'); await tick();
    var changing = fetches;
    setChat([msg('a', 'assistant', 'done\n\n[aiui-artifact]: #app/shop')]);
    await aiuiReadSaved('chat-1', 'xy'); await tick();
    console.log(JSON.stringify({first: first, changing: changing, settled: fetches, drawn: drawn}));""")
    assert got["first"] == 1, "the first look at a chat does not wait"
    assert got["changing"] == 1
    assert got["settled"] == 2
    assert got["drawn"] == [["shop", "a"]]


def test_a_failed_read_tries_again():
    got = _node(r"""
    setChat([msg('a', 'assistant', '[aiui-artifact]: #app/shop')]);
    failNext = true;
    await aiuiReadSaved('chat-1', 'same'); await tick();
    var after_failure = drawn.length;
    await aiuiReadSaved('chat-1', 'same'); await tick();
    console.log(JSON.stringify({after_failure: after_failure, drawn: drawn}));""")
    assert got["after_failure"] == 0
    assert got["drawn"][0] == ["shop", "a"]


def test_closing_a_build_reads_again_at_once():
    """The closing message is what declares the app, and the thread may not
    have changed length by the time the next scan looks."""
    got = _node(r"""
    setChat([msg('a', 'assistant', 'Building.')]);
    await aiuiReadSaved('chat-1', 'same'); await tick();
    setChat([msg('a', 'assistant', 'x'), msg('b', 'assistant', '[aiui-artifact]: #app/shop')]);
    await aiuiCloseWith('chat-1', ['nope'], 'closed');
    await aiuiReadSaved('chat-1', 'same'); await tick();
    console.log(JSON.stringify({drawn: drawn}));""")
    assert ["shop", "b"] in got["drawn"]


def test_moving_to_another_chat_forgets_the_last_one():
    got = _node(r"""
    setChat([msg('a', 'assistant', '[aiui-artifact]: #app/shop')]);
    await aiuiReadSaved('chat-1', 'same'); await tick();
    setChat([msg('c', 'assistant', 'nothing here')]);
    drawn.length = 0;
    await aiuiReadSaved('chat-2', 'same');
    var redrawn_old = drawn.length;
    await tick();
    console.log(JSON.stringify({redrawn_old: redrawn_old, drawn: drawn, fetches: fetches}));""")
    assert got == {"redrawn_old": 0, "drawn": [], "fetches": 2}


def test_a_build_declared_only_by_marker_is_watched():
    got = _node(r"""
    setChat([msg('a', 'assistant', 'Building it now.\n\n[aiui-artifact]: #build/%s')]);
    await aiuiReadSaved('chat-1', 'page'); await tick();
    console.log(JSON.stringify(polled));""" % BUILD)
    assert got == [BUILD]


def test_an_old_build_is_not_watched():
    got = _node(r"""
    setChat([msg('a', 'assistant', '[aiui-artifact]: #build/%s', 1000)]);
    await aiuiReadSaved('chat-1', 'page'); await tick();
    console.log(JSON.stringify(polled));""" % BUILD)
    assert got == []


def test_a_chat_with_a_video_and_no_build_is_watched():
    """aiuiWatchVideos used to sit behind 'if (!fresh.length) return', so a
    video on its own was never followed."""
    got = _node(r"""
    setChat([msg('a', 'assistant', 'Filming.\n\n[aiui-artifact]: #video/%s')]);
    await aiuiReadSaved('chat-1', 'page'); await tick();
    console.log(JSON.stringify({videos: videoPolls, builds: polled}));""" % VIDEO)
    assert got == {"videos": [VIDEO], "builds": []}


def test_a_finished_video_comes_back_in_its_closing_message():
    """The player is drawn at the moment the video finishes, and the soft
    reload after the closing message throws it away."""
    got = _node(r"""
    setChat([msg('a', 'assistant', 'Filming.\n\n[aiui-artifact]: #video/%(v)s'),
             msg('b', 'assistant', 'It is ready.\n\n[aiui-video-done]: #%(v)s')]);
    await aiuiReadSaved('chat-1', 'page'); await tick(); await tick(); await tick();
    await aiuiReadSaved('chat-1', 'page'); await tick();
    console.log(JSON.stringify({shown: videoShown[0], asked: jobFetches.length}));""" % {"v": VIDEO})
    assert got["shown"] == [VIDEO, "b"]
    assert got["asked"] == 1, "the job is asked for once, not on every scan"


def test_the_closing_message_leaves_out_the_link_when_the_player_shows():
    """The player sits in this reply, so the address was only a very long
    line above it, with its token printed for anyone to read."""
    got = _node(r"""
    console.log(JSON.stringify(aiuiVideoOutcome({status: 'done', title: 'Tour',
      output_available: true,
      share_url: location.origin + '/api/video-jobs/abc/share?token=t'}, 'v1')));""")
    assert got == "Tour is ready.\n\n[aiui-video-done]: #v1"


def test_the_closing_message_keeps_the_link_when_the_player_cannot_show():
    """A share link on another host never reaches the player, so the link
    is the only way left to the video."""
    got = _node(r"""
    console.log(JSON.stringify(aiuiVideoOutcome({status: 'done', title: 'Tour',
      output_available: true, share_url: 'https://elsewhere.test/v.mp4'}, 'v1')));""")
    assert "Watch it here: https://elsewhere.test/v.mp4" in got


POLL_OVERRIDES = r"""
var lines = [], theJob = null;
function aiuiBuildLine(chatId, text) { lines.push(text); }
function aiuiClearBuildLine() {}
function aiuiCloseWith() { return Promise.resolve(true); }
function aiuiShowVideoInline() {}
function fetch() { return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(theJob); }}); }
function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }
AIUI_VIDEO_GIVE_UP_MS = -1;
"""


def _line_for(job):
    """What the real poller says about a job, through the real poller."""
    got = _node(r"""
    theJob = %s;
    aiuiPollVideo('chat-1', 'v1', Date.now() - 120000);
    await tick(); await tick();
    console.log(JSON.stringify(lines));""" % json.dumps(job),
                overrides=POLL_OVERRIDES)
    assert len(got) == 1, got
    return got[0]


def test_a_video_waiting_with_nothing_ahead_is_not_said_to_be_rendering():
    """The worker leaves a job queued while the server is short of memory,
    with nothing ahead of it."""
    line = _line_for({"status": "queued", "queue_position": 0})
    assert "Rendering" not in line
    assert line.startswith("Waiting to start rendering")


def test_a_video_behind_others_says_how_many():
    line = _line_for({"status": "queued", "queue_position": 2})
    assert line == "Waiting to render, 2 ahead of it."


def test_a_video_really_rendering_says_so():
    line = _line_for({"status": "rendering"})
    assert line == "Rendering the video, 2 min so far."


def test_a_finished_video_is_not_drawn_before_its_closing_message():
    """Opening a chat, the poller can finish before any reply is on screen,
    and the fallback then is the end of the page, under the message box.
    Measured on the live site 2026-11-09: the player sat there with the
    closing message saying "is ready" and no way to reach it. The saved read
    draws it, in the closing message, once that message exists."""
    got = _node(r"""
    var shown = [], closes = [];
    aiuiShowVideoInline = function () { shown.push(1); };
    aiuiCloseWith = function (c, m, t) { closes.push(t); return Promise.resolve(true); };
    theJob = {status: 'done', title: 'Tour', output_available: true,
              share_url: location.origin + '/api/video-jobs/abc'};
    aiuiPollVideo('chat-1', 'v1', Date.now());
    await tick(); await tick();
    console.log(JSON.stringify({shown: shown.length, closes: closes}));""",
                overrides=POLL_OVERRIDES)
    assert got == {"shown": 0,
                   "closes": ["Tour is ready.\n\n[aiui-video-done]: #v1"]}


LINE_OVERRIDES = r"""
var made = [], reply = null;
function aiuiLastReplyBody() { return reply; }
function aiuiThread() { return {querySelector: function () { return null; }, appendChild: function () {}}; }
function aiuiPutUnderLastMessage(el) { made.push(el); }
document.createElement = function () { return {style: {}}; };
"""


def test_the_waiting_line_waits_for_the_reply_to_be_on_screen():
    """The same race as the player: drawn at the end of the page it is
    never seen, and it is never moved because it already exists."""
    got = _node(r"""
    aiuiBuildLine('chat-1', 'Waiting to start rendering, 1 min so far.');
    console.log(JSON.stringify(made.length));""", overrides=LINE_OVERRIDES)
    assert got == 0


def test_the_waiting_line_is_drawn_once_the_reply_is_there():
    got = _node(r"""
    reply = {};
    aiuiBuildLine('chat-1', 'Waiting to start rendering, 1 min so far.');
    console.log(JSON.stringify(made.map(function (e) { return e.textContent; })));""",
                overrides=LINE_OVERRIDES)
    assert got == ["Waiting to start rendering, 1 min so far."]


def _source():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def test_the_scan_reads_the_saved_message_before_it_can_return_early():
    src = _source()
    watcher = src[src.index("function aiuiWatchBuilds()"):]
    watcher = watcher[:watcher.index("// ===== Video watcher =====")]
    assert watcher.index("aiuiReadSaved(chatId, html)") < watcher.index(
        "if (!fresh.length) return;")


def test_something_scans_when_the_page_has_gone_quiet():
    """The scan ran only on a page mutation, and a thread that has finished
    changing produces none, so the last change could go unread for ever."""
    assert "setInterval(aiuiWatchBuilds" in _source()
