"""The Save as your skill button under a chat reply (2026-11-26).

The service appends `[Save as your skill](#aiui-say:save-skill)` after a
workflow or automation was really made. integrations-ui.js turns it into a
button that types one fixed message into the composer and sends it. The page
sends only texts from its own list.
"""
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
UI_JS = HERE.parents[2] / "gdrive" / "integrations-ui.js"
MESSAGE = ("Write a skill from what you just set up for me, "
           "and show it to me before saving.")


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def _section():
    src = UI_JS.read_text(encoding="utf-8")
    start = src.index("  // ===== The assistant's say links =====")
    end = src.index("  function wireAiuiConnectLinks()")
    return src[start:end]


def _reply_page(browser, href, ok=True):
    pg = browser.new_page()
    pg.set_content(
        '<div class="chat-assistant"><p>Done.</p>'
        '<p><a href="%s">Save as your skill</a></p></div>' % href)
    pg.evaluate("(ok) => { window.__sent = []; window.__ok = ok; }", ok)
    pg.add_script_tag(content=(
        "function aiuiSendToChat(t, done) { window.__sent.push(t); done(window.__ok); }\n"
        + _section() + "\nwindow.__wire = wireAiuiSayLink;"))
    pg.evaluate("() => document.querySelectorAll('a').forEach(a => window.__wire(a))")
    return pg


def test_the_link_becomes_a_button_that_sends_the_fixed_text(browser):
    pg = _reply_page(browser, "#aiui-say:save-skill")
    try:
        btn = pg.locator(".aiui-say-inline button")
        assert btn.inner_text() == "Save as your skill"
        btn.click()
        assert pg.evaluate("() => window.__sent") == [MESSAGE]
        assert btn.inner_text() == "✓ Asked"
        assert btn.is_disabled()
    finally:
        pg.close()


def test_a_full_message_box_is_not_overwritten(browser):
    pg = _reply_page(browser, "#aiui-say:save-skill", ok=False)
    try:
        btn = pg.locator(".aiui-say-inline button")
        btn.click()
        assert btn.inner_text() == "Send or clear your message first, then press again"
        assert btn.is_enabled()
    finally:
        pg.close()


def test_an_id_not_on_the_list_stays_a_plain_link(browser):
    for href in ("#aiui-say:other", "#aiui-say:",
                 "#aiui-say:__proto__", "#aiui-say:toString"):
        pg = _reply_page(browser, href)
        try:
            assert pg.locator(".aiui-say-inline").count() == 0, href
            assert pg.locator("a").count() == 1, href
        finally:
            pg.close()
