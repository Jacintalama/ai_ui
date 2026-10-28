"""Talk to an agent on the live site; it answers out loud with tools Jev picked.

Live only, from inside the tasks container with AIUI_LIVE=1:

    docker exec -e AIUI_LIVE=1 tasks sh -lc \
        'cd /app && python -m pytest tests/browser/test_agent_talk_live.py -q'

Everything is real except the speech recogniser, which a headless browser
does not have: the office page, the send, the agent's turn, Jev's tool pick,
the free model, and the read-aloud through Open WebUI and ElevenLabs. Two
short messages to the first agent of the test account: about $0.002 in
model and Jev calls and a few hundred ElevenLabs credits.
"""
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AIUI_LIVE") != "1",
                                reason="live site only; set AIUI_LIVE=1 in the tasks container")

HOST = "https://ai-ui.coolestdomain.win"
EMAIL = "alamajacintg04@gmail.com"
TURN_SECONDS = 150

#: Stands in for the microphone only. __say() is the person finishing a
#: sentence. Playback is the browser's own; each play() is recorded with
#: whether it started.
FAKE_MIC = """
window.__recs = [];
window.__plays = [];
class FakeRecognition {
  constructor() { window.__recs.push(this); this.started = false; }
  start() { this.started = true; }
  stop() { if (this.onend) this.onend(); }
  abort() { if (this.onend) this.onend(); }
}
window.SpeechRecognition = FakeRecognition;
window.webkitSpeechRecognition = FakeRecognition;
window.__say = function (words) {
  const r = window.__recs[window.__recs.length - 1];
  r.onresult({ results: [[{ transcript: words }]] });
  r.onend();
};
const realPlay = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const p = realPlay.call(this);
  const rec = { src: this.src, started: null };
  window.__plays.push(rec);
  if (p && p.then) p.then(() => { rec.started = true; }, e => { rec.started = String(e); });
  return p;
};
"""


@pytest.fixture(autouse=True)
def fresh_db_pool():
    import db
    db._engine = db._session_maker = None
    yield
    db._engine = db._session_maker = None


async def _rows(sql, **params):
    from sqlalchemy import text
    from db import session
    async with session() as s:
        return (await s.execute(text(sql), params)).all()


async def test_talking_to_an_agent_is_answered_out_loud_with_picked_tools():
    from playwright.async_api import async_playwright
    from owui_token import mint_owui_token, session_stamp_for
    from routes_gateway import _owui_user_id_for

    uid = await _owui_user_id_for(EMAIL)
    token = mint_owui_token(uid, ttl_seconds=1800,
                            session_stamp=await session_stamp_for(uid))
    agent = await _rows(
        "select id, name from public.model where user_id = :u and "
        "base_model_id = 'io.io' order by name limit 1", u=uid)
    assert agent, "the test account has no agents"
    agent_id, name = agent[0]
    since = datetime.now(timezone.utc)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await browser.new_context(viewport={"width": 1500, "height": 1000})
        await ctx.add_cookies([{"name": "token", "value": token,
                                "domain": "ai-ui.coolestdomain.win", "path": "/"}])
        await ctx.add_init_script(FAKE_MIC)
        page = await ctx.new_page()
        await page.goto(HOST + "/", wait_until="domcontentloaded")
        await page.evaluate("t => localStorage.setItem('token', t)", token)
        speech = []

        async def on_response(r):
            if "/api/v1/audio/speech" in r.url:
                speech.append((r.status, r.headers.get("content-type", ""),
                               r.request.post_data_json))
        page.on("response", on_response)
        try:
            # The agents page: Talk is there, and no card claims a hand
            # picked limit any more.
            await page.goto(HOST + "/tasks/agents", wait_until="load")
            await page.locator(".ap-composer .ap-mic").wait_for(state="attached", timeout=30000)
            await page.locator("#my-agents .card").first.wait_for(timeout=30000)
            chips = await page.locator("#my-agents .card .chip.scope").all_inner_texts()
            assert chips and set(chips) == {"Tools: automatic"}, chips

            # The office: a private window with the agent, spoken to.
            await page.goto(HOST + "/tasks/office", wait_until="load")
            await page.wait_for_function("() => document.querySelector('#chatdock')")
            await page.evaluate(
                "id => import('/tasks/static/office/js/dock.js').then(d => d.openChat(id))",
                agent_id)
            win = page.locator('#chatdock .cw[data-chat="%s"]' % agent_id)
            await win.wait_for(state="visible", timeout=30000)
            await page.wait_for_timeout(3000)

            async def talk(words):
                before = await win.locator(".am.agent").count()
                heard = len(speech)
                await win.locator(".ap-mic").click()
                await page.wait_for_function(
                    "() => window.__recs.length && window.__recs.at(-1).started")
                await page.evaluate("w => window.__say(w)", words)
                for _ in range(TURN_SECONDS * 2):
                    await page.wait_for_timeout(500)
                    if await win.locator(".am.agent").count() > before and len(speech) > heard:
                        break
                else:
                    raise AssertionError("no spoken answer to %r" % words)
                await page.wait_for_timeout(1500)
                return speech[heard]

            status, kind, body = await talk("in one short sentence, who are you?")
            assert status == 200 and kind.startswith("audio/mpeg"), (status, kind)
            assert body["voice"], body
            assert len(body["input"]) > 5, body

            status, kind, body = await talk("what is on my calendar tomorrow")
            assert status == 200 and kind.startswith("audio/mpeg"), (status, kind)
            plays = await page.evaluate("() => window.__plays")
            assert plays and all(p["started"] is True for p in plays), plays
        finally:
            await browser.close()

    runs = await _rows(
        "select status from tasks.agent_run where user_email = :e and "
        "agent_id = :a and started_at >= :t order by started_at",
        e=EMAIL, a=agent_id, t=since)
    assert [r.status for r in runs] == ["completed", "completed"], runs
    picks = await _rows(
        "select outcome from tasks.jev_check where user_email = :e and "
        "purpose = 'tool_pick' and created_at >= :t order by created_at",
        e=EMAIL, t=since)
    assert len(picks) == 2, picks
    assert "calendar" in picks[-1].outcome.split(","), picks
