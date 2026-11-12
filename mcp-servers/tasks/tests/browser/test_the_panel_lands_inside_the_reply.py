"""The panel is part of the model's reply, not a box underneath it.

Placement has been wrong three times. After the composer; then in the
thread but as a separate box under the message; then still under it.

The first two attempts failed for the same reason: the markup was
reasoned about rather than read. This fixture is not invented. It is
Open WebUI 0.12's own ResponseMessage source, taken from the source map
of the compiled chunk on the server (D3JjuTf6.js.map), with the Svelte
components rendered out as the elements they produce:

    <div class=" flex w-full message-{id}" id="message-{id}">
      <div class="shrink-0 ...">             the avatar
      <div class="flex-auto w-0 pl-1 relative">
        <Name><Tooltip>
          <span id="response-message-model-name">
        <div>
          <div class="chat-{message.role} w-full min-w-full">
            <div> ...the reply...

Two things that reading it corrected:

  * There ARE per-message ids. "no per-message ids" was wrong; the
    trouble was only ever that message-input-container, the COMPOSER,
    shares the "message-" prefix, which is what the first attempt hit.

  * chat-assistant does exist in the DOM. Grepping the compiled bundle
    for it finds nothing because it is built at runtime from
    `chat-{message.role}`, so searching the build for the literal says
    "absent" about a class that is on screen.

chat-assistant is a GRANDCHILD of the model name span's column, not a
sibling, which is why a walk that checks a sibling's own class falls
through to a looser fallback.
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
    # The thread's gutter is the box's own value now, because marginLeft
    # also carries half the extra width and the two have to compose.
    # These live outside the range above, and a cut missing half a
    # function is a ReferenceError rather than a lesser version of it.
    extra = []
    for name in ("aiuiMaxAppExtra", "aiuiClampAppExtra", "aiuiSavedAppExtra",
                 "aiuiIndentOf", "aiuiApplyAppWidth", "aiuiSetIndent"):
        at = src.index("  function " + name + "(")
        extra.append(src[at:src.index("\n  }\n", at) + 5])
    return finder + "\n" + "\n".join(extra) + "\n" + src[start:end]


def _reply(mid, text):
    """One assistant message, shaped exactly like Open WebUI builds it."""
    return (
        '<div class=" flex w-full message-' + mid + '" id="message-' + mid + '"'
        ' style="scroll-margin-top: 3rem;">'
        '  <div class="shrink-0 ltr:mr-2 rtl:ml-2 hidden mt-0.5">'
        '    <div class="size-7 assistant-message-profile-image"></div>'
        '  </div>'
        '  <div class="flex-auto w-0 pl-1 relative">'
        '    <div class="name">'
        '      <div class="tooltip">'
        '        <span id="response-message-model-name"'
        '              class="line-clamp-1">Auto (Free)</span>'
        '      </div>'
        '    </div>'
        '    <div>'
        '      <div class="chat-assistant w-full min-w-full" data-body="' + mid + '">'
        '        <div><p>' + text + '</p></div>'
        '      </div>'
        '    </div>'
        '  </div>'
        '</div>'
    )


def _user(text):
    return ('<div class=" flex w-full message-u1" id="message-u1">'
            '<div class="flex-auto w-0 pl-1 relative"><div>'
            '<div class="chat-user w-full min-w-full"><div>' + text + '</div></div>'
            '</div></div></div>')


PAGE = """<!doctype html><meta charset="utf-8">
<style>
  body { margin:0; height:100vh; display:flex; flex-direction:column; }
  #messages-container { flex:1 1 auto; display:flex;
                        flex-direction:column-reverse; overflow:auto; }
  #message-input-container { flex:0 0 auto; padding:16px; }
</style>
<div id="messages-container" class="flex flex-col-reverse overflow-auto">
  <div id="thread">%(messages)s</div>
</div>
<div id="message-input-container">the composer</div>
<script>
%(js)s
window.__place = function () {
  var box = document.createElement('div');
  box.id = 'aiui-probe';
  box.textContent = 'the panel';
  box.style.cssText = 'margin:.5rem 0 1rem 3.75rem;padding:10px;';
  aiuiPutUnderLastMessage(box);
};
</script>
"""

MESSAGES = (_user("make me a landing page")
            + _reply("m1", "an earlier reply")
            + _reply("m2", "Your Juice For All landing page is building now."))


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _page(browser, messages=MESSAGES):
    page = browser.new_page()
    page.set_content(PAGE % {"js": _placer(), "messages": messages})
    page.evaluate("window.__place()")
    page.wait_for_selector("#aiui-probe")
    return page


# --- where it goes -------------------------------------------------------

def test_it_is_inside_the_last_reply(browser):
    """The thing asked for three times. Being in the conversation is not
    enough; it has to be in the message."""
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('message-m2')"
        ".contains(document.getElementById('aiui-probe'))") is True
    page.close()


def test_it_is_inside_the_reply_content_itself(browser):
    """chat-assistant is the block holding what the model said. Landing
    beside it, in the column, is still a box next to the message rather
    than part of it."""
    page = _page(browser)
    assert page.evaluate(
        "document.querySelector('[data-body=m2]')"
        ".contains(document.getElementById('aiui-probe'))") is True
    page.close()


def test_it_goes_in_the_last_reply_not_an_earlier_one(browser):
    """The model name id is REUSED on every reply rather than being
    unique, so anything taking the first match lands on the oldest
    message in the chat."""
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('message-m1')"
        ".contains(document.getElementById('aiui-probe'))") is False
    page.close()


def test_it_never_lands_in_the_composer(browser):
    """message-input-container shares the "message-" prefix with every
    real message, and matching on that prefix is the original bug: the
    panel came out under the message box, at the bottom of the page."""
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('message-input-container')"
        ".contains(document.getElementById('aiui-probe'))") is False
    page.close()


def test_it_is_not_put_in_a_message_the_person_wrote(browser):
    page = _page(browser)
    assert page.evaluate(
        "document.getElementById('message-u1')"
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


def test_a_reply_still_being_written_is_not_skipped(browser):
    """A build panel is drawn while the reply is the newest thing on the
    page, which is exactly when it has no buttons under it yet."""
    page = _page(browser, _user("hi") + _reply("m9", "Building now."))
    assert page.evaluate(
        "document.querySelector('[data-body=m9]')"
        ".contains(document.getElementById('aiui-probe'))") is True
    page.close()


# --- when there is no reply to go in -------------------------------------

NO_REPLY = _user("just a question")


def test_with_no_reply_on_the_page_it_still_lands_in_the_conversation(browser):
    """A chat whose last turn is the person's own, or markup that has
    moved again. Falling back into the thread is far better than falling
    back to the bottom of the page, which is the original bug."""
    page = _page(browser, NO_REPLY)
    assert page.evaluate(
        "document.getElementById('messages-container')"
        ".contains(document.getElementById('aiui-probe'))") is True
    panel = page.locator("#aiui-probe").bounding_box()
    composer = page.locator("#message-input-container").bounding_box()
    assert panel["y"] + panel["height"] <= composer["y"] + 1
    page.close()
