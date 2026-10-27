"""The main chat, end to end, the way a person uses it. Live only.

Runs against the real site from inside the tasks container with AIUI_LIVE=1.
Nothing is stubbed: Open WebUI, the Auto pipe, /agents/chat, Jev, the free
model, the tools and ElevenLabs are all the real ones. What is asserted is
what the person sees (the rendered reply) plus the row that proves which
path produced it, since a reply alone cannot tell IO from the plain free
model it falls back to.

    docker exec -e AIUI_LIVE=1 tasks sh -lc \
        'cd /app && python -m pytest tests/browser/test_main_chat_live.py -q'

One run costs about $0.002 in model and Jev calls and a few hundred
ElevenLabs credits. Every chat it opens is deleted at the end.
"""
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AIUI_LIVE") != "1",
                                reason="live site only; set AIUI_LIVE=1 in the tasks container")

HOST = "https://ai-ui.coolestdomain.win"
OWUI = "http://open-webui:8080"
EMAIL = "alamajacintg04@gmail.com"
AUTO = "auto_router.auto"
#: Shown under a reply only when nobody, IO included, took the message.
FALLBACK = "Auto-routed to the free general model"
TURN_SECONDS = 120


@pytest.fixture(autouse=True)
def fresh_db_pool():
    """Each test runs on its own event loop, and an asyncpg pool belongs to
    the loop that opened it, so the second test would reuse dead
    connections ("another operation is in progress"). Start each test with
    no pool; db.session() builds one on first use."""
    import db
    db._engine = db._session_maker = None
    yield
    db._engine = db._session_maker = None


@pytest.fixture
async def site():
    """A signed-in page as the test account, and cleanup of every chat."""
    import httpx
    from playwright.async_api import async_playwright
    from owui_token import mint_owui_token, session_stamp_for
    from routes_gateway import _owui_user_id_for

    uid = await _owui_user_id_for(EMAIL)
    token = mint_owui_token(uid, ttl_seconds=1800,
                            session_stamp=await session_stamp_for(uid))
    chats = []
    # An agent on "All" may build agents without asking (its owner's choice),
    # and on 2026-10-27 one did, in this test. Whatever this run creates,
    # it removes, even when an assertion fails.
    agents_before = {r[0] for r in await _rows(
        "select id from public.model where user_id = :u "
        "and base_model_id is not null", u=uid)}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        await ctx.add_cookies([{"name": "token", "value": token,
                                "domain": "ai-ui.coolestdomain.win", "path": "/"}])
        page = await ctx.new_page()
        await page.goto(HOST + "/", wait_until="domcontentloaded")
        await page.evaluate("t => localStorage.setItem('token', t)", token)
        try:
            yield {"page": page, "token": token, "uid": uid, "chats": chats}
        finally:
            await browser.close()
            made = {r[0] for r in await _rows(
                "select id from public.model where user_id = :u "
                "and base_model_id is not null", u=uid)} - agents_before
            auth = {"Authorization": "Bearer " + token}
            async with httpx.AsyncClient(timeout=60) as c:
                for chat_id in chats:
                    await c.delete(OWUI + "/api/v1/chats/" + chat_id, headers=auth)
                for agent_id in made:
                    await c.post(OWUI + "/api/v1/models/model/delete",
                                 params={"id": agent_id}, json={"id": agent_id},
                                 headers=auth)
            assert not made, "this run created agents (removed): %s" % sorted(made)


async def _open(site, model):
    page = site["page"]
    # Not "networkidle": the chat keeps a socket open, so it never idles.
    await page.goto(HOST + "/?models=" + model, wait_until="load")
    await page.locator("#chat-input").wait_for(state="visible", timeout=60000)
    await page.wait_for_timeout(2000)
    return page


async def _replies(page):
    """Each finished assistant reply: its header and its rendered text. A
    reply is finished when its action bar (Read Aloud) is drawn."""
    return await page.evaluate("""() => [...document.querySelectorAll('[id^="message-"]')]
        .filter(r => r.querySelector('button[aria-label="Read Aloud"]'))
        .map(r => {
            const h = r.querySelector('#response-message-model-name');
            return { header: h ? h.textContent.trim() : null,
                     text: r.innerText.replace(/\\s+/g, ' ').trim() };
        })""")


async def _send(site, text):
    """Send one message and wait for its reply to finish. The reply."""
    page = site["page"]
    before = len(await _replies(page))
    box = page.locator("#chat-input, textarea, [contenteditable='true']").first
    await box.click()
    await box.fill(text)
    await page.keyboard.press("Enter")
    for _ in range(TURN_SECONDS * 2):
        await page.wait_for_timeout(500)
        try:
            rows = await _replies(page)
        except Exception:                                   # a soft reload
            continue
        if len(rows) > before and rows[-1]["text"]:
            # One more beat, so a streamed reply is not read mid-word.
            await page.wait_for_timeout(1500)
            rows = await _replies(page)
            chat_id = await page.evaluate(
                "(location.pathname.split('/c/')[1] || '')")
            if chat_id and chat_id not in site["chats"]:
                site["chats"].append(chat_id)
            return rows[-1]
    raise AssertionError("no reply to %r within %ss" % (text, TURN_SECONDS))


async def _rows(sql, **params):
    from sqlalchemy import text
    from db import session
    async with session() as s:
        return (await s.execute(text(sql), params)).all()


async def _runs_since(agent_id, since):
    return await _rows(
        "select status, model from tasks.agent_run where user_email = :e "
        "and agent_id = :a and started_at >= :t order by started_at",
        e=EMAIL, a=agent_id, t=since)


async def _agent_count(uid):
    return (await _rows(
        "select count(*) from public.model where user_id = :u "
        "and base_model_id is not null", u=uid))[0][0]


def _now():
    return datetime.now(timezone.utc)


async def test_auto_answers_with_a_tool_jev_picked(site):
    """A calendar question on Auto: IO answers, not the bare free model, and
    Jev handed it the calendar."""
    since = _now()
    await _open(site, AUTO)
    reply = await _send(site, "what is on my calendar tomorrow")
    assert FALLBACK not in reply["text"], reply
    assert len(reply["text"]) > 20, reply
    runs = await _runs_since("io-assistant", since)
    assert [r.status for r in runs] == ["completed"], runs
    picks = await _rows(
        "select outcome from tasks.jev_check where user_email = :e and "
        "purpose = 'tool_pick' and created_at >= :t", e=EMAIL, t=since)
    assert picks and "calendar" in picks[-1].outcome.split(","), picks


async def test_a_change_asks_first_and_no_changes_nothing(site):
    """Building agents is a write: the main chat shows the question, and a
    bare "no" refuses it. Nothing is created."""
    agents_before = await _agent_count(site["uid"])
    since = _now()
    await _open(site, AUTO)
    asked = await _send(site, "create three assistants for my coffee shop")
    assert "wants to run" in asked["text"], asked
    assert "create_agent" in asked["text"], asked
    assert "Reply yes to let it, or no to skip." in asked["text"], asked

    answered = await _send(site, "no")
    assert "wants to run" not in answered["text"], answered
    assert FALLBACK not in answered["text"], answered
    statuses = [r.status for r in await _runs_since("io-assistant", since)]
    assert statuses[0] == "waiting", statuses
    assert await _agent_count(site["uid"]) == agents_before


async def test_a_picked_agent_answers_as_itself_and_reads_aloud(site):
    """Choosing an agent runs our loop as that agent (PR #40), its name is on
    the reply, and the speaker button plays it through ElevenLabs."""
    agent = (await _rows(
        "select id, name from public.model where user_id = :u and "
        "base_model_id = 'io.io' order by name limit 1", u=site["uid"]))
    assert agent, "the test account has no agents"
    agent_id, name = agent[0]
    since = _now()
    page = await _open(site, agent_id)
    reply = await _send(site, "in one short sentence, who are you?")
    assert reply["header"] == name, reply
    assert [r.status for r in await _runs_since(agent_id, since)] == ["completed"]

    speech = []
    page.on("response", lambda r: speech.append(
        (r.status, r.headers.get("content-type", "")))
        if "/api/v1/audio/speech" in r.url else None)
    button = page.locator('button[aria-label="Read Aloud"]').last
    await button.click(force=True)
    for _ in range(40):
        if speech:
            break
        await page.wait_for_timeout(500)
    assert speech and speech[0] == (200, "audio/mpeg"), speech
