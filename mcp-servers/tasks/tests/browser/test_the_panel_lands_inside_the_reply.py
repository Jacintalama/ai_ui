"""The panel is part of the model's reply, not a box underneath it.

Placement has been wrong three times now. First it went after the
composer, at the bottom of the page. Then it went into the thread, which
put it in the conversation but as a SEPARATE box sitting under the
message, with its own border and a rule above it. What was wanted both
times is the panel inside the reply itself, the way a canvas is part of
what the model said.

The walk from a reply to its content block is aiuiFindReplyBody, which
the agent name header has used in production since September. That is
the difference from the two earlier attempts: this is markup that is
already known to work, not markup reasoned about from a source map.

The fixture is Open WebUI 0.12's reply shape: a reused (not unique)
#response-message-model-name span for the model name, and a sibling div
whose class starts with "chat-" holding the text.
"""
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")


def _placer():
    """The real placing code, plus the body walk it leans on."""
    src = JS.read_text(encoding="utf-8")

    finder_start = src.index("  function aiuiFindReplyBody(")
    finder_end = src.index("\n  // Only the very first content of the body")
    finder = src[finder_start:finder_end]

    start = src.index("  function aiuiScroller()")
    end = src.index("\n  function ", src.index("function aiuiPutUnderLastMessage"))
    return finder + "\n" + src[start:end]


PAGE = """<!doctype html><meta charset="utf-8">
<style>
  body { margin:0; height:100vh; display:flex; flex-direction:column; }
  #messages-container { flex:1 1 auto; display:flex;
                        flex-direction:column-reverse; overflow:auto; }
  #message-input-container { flex:0 0 auto; padding:16px; }
</style>
<div id="messages-container" class="flex flex-col-reverse overflow-auto">
  <div id="thread">
    <div class="msg" data-m="1">make me a landing page</div>

    <div class="reply" id="reply-one">
      <div class="flex items-center">
        <span id="response-message-model-name">Auto (Free)</span>
      </div>
      <div class="chat-assistant markdown-prose" id="body-one">
        an earlier reply
      </div>
    </div>

    <div class="reply" id="reply-two">
      <div class="flex items-center">
        <span id="response-message-model-name">Auto (Free)</span>
      </div>
      <div class="chat-assistant markdown-prose" id="body-two">
        Building your JuiceThere landing page now.
      </div>
    </div>
  </div>
</div>
<div id="message-input-container">the composer</div>
<script>
%s
window.__place = function () {
  var box = document.createElement('div');
  box.id = 'aiui-probe';
  box.textContent = 'the panel';
  box.style.cssText = 'margin:.5rem 0 1rem 3.75rem;padding:10px;';
  aiuiPutUnderLastMessage(box);
};
</script>
"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _page(browser, html=PAGE):
    page = browser.new_page()
    page.set_content(html % _placer())
    page.evaluate("window.__place()")
    page.wait_for_selector("#aiui-probe")
    return page


# --- where it goes -------------------------------------------------------

def test_it_is_inside_the_reply_not_a_sibling_of_it(browser):
    """The thing asked for three times. Being in the conversation is not
    enough; it has to be in the message."""
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('body-two')"
        ".contains(document.getElementById('aiui-probe'))") is True
    page.close()


def test_it_goes_in_the_last_reply_not_an_earlier_one(browser):
    """The model name id is REUSED on every reply rather than being
    unique, so anything taking the first match lands on the oldest
    message in the chat."""
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('body-one')"
        ".contains(document.getElementById('aiui-probe'))") is False
    page.close()


def test_the_indent_for_the_thread_is_dropped_inside_the_reply(browser):
    """Every panel carries a left margin to clear the avatar gutter. The
    reply already provides that gutter, so keeping it indents the panel
    twice and it no longer lines up with the text above it."""
    page = _page(browser)
    assert page.evaluate(
        "getComputedStyle(document.getElementById('aiui-probe')).marginLeft"
    ) == "0px"
    page.close()


def test_it_still_comes_out_above_the_composer(browser):
    """The original bug. Worth keeping even though the mechanism changed,
    because it is the thing a person actually sees go wrong."""
    page = _page(browser)
    panel = page.locator("#aiui-probe").bounding_box()
    composer = page.locator("#message-input-container").bounding_box()
    assert panel["y"] + panel["height"] <= composer["y"] + 1
    page.close()


# --- when there is no reply to go in -------------------------------------

NO_REPLY = """<!doctype html><meta charset="utf-8">
<style>
  body { margin:0; height:100vh; display:flex; flex-direction:column; }
  #messages-container { flex:1 1 auto; display:flex;
                        flex-direction:column-reverse; overflow:auto; }
  #message-input-container { flex:0 0 auto; padding:16px; }
</style>
<div id="messages-container" class="flex flex-col-reverse overflow-auto">
  <div id="thread"><div class="msg">just a question</div></div>
</div>
<div id="message-input-container">the composer</div>
<script>
%s
window.__place = function () {
  var box = document.createElement('div');
  box.id = 'aiui-probe';
  box.textContent = 'the panel';
  aiuiPutUnderLastMessage(box);
};
</script>
"""


def test_with_no_reply_on_the_page_it_still_lands_in_the_conversation(browser):
    """A chat whose last turn is the person's own, or markup that has
    moved again. Falling back into the thread is far better than falling
    back to the bottom of the page, which is the original bug."""
    page = _page(browser, NO_REPLY)
    # The scroller, not the inner wrapper: with nothing to go after, the
    # existing path inserts at the scroller's start, which in a
    # flex-col-reverse scroller is the BOTTOM of the conversation. What
    # matters is that it is in the scroller and below the last message,
    # which the geometry below is the real check of.
    assert page.evaluate(
        "document.getElementById('messages-container')"
        ".contains(document.getElementById('aiui-probe'))") is True
    panel = page.locator("#aiui-probe").bounding_box()
    last = page.locator(".msg").last.bounding_box()
    composer = page.locator("#message-input-container").bounding_box()
    assert panel["y"] >= last["y"], "it came out above the conversation"
    assert panel["y"] + panel["height"] <= composer["y"] + 1
