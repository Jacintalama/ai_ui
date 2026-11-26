"""The Save as your skill button under a chat reply (2026-11-26).

The service appends `[Save as your skill](#aiui-say:save-skill)` after a
workflow or automation was really made. integrations-ui.js turns it into a
button that types one fixed message into the composer and sends it. The page
sends only texts from its own list, under its own label, and only from the
latest reply: after a reload every reply is drawn again, and "what you just
set up" is true of the latest one only.
"""
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
UI_JS = HERE.parents[2] / "gdrive" / "integrations-ui.js"
MESSAGE = ("Write a skill from what you just set up for me, "
           "and show it to me before saving.")
RETRY = "Wait for the reply to finish or clear your message, then press again"
STALE = "Only works on the latest reply"
NL = "\n"


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def _cut(src, start, end):
    at = src.index(start)
    return src[at:src.index(end, at)]


def _function(src, name):
    """One whole function from the file, by its two-space indent."""
    at = src.index("  function %s(" % name)
    close = NL + "  }" + NL
    return src[at:src.index(close, at) + len(close)]


def _section():
    """The say links, plus the real helpers they lean on that live in other
    sections: which message a node is in, and which reply is the latest."""
    src = UI_JS.read_text(encoding="utf-8")
    return NL.join([
        _cut(src, "  // ===== The assistant's say links =====",
             "  function wireAiuiConnectLinks()"),
        _function(src, "aiuiMessageRowOf"),
        _function(src, "aiuiMessageOf"),
        _function(src, "aiuiLastReply"),
    ])


SEND_STUB = ("function aiuiSendToChat(t, done) "
             "{ window.__sent.push(t); done(window.__ok); }")


def _reply(n, href, label="Save as your skill"):
    return ('<div id="message-%d"><div class="chat-assistant"><p>Done.</p>'
            '<p><a href="%s">%s</a></p></div></div>' % (n, href, label))


def _page(browser, body, ok=True):
    pg = browser.new_page()
    pg.set_content(body)
    pg.evaluate("(ok) => { window.__sent = []; window.__ok = ok; }", ok)
    pg.add_script_tag(content=NL.join(
        [SEND_STUB, _section(), "window.__wire = wireAiuiSayLink;"]))
    pg.evaluate("() => document.querySelectorAll('a').forEach(a => window.__wire(a))")
    return pg


def _reply_page(browser, href, ok=True, label="Save as your skill"):
    return _page(browser,
                 '<div id="message-0"><div class="chat-user">make it</div></div>'
                 + _reply(1, href, label), ok=ok)


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


def test_a_send_that_did_not_happen_says_what_to_do(browser):
    """done(false): the box held text, or Send never came because a reply
    was still running. The words cover both."""
    pg = _reply_page(browser, "#aiui-say:save-skill", ok=False)
    try:
        btn = pg.locator(".aiui-say-inline button")
        btn.click()
        assert btn.inner_text() == RETRY
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


def test_the_label_is_ours_not_the_links(browser):
    pg = _reply_page(browser, "#aiui-say:save-skill", label="Do something else")
    try:
        btn = pg.locator(".aiui-say-inline button")
        assert btn.inner_text() == "Save as your skill"
        btn.click()
        assert pg.evaluate("() => window.__sent") == [MESSAGE]
    finally:
        pg.close()


def test_only_the_latest_reply_sends(browser):
    """After a reload every reply is drawn again."""
    pg = _page(browser,
               _reply(1, "#aiui-say:save-skill")
               + '<div id="message-2"><div class="chat-user">and another</div></div>'
               + _reply(3, "#aiui-say:save-skill"))
    try:
        old = pg.locator("#message-1 .aiui-say-inline button")
        new = pg.locator("#message-3 .aiui-say-inline button")
        assert old.inner_text() == STALE
        assert old.is_disabled()
        old.click(force=True)
        assert pg.evaluate("() => window.__sent") == []
        assert new.inner_text() == "Save as your skill"
        new.click()
        assert pg.evaluate("() => window.__sent") == [MESSAGE]
    finally:
        pg.close()


def test_a_button_that_stopped_being_the_latest_does_not_send(browser):
    """Live when it was drawn, then a newer reply arrived: checked again at
    the click."""
    pg = _reply_page(browser, "#aiui-say:save-skill")
    try:
        btn = pg.locator(".aiui-say-inline button")
        assert btn.is_enabled()
        pg.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
            '<div id="message-2"><div class="chat-user">x</div></div>'
            + '<div id="message-3"><div class="chat-assistant"><p>Later.</p></div></div>')""")
        btn.click()
        assert pg.evaluate("() => window.__sent") == []
        assert btn.inner_text() == STALE
        assert btn.is_disabled()
    finally:
        pg.close()


def test_the_page_scan_wires_a_say_link_that_appears(browser):
    """wireAiuiConnectLinks' scan picks the say links up, including one
    drawn after the page loaded (the MutationObserver path)."""
    src = UI_JS.read_text(encoding="utf-8")
    pg = browser.new_page()
    try:
        pg.set_content('<div id="message-0"><div class="chat-user">hi</div></div>')
        pg.evaluate("() => { window.__sent = []; window.__ok = true; }")
        pg.add_script_tag(content=NL.join([
            "var AIUI_CONNECT_MARKER = '#aiui-connect:';",
            "var AIUI_OPEN_MARKER = '#aiui-open:';",
            "function wireAiuiConnectLink() {}",
            "function wireAiuiOpenLink() {}",
            SEND_STUB, _section(), _function(src, "wireAiuiConnectLinks"),
            "wireAiuiConnectLinks();"]))
        pg.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
            '<div id="message-1"><div class="chat-assistant"><p>Done.</p>'
            + '<p><a href="#aiui-say:save-skill">Save as your skill</a></p></div></div>')""")
        btn = pg.locator(".aiui-say-inline button")
        btn.wait_for(timeout=2000)
        btn.click()
        assert pg.evaluate("() => window.__sent") == [MESSAGE]
    finally:
        pg.close()
