"""What the chat shows while something is being made (2026-11-10).

Lukas, 2026-11-10:

- videos: "some nicer loading thing for the user". The chat showed one grey
  line, "Waiting to start rendering, 1 min so far."
- builds: "maybe some loading or just showing that it's building", and the
  preview "sometimes didn't show up". The build's step panel had the race
  the video player had on 2026-11-09: drawn before any reply was on screen,
  it went to the end of the page and stayed there.
- the app itself: "it needs an embed, which takes time". Until the app's
  page loads, its panel was a blank white box.
- the side view "sometimes shows you the mobile version because it's too
  narrow", with a hamburger menu instead of the menu items. The side panel
  is half the window, about 700 px on a laptop, under most sites' breakpoint.

The real section of integrations-ui.js runs under node, with a small fake
DOM standing in for the browser.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")
START = "// ===== Build watcher ====="
END = "// ===== End build watcher ====="

DOM = r"""
function El(tag) { this.tagName = tag; this.children = []; this.style = {}; this.attrs = {};
  this.listeners = {}; this.parentNode = null; this.innerHTML = ''; this.textContent = '';
  this.id = ''; this.clientWidth = 0; this.clientHeight = 0; this.className = ''; }
El.prototype.appendChild = function (c) { if (c.parentNode) c.parentNode.removeChild(c);
  c.parentNode = this; this.children.push(c); return c; };
El.prototype.removeChild = function (c) { var i = this.children.indexOf(c);
  if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.addEventListener = function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.removeEventListener = function (t, f) { var l = this.listeners[t] || []; var i = l.indexOf(f); if (i >= 0) l.splice(i, 1); };
El.prototype.fire = function (t) { (this.listeners[t] || []).slice().forEach(function (f) { f({}); }); };
El.prototype.querySelector = function () { return null; };
// The real DOM has this on every element, and code that measures a
// box is entitled to assume it. A stub without it is the harness
// being less than the thing it stands for.
El.prototype.getBoundingClientRect = function () {
  return { width: this.clientWidth || 0, height: this.clientHeight || 0,
           top: 0, left: 0, right: 0, bottom: 0 }; };
El.prototype.contains = function () { return false; };
var document = { head: new El('head'), body: new El('body'), listeners: {},
  createElement: function (t) { return new El(t); },
  getElementById: function (id) {
    function walk(n) { if (n.id === id) return n;
      for (var i = 0; i < n.children.length; i++) { var f = walk(n.children[i]); if (f) return f; }
      return null; }
    return walk(document.head) || walk(document.body); },
  querySelectorAll: function () { return []; },
  addEventListener: function (t, f) { (document.listeners[t] = document.listeners[t] || []).push(f); },
  removeEventListener: function (t, f) { var l = document.listeners[t] || []; var i = l.indexOf(f); if (i >= 0) l.splice(i, 1); } };
var window = { listeners: {},
  addEventListener: function (t, f) { (window.listeners[t] = window.listeners[t] || []).push(f); },
  removeEventListener: function (t, f) { var l = window.listeners[t] || []; var i = l.indexOf(f); if (i >= 0) l.splice(i, 1); } };
var location = {origin: 'https://x.test', pathname: '/c/chat-1'};
function aiuiChatIdFromUrl() { return 'chat-1'; }
function aiuiAuthHeaders() { return {}; }
function aiuiFetchChat() { return Promise.resolve({chat: {history: {messages: {}, currentId: null}}}); }
function aiuiSaveChat() { return Promise.resolve(); }
function aiuiSoftReload() {}
function aiuiUuid() { return 'u'; }
function aiuiChainFromHistory() { return []; }
"""

AFTER = r"""
var reply = null;
function aiuiLastReplyBody() { return reply; }
function aiuiPutUnderLastMessage(el) { (reply || document.body).appendChild(el); }
function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }
"""


def _section():
    with open(JS, encoding="utf-8") as fh:
        js = fh.read()
    return js[js.index(START):js.index(END)]


def _node(script):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    body = (DOM + _section() + AFTER + "\n(async function () {\n" + script
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


def _source():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    src = _source()
    start = src.index("function " + name + "(")
    nxt = src.find("\n  function ", start + 10)
    return src[start:nxt if nxt != -1 else len(src)]


# --- video: the steps, not one line ------------------------------------------

def test_each_video_status_marks_its_step():
    got = _node(r"""
    var out = {};
    ['queued', 'scripting', 'voicing', 'rendering'].forEach(function (s) {
      out[s] = aiuiVideoSteps({status: s}).map(function (r) { return r.state; });
    });
    console.log(JSON.stringify(out));""")
    assert got == {"queued": ["working", "waiting", "waiting"],
                   "scripting": ["done", "working", "waiting"],
                   "voicing": ["done", "done", "working"],
                   "rendering": ["done", "done", "working"]}


def test_the_video_panel_waits_for_a_reply_to_be_on_screen():
    got = _node(r"""
    var drew = aiuiVideoPanel('chat-1', 'v1', {status: 'queued', queue_position: 0}, 1);
    console.log(JSON.stringify({drew: drew, body: document.body.children.length}));""")
    assert got == {"drew": False, "body": 0}


def test_the_video_panel_shows_the_steps_and_where_it_is():
    got = _node(r"""
    reply = new El('div'); document.body.appendChild(reply);
    var drew = aiuiVideoPanel('chat-1', 'v1', {status: 'queued', queue_position: 2}, 3);
    var el = document.getElementById('aiui-video-steps-v1');
    console.log(JSON.stringify({drew: drew, inReply: el.parentNode === reply, html: el.innerHTML}));""")
    assert got["drew"] is True and got["inReply"] is True
    html = got["html"]
    for said in ("In the queue", "Writing the script", "Recording the voice and rendering",
                 "Waiting to render, 2 ahead of it.", "Working on it"):
        assert said in html, said
    assert "aiui-working" in html, "the step in progress moves"


def test_the_video_panel_is_drawn_once_and_updated():
    got = _node(r"""
    reply = new El('div'); document.body.appendChild(reply);
    aiuiVideoPanel('chat-1', 'v1', {status: 'queued'}, 1);
    aiuiVideoPanel('chat-1', 'v1', {status: 'rendering'}, 4);
    var el = document.getElementById('aiui-video-steps-v1');
    console.log(JSON.stringify({count: reply.children.length, html: el.innerHTML}));""")
    assert got["count"] == 1
    assert "Rendering the video, 4 min so far." in got["html"]


def test_the_poller_draws_the_panel_and_clears_it_when_done():
    got = _node(r"""
    reply = new El('div'); document.body.appendChild(reply);
    var answers = [{status: 'scripting'}, {status: 'done', title: 'Tour', output_available: false}];
    fetch = function () { var j = answers.shift();
      return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(j); }}); };
    aiuiCloseWith = function () { return Promise.resolve(true); };
    AIUI_VIDEO_POLL_MS = 40;
    aiuiPollVideo('chat-1', 'v1', Date.now());
    await tick(); await tick();
    var during = !!document.getElementById('aiui-video-steps-v1');
    await new Promise(function (r) { setTimeout(r, 120); });
    console.log(JSON.stringify({during: during, after: !!document.getElementById('aiui-video-steps-v1'),
                                line: !!document.getElementById('aiui-build-line')}));""")
    assert got == {"during": True, "after": False, "line": False}


def test_motion_stops_for_people_who_ask_for_less():
    got = _node(r"""
    aiuiMotion(); aiuiMotion();
    var st = document.getElementById('aiui-motion');
    console.log(JSON.stringify({n: document.head.children.length, css: st.textContent}));""")
    assert got["n"] == 1
    assert "prefers-reduced-motion: reduce" in got["css"]
    assert "animation:none" in got["css"].replace(" ", "")


# --- build: the panel waits for a reply too -----------------------------------

def test_the_build_steps_wait_for_a_reply_to_be_on_screen():
    got = _node(r"""
    AIUI_STEPS.agent = [{key: 'plan', said: 'Planning'}, {key: 'write', said: 'Writing'}];
    var drew = aiuiStepPanel('chat-1', {build_lane: 'agent', build_step: 'plan'}, 1);
    console.log(JSON.stringify({drew: drew, body: document.body.children.length}));""")
    assert got == {"drew": False, "body": 0}


def test_the_build_steps_move_while_working():
    got = _node(r"""
    reply = new El('div'); document.body.appendChild(reply);
    AIUI_STEPS.agent = [{key: 'plan', said: 'Planning'}, {key: 'write', said: 'Writing'}];
    var drew = aiuiStepPanel('chat-1', {build_lane: 'agent', build_step: 'write'}, 2);
    console.log(JSON.stringify({drew: drew, html: document.getElementById('aiui-steps').innerHTML}));""")
    assert got["drew"] is True
    assert "aiui-working" in got["html"]


def test_the_build_poller_draws_nothing_until_a_reply_is_there():
    """Its fallback, the embedded build page, would land at the end of the
    page the same way."""
    poll = _fn("aiuiPollBuild")
    guard = poll.index("if (!aiuiLastReplyBody()) return;")
    assert guard < poll.index("aiuiStepPanel(chatId, task, mins)")
    assert "if (!aiuiLastReplyBody()) return;" in _fn("aiuiShowBuildInline")


# --- the app: loading, then the app --------------------------------------------

def test_an_app_shows_loading_until_its_page_has_loaded():
    """It covers the frame while the app's page loads, and goes on load.

    What it SAYS changed on 2026-11-11. It used to be a flat dark box
    reading "Loading the app", which had motion but looked nothing like
    the thing about to replace it, so it read as a broken panel rather
    than a loading one. It is the shape of a page now: shimmer blocks for
    a nav, a heading and some lines.

    The words are gone on purpose, not lost. A panel that announces its
    own loading before anything is wrong is noise, so the sentence about
    opening it in a new tab waits until it HAS been slow, which is the
    next test.
    """
    got = _node(r"""
    var wrap = new El('div'), frame = new El('iframe');
    wrap.appendChild(frame);
    var cover = aiuiCoverWhileLoading(wrap, frame);
    function shimmers(el) {
      var n = el.className === 'aiui-shimmer' ? 1 : 0;
      el.children.forEach(function (c) { n += shimmers(c); });
      return n;
    }
    var before = {there: cover.parentNode === wrap, blocks: shimmers(cover)};
    frame.fire('load');
    console.log(JSON.stringify({before: before, after: cover.parentNode === wrap}));""")
    assert got["before"]["there"] is True
    assert got["before"]["blocks"] >= 3, (
        "a page-shaped skeleton needs more than one block")
    assert got["after"] is False


def test_an_app_that_is_slow_says_where_else_to_look():
    """Only once it has been slow. Before that the skeleton is the whole
    message and a sentence would be noise."""
    got = _node(r"""
    AIUI_COVER_SLOW_MS = 1;
    var wrap = new El('div'), frame = new El('iframe');
    wrap.appendChild(frame);
    var cover = aiuiCoverWhileLoading(wrap, frame);
    function said(el) {
      if (el.textContent) return el.textContent;
      var out = '';
      el.children.forEach(function (c) { out = out || said(c); });
      return out;
    }
    var quiet = said(cover);
    await new Promise(function (r) { setTimeout(r, 30); });
    console.log(JSON.stringify({quiet: quiet, slow: said(cover)}));""")
    assert got["quiet"] == "", "it spoke before anything was wrong"
    assert "new tab" in got["slow"]


def test_the_app_panel_uses_the_cover():
    body = _fn("aiuiShowAppInline")
    assert "aiuiCoverWhileLoading(" in body


# --- the side view: the desktop layout ----------------------------------------

def test_a_narrow_side_panel_lays_the_app_out_as_a_desktop():
    got = _node(r"""
    console.log(JSON.stringify([aiuiDesktopFit(700, 900), aiuiDesktopFit(1400, 900), aiuiDesktopFit(0, 0)]));""")
    narrow, wide, unknown = got
    assert narrow["width"] == 1280
    assert abs(narrow["scale"] - 700 / 1280) < 1e-9
    assert narrow["height"] == round(900 / (700 / 1280))
    assert wide == {"width": 0, "height": 0, "scale": 1}
    assert unknown == {"width": 0, "height": 0, "scale": 1}


def test_fitting_writes_the_frame_style_and_undoing_clears_it():
    got = _node(r"""
    var frame = new El('iframe'), holder = new El('div');
    holder.clientWidth = 640; holder.clientHeight = 800;
    aiuiFitDesktop(frame, holder);
    var fitted = {w: frame.style.width, h: frame.style.height, t: frame.style.transform, o: frame.style.transformOrigin};
    holder.clientWidth = 1600;
    aiuiFitDesktop(frame, holder);
    console.log(JSON.stringify({fitted: fitted, wide: {w: frame.style.width, h: frame.style.height, t: frame.style.transform}}));""")
    assert got["fitted"] == {"w": "1280px", "h": "1600px", "t": "scale(0.5)", "o": "0 0"}
    assert got["wide"] == {"w": "100%", "h": "100%", "t": ""}


def test_the_side_view_fits_on_open_and_on_resize_and_lets_go_on_close():
    opened = _fn("aiuiSplitOpen")
    assert "aiuiFitDesktop(frame, holder)" in opened
    assert "window.addEventListener('resize'" in opened
    closed = _fn("aiuiSplitClose")
    assert "window.removeEventListener('resize'" in closed
    assert "s.frame.style.transform = ''" in closed
    assert "s.frame.style.width = '100%'" in closed


# --- seen on the live site, 2026-11-10 ------------------------------------------

def test_the_footer_says_the_step_the_video_is_on():
    """Live, a video writing its script showed step 2 working over a footer
    saying "Rendering the video"."""
    got = _node(r"""
    console.log(JSON.stringify({
      scripting: aiuiVideoProgress({status: 'scripting'}, 2),
      rendering: aiuiVideoProgress({status: 'rendering'}, 3),
      voicing: aiuiVideoProgress({status: 'voicing'}, 3),
      collecting: aiuiVideoProgress({status: 'collecting'}, 1),
      queued: aiuiVideoProgress({status: 'queued', queue_position: 0}, 1)}));""")
    assert got == {"scripting": "Writing the script, 2 min so far.",
                   "rendering": "Rendering the video, 3 min so far.",
                   "voicing": "Rendering the video, 3 min so far.",
                   "collecting": "Waiting to start rendering, 1 min so far.",
                   "queued": "Waiting to start rendering, 1 min so far."}


def test_the_panels_keep_their_padding_inside_a_reply():
    """aiuiPutUnderLastMessage clears a box's left padding (it is built for
    boxes that carry the thread's indent), so a panel's own padding must
    live on an inner element. Live, the text sat against the border."""
    got = _node(r"""
    reply = new El('div'); document.body.appendChild(reply);
    aiuiPutUnderLastMessage = function (el) { el.style.marginLeft = '0'; el.style.paddingLeft = '0'; reply.appendChild(el); };
    aiuiVideoPanel('chat-1', 'v1', {status: 'queued'}, 1);
    AIUI_STEPS.agent = [{key: 'plan', said: 'Planning'}];
    aiuiStepPanel('chat-1', {build_lane: 'agent', build_step: 'plan'}, 1);
    console.log(JSON.stringify({
      video: document.getElementById('aiui-video-steps-v1').innerHTML.slice(0, 60),
      build: document.getElementById('aiui-steps').innerHTML.slice(0, 60)}));""")
    for html in got.values():
        assert html.startswith('<div style="padding:.6rem .75rem;">'), html
