"""The panel, on the real site, checked the way a person sees it.

Asserts on rendered text in the browser. The predecessor of this test asserted
on stored `content` while Open WebUI rendered `output`, so it passed on a
screen that was visibly wrong.

Two things this test has to get right about the real site, both of which cost
a run each before they were understood:

* The form posts carry the token as a bearer header, but the stream is an
  EventSource, which cannot send headers, so it authenticates on the cookie.
  With no cookie the gateway forwards an empty identity, the stream 401s, and
  the test waits out its whole timeout on a page that will never fill in.
* The room is a server-side session with a two hour TTL, so a second run
  within two hours arrives with agents already seated. Clicking a chip that
  is already in takes it OUT. The room is therefore cleared and rebuilt here
  rather than assumed empty. New chat is not an escape hatch: it keeps the
  room on purpose.
"""
import os
from urllib.parse import urlparse

import pytest
from playwright.async_api import async_playwright

BASE = os.environ.get("AIUI_BASE", "https://ai-ui.coolestdomain.win")
TOKEN = os.environ.get("AIUI_TOKEN", "")
SHOT = os.environ.get("AIUI_SHOT", "/tmp/agent-panel.png")

_SEATED = "#agent-room .chip.in"
_SEATED_COUNT = ("n => document.querySelectorAll('%s').length === n" % _SEATED)


async def _seated(page) -> int:
    return await page.locator(_SEATED).count()


async def _set_room_to_two(page) -> tuple[str, str]:
    """Leave exactly two agents in the room and say who, in seating order."""
    while await _seated(page) > 0:
        want = await _seated(page) - 1
        await page.locator(_SEATED).first.click()
        await page.wait_for_function(_SEATED_COUNT, arg=want, timeout=15000)

    chips = page.locator("#agent-room .chip")
    if await chips.count() < 2:
        pytest.skip("needs at least two agents on this account")
    first = (await chips.nth(0).inner_text()).strip()
    second = (await chips.nth(1).inner_text()).strip()

    # One at a time, waiting for each swap: the chip row replaces itself, so
    # a second click before the swap lands would go to a detached element.
    await page.locator("#agent-room .chip").nth(0).click()
    await page.wait_for_function(_SEATED_COUNT, arg=1, timeout=15000)
    await page.locator("#agent-room .chip").nth(1).click()
    await page.wait_for_function(_SEATED_COUNT, arg=2, timeout=15000)
    return first, second


@pytest.mark.skipif(not TOKEN, reason="needs AIUI_TOKEN for a real sign-in")
async def test_two_agents_answer_in_two_separate_bubbles():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1600, "height": 1000})
        # Both, and for the reason in the module docstring: the posts read the
        # bearer header, the stream reads the cookie.
        await ctx.add_cookies([{"name": "token", "value": TOKEN,
                                "domain": urlparse(BASE).hostname,
                                "path": "/"}])
        page = await ctx.new_page()
        await page.goto(BASE, wait_until="domcontentloaded")
        await page.evaluate("t => localStorage.setItem('token', t)", TOKEN)
        await page.goto(BASE + "/tasks/agents")
        await page.wait_for_selector("#agent-room .chip")

        first, second = await _set_room_to_two(page)

        await page.fill(".ap-composer input", "say hello in one short line")
        await page.click(".ap-composer button")

        # A round can hold the page for minutes, so it must read as slow
        # rather than as broken while it runs. This line is the only thing
        # that says so, and it is only ever on screen if the stream is
        # actually arriving in pieces.
        working = await page.wait_for_selector(".aworking", timeout=120000)
        line = (await working.inner_text()).strip()
        assert line.endswith("is working..."), line

        # Two agent rows, drawn by us, in the order they were seated. An
        # agent that stops to ask permission gets a bubble with this class
        # too, and it holds a second .atext, so it is left out here.
        answers = "#agent-thread .am.agent:not(.awaiting)"
        await page.wait_for_selector(answers + " >> nth=1", timeout=180000)
        rows = page.locator(answers)
        assert await rows.count() >= 2
        who = [(await rows.nth(i).locator(".awho").inner_text()).strip()
               for i in range(2)]
        assert who == [first, second], who

        # What the two agents actually said, as a person reads it. Every
        # assertion below is on this and not on the thread as a whole: the
        # thread also holds the message that was typed, which legitimately
        # starts with whatever was typed.
        said = [(await rows.nth(i).locator(".atext").inner_text()).strip()
                for i in range(2)]
        assert all(said), "an agent bubble arrived with nothing in it"

        for name, text in zip(who, said):
            # The marker the rolled-back attempt smuggled state in. Open
            # WebUI escaped it and printed it, so it reached the screen as
            # readable text, which is exactly what inner_text returns.
            assert "aiui:turns" not in text, text
            assert "<!--" not in text, text
            # And the stray speaker label the same attempt left behind. Each
            # answer is its own bubble with its own name above it, so no
            # answer has any business naming its speaker again.
            for label in (name, first, second):
                assert not text.startswith(label + ":"), (label, text)

        # The invitation is not still sitting on top of a conversation.
        assert await page.locator("#agent-thread .aempty").count() == 0

        await page.screenshot(path=SHOT, full_page=True)
        await browser.close()
