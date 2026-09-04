"""Two agents, two real messages, one after the other. Live only.

Runs against the real site from inside the tasks container with AIUI_LIVE=1.
Nothing here is stubbed: the pipe, the service, the chat API and Open
WebUI's renderer are all the real ones, because three of this feature's
load-bearing facts were found only that way and no stub would have shown
them.
"""
import os

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
        chat_id = None
        try:
            await page.goto(HOST + "/?models=auto_router.auto", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            box = page.locator("#chat-input, textarea, [contenteditable='true']").first
            await box.click()
            await box.fill("hi team, one short sentence each")
            await page.keyboard.press("Enter")

            # Sample from the moment the message is sent, with no leading
            # sleep, and keep the whole sequence of counts. "One agent row,
            # then two" is the property under test, so it has to be OBSERVED
            # in the samples. Waiting a second and then finding two rows
            # would pass just as happily if both had arrived together, which
            # is the bug this test exists to catch.
            # Keep the whole LIST of headers per sample, not just how many.
            # After the soft reload Ada's header briefly reads "Auto (Free)"
            # while Mia's already reads "Mia", so a one-name sample can be
            # ["Mia"], which counting alone would happily accept as "Ada was
            # alone first". The property is that ["Ada"] is seen before the
            # first ["Ada", "Mia"].
            seen = []
            for _ in range(240):
                await page.wait_for_timeout(250)
                try:
                    rows = await _rows(page)
                except Exception:
                    # A location.reload() fallback can tear down the execution
                    # context mid evaluate. That is a missed sample, not a
                    # failure.
                    continue
                heads = [r["header"] for r in rows
                         if r["header"] and r["header"] not in ("Auto (Free)", "IO")]
                seen.append(heads)
                if heads[:2] == ["Ada", "Mia"]:
                    break

            both = next((i for i, s in enumerate(seen) if s[:2] == ["Ada", "Mia"]), None)
            assert both is not None, "the two agents never both appeared: %r" % seen
            alone = next((i for i, s in enumerate(seen) if s == ["Ada"]), None)
            assert alone is not None, (
                "Ada was never shown on her own: %r" % seen)
            assert alone < both, (
                "both agents appeared in the same sample, so the second did "
                "not arrive after the first: %r" % seen)

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
                stored = r.json()["chat"]
                msgs = stored["history"]["messages"].values()
            assistants = [m for m in msgs if m["role"] == "assistant"]

            # An agent's id is minted from the TEMPLATE it was made from and a
            # counter, not from the name its owner sees: the live pair are
            # agent-research-assistant-0001 named Ada and agent-inbox-triage-0002
            # named Mia. So an id prefix says nothing, and hardcoding either the
            # id or the agents a person happens to own would make this a fixture
            # check. What must hold is that the two stored replies are
            # attributed, in order, to the two agents whose names were shown.
            models = [m["model"] for m in assistants][:2]
            assert len(models) == 2, models
            assert models[0] != models[1], models
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get("http://open-webui:8080/api/models",
                                headers={"Authorization": "Bearer " + token})
                listed = r.json()
            listed = listed.get("data", listed) if isinstance(listed, dict) else listed
            name_of = {m.get("id"): (m.get("name") or "") for m in listed}
            assert [name_of.get(m) for m in models] == ["Ada", "Mia"], (
                "stored replies are not attributed to the agents whose names "
                "were shown: %r" % ([(m, name_of.get(m)) for m in models],))

            # The page writes {history} and nothing else. Posting the whole
            # fetched chat back would replace the title Open WebUI generated
            # moments earlier with whatever the page first read, which right
            # after a send is the placeholder.
            title = stored.get("title") or ""
            assert title and title != "New Chat", repr(title)

            # Every marker is consumed as its turn is claimed, so a drained
            # queue leaves none behind to re-run on the next reload.
            assert not any("aiui:turns" in (m.get("content") or "") for m in msgs), (
                "a marker survived the drained queue and would re-run")
            assert not any((m.get("content") or "").startswith("Ada:") for m in assistants)
        finally:
            # A failed assertion must not leave a stray chat behind for the
            # next run to trip over.
            await browser.close()
            if chat_id:
                async with httpx.AsyncClient(timeout=60) as c:
                    await c.delete("http://open-webui:8080/api/v1/chats/" + chat_id,
                                   headers={"Authorization": "Bearer " + token})
