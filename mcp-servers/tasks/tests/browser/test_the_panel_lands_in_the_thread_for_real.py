"""The panel lands in the conversation, checked in a real browser.

This bug shipped TWICE. The panel and the build box were inserted after
the message box, at the bottom of the page, outside the conversation, and
both times a structural test passed while Ralph's screenshot showed it in
the wrong place.

Structural tests could not catch it because the mistake was never in the
shape of the code. It was in what the markup actually is: Open WebUI 0.12
has no per-message ids, the only id starting with "message-" is
"message-input-container" (the composer), and the scroller is
flex-col-REVERSE, so appending to it puts a panel at the TOP.

So this asserts GEOMETRY in a real browser: the panel must come out below
the last reply and above the composer, which is the thing a person sees.

The page is a fixture of Open WebUI 0.12's chat markup, taken from the
compiled bundle on the server, not invented:

    <div id="messages-container" class="... flex flex-col-reverse overflow-auto">
      <div> ...the messages... </div>
    </div>
    <div id="message-input-container"> ...the composer... </div>

The JavaScript is the real integrations-ui.js, cut to the three functions
that do the placing.
"""
import pathlib
import re

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")


def _placer():
    """The real placing code, cut out of the real file."""
    src = JS.read_text(encoding="utf-8")
    # From the ACCESSORS, not from aiuiThread: aiuiScroller and
    # aiuiComposer are defined above it and it calls them, so slicing
    # lower leaves the real code with an undefined reference.
    start = src.index("  function aiuiScroller()")
    end = src.index("\n  function ", src.index("function aiuiPutUnderLastMessage"))
    return src[start:end]


#: Open WebUI 0.12's chat, as the compiled bundle renders it. The classes
#: matter: flex-col-reverse is why "append to the scroller" is wrong.
PAGE = """<!doctype html><meta charset="utf-8">
<style>
  body { margin:0; height:100vh; display:flex; flex-direction:column; }
  #messages-container { flex:1 1 auto; display:flex; flex-direction:column-reverse;
                        overflow:auto; }
  .msg { padding:14px; }
  #message-input-container { flex:0 0 auto; padding:16px; background:#222; }
</style>
<div id="messages-container" class="flex flex-col-reverse overflow-auto">
  <div id="thread">
    <div class="msg" data-m="1">first message</div>
    <div class="msg" data-m="2">second message</div>
    <div class="msg" data-m="3">the reply the panel belongs under</div>
  </div>
</div>
<div id="message-input-container">the composer</div>
<script>
%s
window.__place = function () {
  var box = document.createElement('div');
  box.id = 'aiui-probe';
  box.textContent = 'the panel';
  box.style.cssText = 'padding:10px;background:#6b73ff;color:#fff;';
  aiuiPutUnderLastMessage(box);
};
</script>
"""


@pytest.fixture(scope="module")
def browser():
    """Driven directly, the way every other test in this directory does
    it: pytest-playwright is not installed here, so there is no `page`
    fixture to borrow."""
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture
def page_with_chat(page):
    page.set_content(PAGE % _placer())
    page.evaluate("window.__place()")
    return page


def _box(page, sel):
    return page.evaluate(
        "s => { const e = document.querySelector(s);"
        "       if (!e) return null;"
        "       const r = e.getBoundingClientRect();"
        "       return {top: r.top, bottom: r.bottom}; }", sel)


def test_the_panel_exists_at_all(page_with_chat):
    assert page_with_chat.locator("#aiui-probe").count() == 1


def test_it_is_not_dumped_at_the_end_of_the_page(page_with_chat):
    """document.body.appendChild is the fallback, and it is what happened
    for two days. A panel there sits under the composer."""
    parent = page_with_chat.evaluate(
        "document.getElementById('aiui-probe').parentElement.id")
    assert parent != "", "the panel is a direct child of body"
    assert parent != "message-input-container"


def test_it_is_inside_the_conversation(page_with_chat):
    inside = page_with_chat.evaluate(
        "document.getElementById('messages-container')"
        ".contains(document.getElementById('aiui-probe'))")
    assert inside, "the panel is outside the message list"


def test_it_appears_below_the_last_reply(page_with_chat):
    """The geometry, which is what a person actually sees. In a reversed
    column, appending to the scroller would put this ABOVE every message
    while still being 'inside the conversation', so containment alone is
    not enough."""
    last = _box(page_with_chat, '[data-m="3"]')
    panel = _box(page_with_chat, "#aiui-probe")
    assert panel["top"] >= last["top"], (
        "the panel is above the reply it belongs under: %s vs %s"
        % (panel, last))


def test_it_appears_above_the_composer(page_with_chat):
    """This is the bug Ralph reported twice, in one assertion."""
    panel = _box(page_with_chat, "#aiui-probe")
    composer = _box(page_with_chat, "#message-input-container")
    assert panel["bottom"] <= composer["top"] + 1, (
        "the panel is below the message box: %s vs %s" % (panel, composer))


def test_a_page_with_no_chat_still_places_it_somewhere(page):
    """Open WebUI's markup will move again. Losing the panel entirely is
    worse than putting it somewhere visible, and the code warns when it
    falls back."""
    page.set_content(
        "<!doctype html><meta charset=utf-8><div>no chat here</div>"
        "<script>%s\nvar b=document.createElement('div');b.id='aiui-probe';"
        "aiuiPutUnderLastMessage(b);</script>" % _placer())
    assert page.locator("#aiui-probe").count() == 1
