"""A panel belongs to the message that announced it, and nowhere else.

Ralph, 2026-11-10, with a screenshot: the landing page panel was sitting
under a reply about a ClickUp task. "it should stay in the last output or
result", pointing at the message that says the app is built.

Measured in his chat before writing any of this, read-only off the box:

    history.messages: 22
    #10  assistant  03b4d7e3-...  [aiui-artifact]: #app/aiui-landing-2d50
                                  "aiui-landing-2d50 is built."
    last assistant   d8795492-...  mentions the slug: False
                                  "Done, "Buy milk 7" is created ..."

So exactly ONE message declares it and the message it landed in never
mentions it. The panel was not mis-found, it was mis-PLACED, and by two
separate routes:

1. `aiuiReplyFor` looked for the declaring message, did not find it on
   the page, counted three looks and then returned null. Every caller
   reads null as "no particular reply", which means
   `aiuiPutUnderLastMessage`. A burst from the mutation observer spends
   three looks in milliseconds, so a message that simply had not painted
   yet was treated as gone forever. Not drawing yet is recoverable: the
   scan runs again every few seconds. Drawing it inside somebody else's
   message is not.

2. `aiuiWatchBuilds` read the WHOLE thread as one innerHTML blob and
   called the draw with no message id at all, so anything it found was
   placed by route 1's fallback by construction. The blob cannot see the
   marker either, because a markdown link reference definition renders to
   nothing, so the only thing it can match in rendered HTML is a
   preview-app URL in the prose, or the slug in a panel's OWN iframe src.
   That last one is why this compounds: once a panel is in the wrong
   message, the blob keeps finding it there.

The fixture markup is Open WebUI 0.12's own ResponseMessage, same source
as tests/browser/test_the_panel_lands_inside_the_reply.py, which holds
the other half of this contract: WHERE in a reply a panel goes. This file
is about WHICH reply.
"""
import pathlib
import re

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")

#: The slug and ids are the real ones out of the chat above.
SLUG = "aiui-landing-2d50"
DECLARED_IN = "03b4d7e3-f126-4e97-b527-35d9f3633cfb"
LAST_REPLY = "d8795492-42b9-43c8-9be6-79fbedc31203"


def _fn(src, name):
    """One function out of the file, by matching its braces.

    By name rather than by line range, because a range silently captures
    the wrong thing the moment anything above it moves.
    """
    start = src.index("  function " + name + "(")
    depth, i, seen = 0, src.index("{", start), False
    while i < len(src):
        if src[i] == "{":
            depth += 1
            seen = True
        elif src[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError("no end found for " + name)


def _carries(src):
    """The block that reads what a reply declares, consts and all."""
    a = src.index("  // ===== What a reply carries =====")
    b = src.index("  // ===== End what a reply carries =====")
    return src[a:b]


def _js():
    src = JS.read_text(encoding="utf-8")
    parts = [_carries(src)]
    # aiuiPutInReply sets the thread's gutter, which is now the box's own
    # value rather than a raw marginLeft, because that margin also carries
    # half the extra width and the two have to compose.
    for name in ("aiuiMessageRowOf", "aiuiMessageIdOf", "aiuiAppsDeclaredIn",
                 "aiuiReplyFor", "aiuiMaxAppExtra", "aiuiClampAppExtra",
                 "aiuiSavedAppExtra", "aiuiIndentOf", "aiuiApplyAppWidth",
                 "aiuiSetIndent", "aiuiPutInReply"):
        parts.append(_fn(src, name))
    return "\n".join(parts)


def _reply(mid, inner):
    return (
        '<div class=" flex w-full message-' + mid + '" id="message-' + mid + '">'
        '  <div class="shrink-0 ltr:mr-2 rtl:ml-2 hidden mt-0.5">'
        '    <div class="size-7 assistant-message-profile-image"></div>'
        '  </div>'
        '  <div class="flex-auto w-0 pl-1 relative">'
        '    <div class="name"><div class="tooltip">'
        '      <span id="response-message-model-name">Auto (Free)</span>'
        '    </div></div>'
        '    <div>'
        '      <div class="chat-assistant w-full min-w-full" data-body="' + mid + '">'
        '        <div>' + inner + '</div>'
        '      </div>'
        '    </div>'
        '  </div>'
        '</div>'
    )


def _user(mid, inner):
    return ('<div class=" flex w-full message-' + mid + '" id="message-' + mid + '">'
            '<div class="flex-auto w-0 pl-1 relative"><div>'
            '<div class="chat-user w-full min-w-full"><div>' + inner + '</div></div>'
            '</div></div></div>')


PAGE = """<!doctype html><meta charset="utf-8">
<div id="messages-container">
  <div id="thread">%(messages)s</div>
</div>
<div id="message-input-container">
  the composer, carrying /tasks/preview-app/%(slug)s/ in a draft
</div>
<script>
%(js)s
window.__declared = function () {
  return aiuiAppsDeclaredIn(document.getElementById('thread'));
};
window.__replyFor = function (key, mid) {
  var r = aiuiReplyFor(key, mid);
  return r === undefined ? 'wait' : (r === null ? 'no-particular-reply'
                                     : 'found:' + r.getAttribute('data-body'));
};
</script>
"""

#: The app announced early, the chat carried on. Rendered HTML, so the
#: marker is absent exactly as it is on a real page: what is left is the
#: URL the closing message writes.
BUILT = ('aiui-landing-2d50 is built. Open it here: '
         '<a href="/tasks/preview-app/' + SLUG + '/">' + SLUG + '</a>')
LATER = ('Done, "Buy milk 7" is created in Project 1 and assigned to '
         'ralph: <a href="https://app.clickup.com/t/14zhcp5g0qq">link</a>')

MESSAGES = (_user("u1", "build me a landing page")
            + _reply(DECLARED_IN, BUILT)
            + _user("u2", "create a ClickUp task called Buy milk 7")
            + _reply(LAST_REPLY, LATER))


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _page(browser, messages=MESSAGES):
    page = browser.new_page()
    page.set_content(PAGE % {"js": _js(), "messages": messages,
                             "slug": SLUG})
    return page


# --- which message declared it -----------------------------------------

def test_the_app_is_paired_with_the_message_that_announced_it(browser):
    page = _page(browser)
    got = page.evaluate("window.__declared()")
    assert got == [{"slug": SLUG, "messageId": DECLARED_IN}], got
    page.close()


def test_a_later_reply_does_not_claim_an_app_it_never_mentioned(browser):
    """The whole of Ralph's bug in one assertion."""
    page = _page(browser)
    got = page.evaluate("window.__declared()")
    assert [g["messageId"] for g in got] == [DECLARED_IN]
    assert LAST_REPLY not in [g["messageId"] for g in got]
    page.close()


def test_a_panel_already_in_the_wrong_reply_does_not_keep_it_there(browser):
    """A panel's own iframe src carries the slug, so a blob scan finds it
    wherever the panel already is. The message that SAID it is built is
    the answer, so the earliest declaration wins."""
    wrong = _reply(LAST_REPLY, LATER + '<div id="aiui-app-' + SLUG + '">'
                   '<iframe src="/tasks/preview-app/' + SLUG + '/"></iframe>'
                   '</div>')
    page = _page(browser, _user("u1", "hi") + _reply(DECLARED_IN, BUILT) + wrong)
    got = page.evaluate("window.__declared()")
    assert [g["messageId"] for g in got] == [DECLARED_IN], got
    page.close()


def test_what_the_person_pasted_is_not_a_declaration(browser):
    """A link in somebody's own message is not the platform saying it
    built something."""
    page = _page(browser, _user("u1", 'see /tasks/preview-app/' + SLUG + '/'))
    assert page.evaluate("window.__declared()") == []
    page.close()


def test_the_composer_is_never_read_as_a_message(browser):
    """message-input-container shares the "message-" prefix, and a draft
    in it mentions the slug in this fixture on purpose."""
    page = _page(browser)
    got = page.evaluate("window.__declared()")
    assert all(g["messageId"] != "input-container" for g in got), got
    assert all(g["messageId"] for g in got), got
    page.close()


def test_an_empty_thread_declares_nothing(browser):
    page = _page(browser, "")
    assert page.evaluate("window.__declared()") == []
    page.close()


def test_each_app_is_named_once_however_often_it_appears(browser):
    page = _page(browser, _reply(DECLARED_IN, BUILT + " " + BUILT))
    assert page.evaluate("window.__declared()") == [
        {"slug": SLUG, "messageId": DECLARED_IN}]
    page.close()


# --- waiting is not the same as giving up ------------------------------

def test_a_message_not_on_the_page_yet_is_waited_for_not_replaced(browser):
    """It used to answer "no particular reply" on the fourth look, and
    every caller turns that into the last reply. The mutation observer
    can spend four looks before the page has painted."""
    page = _page(browser)
    for attempt in range(12):
        got = page.evaluate("window.__replyFor('aiui-app-x', 'not-here-yet')")
        assert got == "wait", (attempt, got)
    page.close()


def test_the_message_it_belongs_to_is_the_one_it_is_given(browser):
    page = _page(browser)
    assert page.evaluate(
        "window.__replyFor('k', '" + DECLARED_IN + "')"
    ) == "found:" + DECLARED_IN
    page.close()


def test_with_no_message_id_there_is_still_no_particular_reply(browser):
    """The genuinely unknown case, where the last reply IS the right
    answer: a build finishing in front of the person, with nothing saved
    yet. That path must keep working."""
    page = _page(browser)
    assert page.evaluate("window.__replyFor('k', '')") == "no-particular-reply"
    assert page.evaluate("window.__replyFor('k', null)") == "no-particular-reply"
    page.close()


def test_a_message_the_person_wrote_is_not_a_reply_to_put_things_in(browser):
    """u1 exists and has no chat-assistant in it, so this must wait for a
    real reply rather than place the panel in somebody's own words."""
    page = _page(browser)
    assert page.evaluate("window.__replyFor('k', 'u1')") == "wait"
    page.close()


# --- and it still lands inside that reply ------------------------------

def test_the_panel_goes_into_its_own_reply_and_not_the_newest(browser):
    page = _page(browser)
    page.evaluate(
        "(function () {"
        "  var d = window.__declared()[0];"
        "  var body = aiuiReplyFor('aiui-app-' + d.slug, d.messageId);"
        "  var box = document.createElement('div');"
        "  box.id = 'aiui-app-' + d.slug;"
        "  box.style.marginLeft = '3.75rem';"
        "  aiuiPutInReply(box, body);"
        "})()")
    assert page.evaluate(
        "document.querySelector('[data-body=\"" + DECLARED_IN + "\"]')"
        ".contains(document.getElementById('aiui-app-" + SLUG + "'))") is True
    assert page.evaluate(
        "document.getElementById('message-" + LAST_REPLY + "')"
        ".contains(document.getElementById('aiui-app-" + SLUG + "'))") is False
    page.close()


def test_the_double_indent_is_still_dropped_inside_the_reply(browser):
    """aiuiPutInReply clears it, the same as aiuiPutUnderLastMessage. The
    reply already provides the avatar gutter."""
    page = _page(browser)
    page.evaluate(
        "(function () {"
        "  var box = document.createElement('div');"
        "  box.id = 'probe';"
        "  box.style.marginLeft = '3.75rem';"
        "  aiuiPutInReply(box, aiuiReplyFor('k', '" + DECLARED_IN + "'));"
        "})()")
    assert page.evaluate(
        "getComputedStyle(document.getElementById('probe')).marginLeft"
    ) == "0px"
    page.close()


# --- the file itself ---------------------------------------------------

def test_nothing_scans_the_whole_thread_for_apps_any_more():
    """The blob scan cannot carry a message id, so a slug it finds can
    only ever be placed by the fallback. Asserted against the source
    because the defect is the absence of a message id, which no fixture
    can show."""
    src = JS.read_text(encoding="utf-8")
    assert "aiuiArtifactIds(html, 'app')" not in src
    assert re.search(r"aiuiAppsDeclaredIn\(\s*thread\s*\)", src), \
        "aiuiWatchBuilds should pair each app with its own message"
