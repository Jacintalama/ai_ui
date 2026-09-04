"""Two agents, two real messages, one after the other. Live only.

Runs against the real site from inside the tasks container with AIUI_LIVE=1.
Nothing here is stubbed: the pipe, the service, the chat API and Open
WebUI's renderer are all the real ones, because three of this feature's
load-bearing facts were found only that way and no stub would have shown
them.
"""
import asyncio
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AIUI_LIVE") != "1",
                                reason="live site only; set AIUI_LIVE=1 in the tasks container")

HOST = "https://ai-ui.coolestdomain.win"
EMAIL = "ralphbenitez32@gmail.com"


async def _page(pw, token):
    browser = await pw.chromium.launch()
    ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
    await ctx.add_cookies([{"name": "token", "value": token,
                            "domain": "ai-ui.coolestdomain.win", "path": "/"}])
    page = await ctx.new_page()
    await page.goto(HOST + "/", wait_until="domcontentloaded")
    await page.evaluate("t => localStorage.setItem('token', t)", token)
    return browser, page


async def _rows(page):
    return await page.evaluate("""() => [...document.querySelectorAll('[id^="message-"]')].map(r => {
        const s = r.querySelector('#response-message-model-name');
        return { header: s ? s.textContent.trim() : null,
                 text: r.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60) };
    })""")


async def test_hi_team_becomes_two_messages_one_after_another():
    import httpx
    from playwright.async_api import async_playwright
    from owui_token import mint_owui_token
    from routes_gateway import _owui_user_id_for

    uid = await _owui_user_id_for(EMAIL)
    token = mint_owui_token(uid, ttl_seconds=900)
    async with async_playwright() as pw:
        browser, page = await _page(pw, token)
        await page.goto(HOST + "/?models=auto_router.auto", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        box = page.locator("#chat-input, textarea, [contenteditable='true']").first
        await box.click()
        await box.fill("hi team, one short sentence each")
        await page.keyboard.press("Enter")

        # Ada first, alone.
        for _ in range(60):
            await page.wait_for_timeout(1000)
            rows = await _rows(page)
            heads = [r["header"] for r in rows if r["header"]]
            if len(heads) >= 1 and heads[0] not in ("Auto (Free)", "IO"):
                break
        first_seen = time.time()

        # Then Mia, as her own row.
        for _ in range(60):
            await page.wait_for_timeout(1000)
            rows = await _rows(page)
            heads = [r["header"] for r in rows if r["header"]]
            if len(heads) >= 2:
                break
        assert heads[:2] == ["Ada", "Mia"], rows
        assert time.time() - first_seen >= 1, "the second arrived with the first, not after it"

        chat_id = await page.evaluate("location.pathname.split('/c/')[1]")

        # A reload shows the same two rows, from stored data alone.
        await page.goto(HOST + "/c/" + chat_id, wait_until="networkidle")
        await page.wait_for_timeout(4000)
        rows = await _rows(page)
        assert [r["header"] for r in rows if r["header"]][:2] == ["Ada", "Mia"], rows

        # The stored chat: first message claimed for Ada, no marker anywhere.
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get("http://open-webui:8080/api/v1/chats/" + chat_id,
                            headers={"Authorization": "Bearer " + token})
            msgs = r.json()["chat"]["history"]["messages"].values()
        assistants = [m for m in msgs if m["role"] == "assistant"]
        assert [m["model"] for m in assistants][:2] == ["agent-scout-7d88", "agent-triage-256e"]
        assert not any("aiui:turns" in (m.get("content") or "") for m in msgs)
        assert not any((m.get("content") or "").startswith("Ada:") for m in assistants)

        await browser.close()
        async with httpx.AsyncClient(timeout=60) as c:
            await c.delete("http://open-webui:8080/api/v1/chats/" + chat_id,
                           headers={"Authorization": "Bearer " + token})
