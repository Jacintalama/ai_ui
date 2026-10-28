"""Talk to the agents, and they answer out loud.

Lukas, 2026-10-27: a mic on the agents page and in the office chat, so
talking to the agents gets a spoken answer. agent-chat.js adds a Talk
button to every composer on both pages. The words come from the browser's
own speech recognition; an answer to a SPOKEN message is read through Open
WebUI's /api/v1/audio/speech with the site's read-aloud voice.

The pages, the stylesheet, the script and every bubble are the real ones
(office.html, agents.html, agent_chat_render). Two things are stood in for,
because a headless browser has neither: the speech recognition engine
(the browser API, not our markup) and audio playback.
"""
import http.server
import json
import pathlib
import sys
import threading
import urllib.parse
from datetime import datetime, timezone

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
sys.path.insert(0, str(STATIC.parent))
import agent_chat_render as render                        # noqa: E402

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": [], "skillIds": []},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    # Her own voice, where Open WebUI's model editor keeps it (TTS voice).
    {"id": "agent-mia-77", "name": "Mia",
     "meta": {"role": "Receptionist", "toolIds": [], "skillIds": [],
              "tts": {"voice": "voice-matilda"}},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
]

#: What was said before the page opened. History is never read out.
THREAD = render.thread([
    {"role": "user", "content": "What did we decide?", "turn_id": "t1",
     "at": "2026-10-27T09:15:00+00:00"},
    {"role": "assistant", "agent_name": "Ada", "content": "Thursday.",
     "at": "2026-10-27T09:15:04.123456+00:00"},
    {"role": "assistant", "agent_name": "Mia", "content": "Inbox is clear.",
     "at": "2026-10-27T09:15:06.654321+00:00"},
])

VOICE = "voice-george"


def _now():
    """The instant the server stamps on a message, as routes_agent_chat does."""
    return datetime.now(timezone.utc).isoformat()

#: Speech recognition and playback, as a page sees them. __say() is the
#: person saying a sentence and then going quiet: the page decides when
#: they have finished. __cut() is the browser ending recognition by itself.
#: play() records and ends after a beat. The waits are the page's own,
#: shortened (window.AIUI_TALK_MS): finished 300 ms, unfinished 900 ms,
#: nothing said 1500 ms.
QUIET, UNFINISHED, IDLE = 300, 900, 1500
FAKE_SPEECH = """
window.AIUI_TALK_MS = { quiet: %d, unfinished: %d, idle: %d, again: 50 };
window.__recs = [];
window.__played = [];
class FakeRecognition {
  constructor() { window.__recs.push(this); this.started = false; this.ended = false; }
  start() { this.started = true; }
  stop() { this.ended = true; if (this.onend) this.onend(); }
  abort() { this.ended = true; if (this.onend) this.onend(); }
}
window.SpeechRecognition = FakeRecognition;
window.webkitSpeechRecognition = FakeRecognition;
window.__say = function (words) {
  const r = window.__recs[window.__recs.length - 1];
  r.onresult({ results: [[{ transcript: words }]] });
};
window.__cut = function () {
  const r = window.__recs[window.__recs.length - 1];
  r.ended = true;
  r.onend();
};""" % (QUIET, UNFINISHED, IDLE) + """
window.__refuse = function () {
  const r = window.__recs[window.__recs.length - 1];
  r.onerror({ error: "not-allowed" });
  r.onend();
};
// A player that never decodes anything: the bytes served below are not a
// real MP3, and a real element would fire error and skip on to the next.
window.Audio = function (src) { this.src = src; };
window.Audio.prototype.play = function () {
  window.__played.push(this.src);
  const me = this;
  if (!window.__hold) setTimeout(function () { if (me.onended) me.onended(); }, 30);
  return Promise.resolve();
};
window.Audio.prototype.pause = function () { window.__paused = true; };
"""

NO_SPEECH = """
Object.defineProperty(window, "SpeechRecognition", { value: undefined });
Object.defineProperty(window, "webkitSpeechRecognition", { value: undefined });
"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def _serve(html: bytes):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?", 1)[0]
            body, kind = html, "text/html"
            if "/office/" in path:
                asset = STATIC / "office" / path.split("/office/", 1)[1]
            elif path.startswith("/tasks/static/"):
                rel = path.rsplit("/", 1)[1]
                asset = STATIC / rel if (STATIC / rel).is_file() else STATIC / "vendor" / rel
            else:
                asset = None
            if asset is not None:
                if not asset.is_file():
                    self.send_error(404, "no such asset: %s" % path)
                    return
                body = asset.read_bytes()
                kind = "text/css" if path.endswith(".css") else "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _open(browser, page_file, init=FAKE_SPEECH):
    srv = _serve((STATIC / page_file).read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    pg.errors, pg.sent, pg.spoken = [], [], []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(init)

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            r.fulfill(status=204)
            return
        if "/chat/thread" in url:
            r.fulfill(status=200, content_type="text/html", body=THREAD)
            return
        if "/chat/send" in url:
            form = urllib.parse.parse_qs(r.request.post_data or "")
            text = (form.get("message") or [""])[0]
            pg.sent.append(text)
            r.fulfill(status=200, content_type="text/html",
                      body=render.turn_open(text, "t9", at=_now()) + render.turn_close())
            return
        if url.endswith("/api/config"):
            body = {"audio": {"tts": {"engine": "elevenlabs", "voice": VOICE}}}
        elif "/api/v1/audio/speech" in url:
            pg.spoken.append(json.loads(r.request.post_data or "{}"))
            r.fulfill(status=200, content_type="audio/mpeg", body=b"ID3fake")
            return
        elif "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/todo" in url:
            body = {"open": [], "done": []}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        else:
            body = {"skills": []}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d/%s" % (srv.server_address[1], page_file))
    pg.srv = srv
    return pg


@pytest.fixture
def office(browser):
    pg = _open(browser, "office.html")
    pg.wait_for_selector("#cw-team #agent-thread .am.agent", state="visible")
    pg.wait_for_timeout(300)
    yield pg
    pg.close()
    pg.srv.shutdown()


def _answer(pg, name, text, at=None):
    """An answer landing in the team thread, the way the stream adds one:
    stamped with the instant it was said (routes_agent_chat, at=_now_iso())."""
    html = render.agent_bubble(name, text, at=at or _now())
    pg.evaluate(
        "h => { document.querySelector('#agent-thread').insertAdjacentHTML('beforeend', h);"
        " document.body.dispatchEvent(new CustomEvent('htmx:sseMessage')); }",
        html)
    return html


def _talk(pg, words, where="#cw-team"):
    turns = pg.locator("#agent-thread .aturn").count()
    pg.locator(where + " .ap-composer .ap-mic").click()
    pg.wait_for_function("() => window.__recs.length && window.__recs.at(-1).started")
    pg.evaluate("w => window.__say(w)", words)
    # The send's own answer: the turn the person's words open.
    pg.wait_for_function("n => document.querySelectorAll('#agent-thread .aturn').length > n",
                         arg=turns)
    pg.wait_for_timeout(300)


def test_the_office_team_chat_has_a_talk_button_after_send(office):
    form = office.locator("#cw-team .ap-composer")
    # The buttons on the message row; Attach has a row of its own above it.
    labels = form.locator(":scope > button").all_inner_texts()
    assert labels == ["Send", "Talk"], labels
    assert office.errors == [], office.errors


def test_talk_shows_a_microphone_so_it_reads_as_voice(office):
    """Asked for 2026-10-28: a mic, then the word."""
    mic = office.locator("#cw-team .ap-mic")
    icon = mic.locator("svg.ap-mic-icon")
    assert icon.count() == 1
    assert icon.get_attribute("aria-hidden") == "true"
    assert icon.bounding_box()["x"] < mic.locator(".ap-mic-label").bounding_box()["x"]
    mic.click()
    assert mic.locator("svg.ap-mic-icon").count() == 1, "the label change lost the icon"


def test_talk_does_not_look_like_a_second_send(office):
    """The office's plain .btn is filled cyan; Talk is the outline one."""
    look = office.evaluate(
        "() => { const f = document.querySelector('#cw-team .ap-composer');"
        " const bg = b => getComputedStyle(b).backgroundColor;"
        " return [bg(f.querySelector('button[type=submit]')), bg(f.querySelector('.ap-mic'))]; }")
    assert look[0] != look[1], look


def test_listening_leaves_the_message_box_room(office):
    """300px wide: the box keeps more width than both buttons together,
    whatever the button says."""
    office.locator("#cw-team .ap-mic").click()
    got = office.evaluate(
        "() => { const f = document.querySelector('#cw-team .ap-composer');"
        " const w = e => e.getBoundingClientRect().width;"
        " return { box: w(f.querySelector('input[name=message]')),"
        "          buttons: [...f.querySelectorAll(':scope > button')].reduce((n, b) => n + w(b), 0) }; }")
    assert got["box"] > got["buttons"], got


def test_a_private_window_in_the_office_gets_one_too(office):
    office.evaluate("() => import('/tasks/static/office/js/dock.js').then(d => d.openChat('agent-mia-77'))")
    win = office.locator('#chatdock .cw[data-chat="agent-mia-77"]')
    win.wait_for(state="visible")
    office.wait_for_timeout(200)
    assert win.locator(".ap-composer .ap-mic").count() == 1


def test_the_agents_page_composer_has_a_talk_button(browser):
    pg = _open(browser, "agents.html")
    try:
        pg.wait_for_selector(".ap-composer .ap-mic", state="attached")
        assert pg.locator(".ap-composer > button").all_inner_texts() == ["Send", "Talk"]
    finally:
        pg.close()
        pg.srv.shutdown()


def test_no_talk_button_where_the_browser_cannot_listen(browser):
    """Firefox has no speech recognition. A button that cannot work is
    worse than none."""
    pg = _open(browser, "office.html", init=NO_SPEECH)
    try:
        pg.wait_for_selector("#cw-team .ap-composer", state="visible")
        pg.wait_for_timeout(300)
        assert pg.locator(".ap-mic").count() == 0
        assert pg.errors == [], pg.errors
    finally:
        pg.close()
        pg.srv.shutdown()


def test_what_you_say_is_sent_as_your_message(office):
    _talk(office, "what is on my calendar tomorrow")
    assert office.sent == ["what is on my calendar tomorrow"]


def test_the_button_says_it_is_listening(office):
    mic = office.locator("#cw-team .ap-mic")
    mic.click()
    assert mic.inner_text() == "Done"
    assert mic.get_attribute("aria-label") == "Stop listening and send"
    assert mic.get_attribute("aria-pressed") == "true"
    office.evaluate("() => window.__say('hello')")
    office.wait_for_function(
        "() => document.querySelector('#cw-team .ap-mic').innerText.trim() === 'Talk'")


def test_an_answer_to_a_spoken_message_is_read_with_the_site_voice(office):
    _talk(office, "what did we decide")
    _answer(office, "Ada", "We moved it to **Thursday**.")
    office.wait_for_function("() => window.__played.length === 1")
    # Only the new answer; the two from before the page opened stay quiet.
    # Two people have spoken in this thread, so the name goes first.
    assert office.spoken == [{"input": "Ada. We moved it to Thursday.",
                              "voice": VOICE}]


def test_answers_are_read_one_after_another(office):
    _talk(office, "status please")
    _answer(office, "Ada", "Building.")
    _answer(office, "Mia", "Inbox is clear.")
    office.wait_for_function("() => window.__played.length === 2")
    assert [s["input"] for s in office.spoken] == ["Ada. Building.",
                                                   "Mia. Inbox is clear."]


def test_an_answer_to_a_typed_message_is_not_read(office):
    _talk(office, "first by voice")
    box = office.locator("#cw-team .ap-composer input[name=message]")
    box.fill("now typed")
    office.locator("#cw-team .ap-composer button[type=submit]").click()
    office.wait_for_timeout(300)
    _answer(office, "Ada", "A typed answer.")
    office.wait_for_timeout(500)
    assert office.spoken == []


def test_a_long_answer_is_read_up_to_a_sentence_end(office):
    _talk(office, "tell me everything")
    long = " ".join(["This is sentence number %d of a long answer." % i
                     for i in range(60)])
    _answer(office, "Ada", long)
    office.wait_for_function("() => window.__played.length === 1")
    said = office.spoken[0]["input"]
    assert len(said) <= 1200 + len("Ada. ")
    assert said.endswith("answer."), said[-40:]


def test_talking_over_the_reading_stops_it_and_listens(office):
    """Found live, 2026-10-28: a press while an answer was still being read
    only silenced it, and the next sentence was never heard or sent. In a
    spoken conversation you interrupt, so Talk stops the reading and
    listens in one press."""
    office.evaluate("() => { window.__hold = true; }")
    _talk(office, "read me something")
    _answer(office, "Ada", "A long story.")
    office.wait_for_function("() => window.__played.length === 1")
    mic = office.locator("#cw-team .ap-mic")
    assert mic.get_attribute("aria-label") == "Stop the reading and talk"
    _talk(office, "and the next thing")
    assert office.evaluate("() => window.__paused") is True
    assert office.sent[-1] == "and the next thing"


def test_a_thread_drawn_again_is_not_read_again(office):
    """Live, 2026-10-28 12:47:47: one spoken "hey ada" and the page asked
    for fifteen readings at once, Ada's answers from hours before among them
    (the read-aloud cache holds her 10:33 "BLUE HERON" answer, written
    then). Whether an answer had been read lived only on its row, so a
    thread drawn again had no answer marked and read them all."""
    _talk(office, "hey ada")
    office.evaluate("() => htmx.ajax('GET', '/tasks/agents/chat/thread', '#agent-thread')")
    office.wait_for_function(
        "() => document.querySelectorAll('#agent-thread .am.user').length === 1")
    office.wait_for_timeout(600)
    assert office.spoken == []


def test_switching_conversation_on_the_agents_page_reads_nothing_old(browser):
    """The agents page has one thread and swaps conversations into it
    (aiuiTalkTo). Speaking to the room and then opening Ada read every
    answer in Ada's history."""
    pg = _open(browser, "agents.html")
    try:
        pg.wait_for_selector("#agent-thread .am.agent", state="attached")
        pg.wait_for_timeout(300)
        pg.locator(".ap-composer .ap-mic").click()
        pg.wait_for_function("() => window.__recs.length && window.__recs.at(-1).started")
        pg.evaluate("() => window.__say('hey')")
        pg.wait_for_function("() => document.querySelectorAll('#agent-thread .aturn').length > 0")
        pg.evaluate("() => window.aiuiTalkTo('agent-ada-0001', 'Ada')")
        pg.wait_for_function(
            "() => { const t = document.querySelector('#agent-thread');"
            " return !t.textContent.includes('hey') &&"
            " t.querySelectorAll('.am.agent').length === 2; }")
        pg.wait_for_timeout(600)
        assert pg.spoken == []
    finally:
        pg.close()
        pg.srv.shutdown()


def test_an_answer_drawn_twice_is_read_once(office):
    _talk(office, "status please")
    html = _answer(office, "Ada", "Building.")
    office.wait_for_function("() => window.__played.length === 1")
    office.evaluate(
        "h => { document.querySelector('#agent-thread').insertAdjacentHTML('beforeend', h);"
        " document.body.dispatchEvent(new CustomEvent('htmx:sseMessage')); }", html)
    office.wait_for_timeout(500)
    assert [s["input"] for s in office.spoken] == ["Ada. Building."]


def _mic(pg, where="#cw-team"):
    pg.locator(where + " .ap-composer .ap-mic").click()
    pg.wait_for_function("() => window.__recs.length && window.__recs.at(-1).started")


def _hear(pg, *parts):
    """The recogniser's results so far, one entry per phrase."""
    pg.evaluate("p => window.__recs.at(-1).onresult({ results: p.map(t => [{ transcript: t }]) })",
                list(parts))


def _sent(pg, n=1, timeout=6000):
    pg.wait_for_function("n => document.querySelectorAll('#agent-thread .am.user').length > n",
                         arg=n, timeout=timeout)


def test_a_pause_while_talking_does_not_send(office):
    """Live, 2026-10-28: "hey ada what is the weather today" arrived as
    "hey ada". The recogniser stopped at the first pause and sent."""
    _mic(office)
    assert office.evaluate("() => window.__recs.at(-1).continuous") is True
    _hear(office, "hey ada")
    # Longer than a finished sentence waits: "hey ada" is somebody starting.
    office.wait_for_timeout(QUIET + 400)
    assert office.sent == []
    _hear(office, "hey ada", " what is the weather today")
    _sent(office)
    assert office.sent == ["hey ada what is the weather today"]


def test_words_that_trail_off_are_waited_for(office):
    """'...and' is somebody still talking; a finished sentence goes sooner."""
    _mic(office)
    _hear(office, "tell me the weather and")
    office.wait_for_timeout(QUIET + 400)
    assert office.sent == []
    _hear(office, "tell me the weather and", "the news for today")
    _sent(office)
    assert office.sent == ["tell me the weather and the news for today"]


def test_the_browser_stopping_by_itself_keeps_listening(office):
    """Chrome ends recognition by itself now and then (on a phone, after
    every phrase). That is not the person finishing: it listens on, and the
    words already heard are kept."""
    _mic(office)
    _hear(office, "hey ada")
    office.evaluate("() => window.__cut()")
    office.wait_for_function("() => window.__recs.length === 2 && window.__recs[1].started")
    assert office.sent == []
    _hear(office, "what is on my calendar tomorrow")
    _sent(office)
    assert office.sent == ["hey ada what is on my calendar tomorrow"]


def test_after_the_answer_is_read_it_listens_again(office):
    """A conversation: the person talks, the agent answers out loud, and
    the mic opens again for the next thing without a press."""
    _talk(office, "status please")
    heard = office.evaluate("() => window.__recs.length")
    _answer(office, "Ada", "Building.")
    office.wait_for_function("() => window.__played.length === 1")
    office.wait_for_function("n => window.__recs.length > n && window.__recs.at(-1).started &&"
                             " !window.__recs.at(-1).ended", arg=heard)
    assert office.locator("#cw-team .ap-mic").inner_text() == "Done"
    _hear(office, "and how long will it take")
    _sent(office, 2)
    assert office.sent == ["status please", "and how long will it take"]


def test_it_does_not_listen_while_an_answer_is_still_coming(office):
    """Between the spoken message and its answer the mic stays shut, or the
    answer would be read into the person's next turn."""
    _talk(office, "status please")
    heard = office.evaluate("() => window.__recs.length")
    office.wait_for_timeout(600)
    assert office.evaluate("() => window.__recs.length") == heard


def test_saying_nothing_ends_the_conversation(office):
    _talk(office, "status please")
    _answer(office, "Ada", "Building.")
    office.wait_for_function("() => window.__played.length === 1")
    office.wait_for_function("() => window.__recs.at(-1).started && !window.__recs.at(-1).ended")
    office.wait_for_function("() => window.__recs.at(-1).ended", timeout=IDLE + 3000)
    heard = office.evaluate("() => window.__recs.length")
    office.wait_for_timeout(800)
    assert office.evaluate("() => window.__recs.length") == heard
    assert office.locator("#cw-team .ap-mic").inner_text() == "Talk"
    assert office.sent == ["status please"]


def test_done_before_a_word_ends_the_conversation(office):
    _talk(office, "status please")
    _answer(office, "Ada", "Building.")
    office.wait_for_function("() => window.__played.length === 1")
    office.wait_for_function("() => window.__recs.at(-1).started && !window.__recs.at(-1).ended")
    office.locator("#cw-team .ap-mic").click()
    heard = office.evaluate("() => window.__recs.length")
    _answer(office, "Mia", "One more thing.")
    office.wait_for_timeout(600)
    assert office.evaluate("() => window.__recs.length") == heard
    assert office.sent == ["status please"]


def test_typing_ends_the_conversation(office):
    _talk(office, "first by voice")
    box = office.locator("#cw-team .ap-composer input[name=message]")
    box.fill("now typed")
    office.locator("#cw-team .ap-composer button[type=submit]").click()
    heard = office.evaluate("() => window.__recs.length")
    _answer(office, "Ada", "A typed answer.")
    office.wait_for_timeout(600)
    assert office.evaluate("() => window.__recs.length") == heard


def test_done_sends_at_once(office):
    mic = office.locator("#cw-team .ap-mic")
    mic.click()
    office.wait_for_function("() => window.__recs.length && window.__recs.at(-1).started")
    office.evaluate("() => window.__recs.at(-1).onresult("
                    "{ results: [[{ transcript: 'short one' }]] })")
    mic.click()
    office.wait_for_timeout(300)
    assert office.sent == ["short one"]


def test_each_agent_is_read_in_its_own_voice(office):
    """Ada was read by George, a man's voice, the one site voice. An agent
    with a TTS voice set (Open WebUI's model editor, meta.tts.voice) is read
    in it; one without keeps the site's."""
    _talk(office, "both of you")
    _answer(office, "Mia", "Inbox is clear.")
    _answer(office, "Ada", "Thursday.")
    office.wait_for_function("() => window.__played.length === 2")
    assert [(s["input"], s["voice"]) for s in office.spoken] == [
        ("Mia. Inbox is clear.", "voice-matilda"), ("Ada. Thursday.", VOICE)]


def test_a_blocked_microphone_says_how_to_fix_it(office):
    office.locator("#cw-team .ap-mic").click()
    office.evaluate("() => window.__refuse()")
    note = office.locator("#agent-thread .am.note").last
    assert "microphone is blocked" in note.inner_text()
    assert office.sent == []
