"""The panel, on the real site, checked the way a person sees it.

Asserts on rendered text in the browser. The predecessor of this test asserted
on stored `content` while Open WebUI rendered `output`, so it passed on a
screen that was visibly wrong.
"""
import os

import pytest
from playwright.async_api import async_playwright

BASE = os.environ.get("AIUI_BASE", "https://ai-ui.coolestdomain.win")
TOKEN = os.environ.get("AIUI_TOKEN", "")


@pytest.mark.skipif(not TOKEN, reason="needs AIUI_TOKEN for a real sign-in")
async def test_two_agents_answer_in_two_separate_bubbles():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(BASE)
        await page.evaluate("t => localStorage.setItem('token', t)", TOKEN)
        await page.goto(BASE + "/tasks/agents")
        await page.wait_for_selector("#agent-room .chip")

        chips = page.locator("#agent-room .chip")
        first = await chips.nth(0).inner_text()
        second = await chips.nth(1).inner_text()
        await chips.nth(0).click()
        await chips.nth(1).click()
        await page.wait_for_selector("#agent-room .chip.in >> nth=1")

        await page.fill(".ap-composer input", "say hello in one short line")
        await page.click(".ap-composer button")

        # Two agent rows, drawn by us, in the order they were seated.
        await page.wait_for_selector("#agent-thread .am.agent >> nth=1",
                                     timeout=180000)
        rows = page.locator("#agent-thread .am.agent")
        assert await rows.count() >= 2
        who = [await rows.nth(i).locator(".awho").inner_text()
               for i in range(2)]
        assert who == [first.strip(), second.strip()], who

        # Nothing from the old approach leaked into what a person can read.
        body = await page.locator("#agent-thread").inner_text()
        assert "aiui:turns" not in body
        assert "<!--" not in body
        assert not body.strip().startswith(first.strip() + ":")

        await page.screenshot(path="/tmp/agent-panel.png", full_page=True)
        await browser.close()
