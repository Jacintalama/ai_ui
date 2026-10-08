"""The panel is actually on the page.

A route nobody reaches is not a feature. This checks the page carries the
panel, its scripts, and the elements the fragments target, because the last
attempt shipped with the server side correct and the screen wrong.
"""
import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parents[1] / "static"
PAGE = STATIC / "agents.html"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _script() -> str:
    return (STATIC / "agent-chat.js").read_text(encoding="utf-8")


def _styles() -> str:
    return (STATIC / "agent-chat.css").read_text(encoding="utf-8")


def test_the_page_loads_htmx_and_its_sse_extension():
    html = _page()
    assert "/tasks/static/vendor/htmx.min.js" in html
    assert "/tasks/static/vendor/sse.js" in html


def test_the_page_loads_the_panel_styles_and_script():
    html = _page()
    assert "/tasks/static/agent-chat.css" in html
    assert "/tasks/static/agent-chat.js" in html


def test_the_panel_has_the_targets_the_fragments_swap_into():
    html = _page()
    for target in ('id="agent-panel"', 'id="agent-thread"',
                   'id="ap-clear"', 'id="ap-clear-overlay"'):
        assert target in html, target


def test_the_page_is_two_columns():
    html = _page()
    assert 'class="agents-layout"' in html
    assert 'class="agents-main"' in html


def test_the_composer_posts_to_send_and_appends_to_the_thread():
    html = _page()
    assert 'hx-post="/tasks/agents/chat/send"' in html
    assert 'hx-target="#agent-thread"' in html
    assert 'hx-swap="beforeend"' in html


def test_the_router_is_wired_in():
    main = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8")
    assert "routes_agent_chat" in main
    assert "agent_chat_router" in main


def test_the_page_can_render_the_markdown_an_answer_comes_back_as():
    """Without these an answer shows its asterisks and hashes. Both are
    already vendored for the Fusion page."""
    html = _page()
    assert "/tasks/static/vendor/marked.min.js" in html
    assert "/tasks/static/vendor/purify.min.js" in html
    for name in ("marked.min.js", "purify.min.js"):
        assert (STATIC / "vendor" / name).exists(), name


def test_model_output_is_sanitized_before_it_is_inserted():
    js = _script()
    assert "DOMPurify.sanitize(marked.parse(" in js, (
        "markdown must never reach innerHTML unsanitized")


def test_a_failed_request_says_something():
    """No swap happens on an error and the composer clears itself either way,
    so without a handler an expired token looks like nothing happening."""
    js = _script()
    assert "htmx:responseError" in js
    # Scoped to this panel's requests: the page has plenty of others.
    assert "/tasks/agents/chat" in js
    assert "401" in js and "403" in js


def test_the_invitation_goes_away_once_the_conversation_starts():
    """The page ships with it inside #agent-thread and messages append after
    it, so it would otherwise sit above the conversation for good."""
    js = _script()
    assert "aempty" in js
    assert 'class="aempty"' in _page(), "the invitation is still the page's"


def test_the_panel_styles_cover_the_classes_it_renders():
    """A streamed bubble lives inside .alive, which is not a flex child of
    .ap-thread, so without a rule it loses the gap a replayed bubble has."""
    css = _styles()
    for cls in (".aempty", ".astream", ".alive", ".awork", ".awaiting"):
        assert cls in css, cls
    assert "var(--panel)" not in css, "that token does not exist on this page"


# The divider between the conversation and the agents. A width somebody drags
# and loses on the next visit is worse than one they cannot change at all.

def test_the_page_itself_does_not_scroll():
    """Ralph, with a screenshot, 2026-09-18: "make it fit no need to scroll".
    The cards grew the page, so the window scrolled, the conversation scrolled
    inside it, and getting back to the composer meant scrolling the page down
    again. The page is a screen now: it fills the window, and the two columns
    scroll inside it.

    Only above the breakpoint. Stacked into one column, the page has to scroll
    or everything below the fold is unreachable."""
    page, css = _page(), _styles()
    assert "overflow: hidden" in page, "the page still scrolls as a document"
    assert "min-width: 1181px" in page, (
        "the shell must not apply where the columns stack")
    assert "overflow-y: auto" in css.split(".agents-main")[1][:200], (
        "the cards column has to carry its own overflow")
    # The declaration, not the word: the comment above the rule says what it
    # used to be, and a test that cannot tell prose from code would forbid
    # explaining the change.
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "100vh" not in rules, (
        "the panel is sized by its column now, not by the window")


def test_the_memory_row_is_still_there_on_an_agent_that_remembers_nothing():
    """A reversal, and worth keeping the reasoning.

    Every card carried "Memory: 0 notes" above a Show button, and that height
    is what pushed the seventh agent off screen, so the row was hidden
    whenever the count was zero. That deleted the only way into memory for an
    agent with nothing in it, and with it Show, Forget all and the "Nothing
    remembered yet" line. Five browser tests caught it, all of them reaching
    memory through that row.

    The height comes out of the styling instead, which costs nothing anybody
    can click."""
    assert "el.hidden = n === 0" not in _page(), (
        "hiding the row takes Show and Forget all with it")
    assert ".agents-main .card-memory" in _styles(), (
        "the row has to be compacted in the two column layout instead")


def test_the_columns_can_be_resized_and_the_width_is_remembered():
    page, js, css = _page(), _script(), _styles()
    assert 'id="ap-resize"' in page
    assert "--agents-width" in css, "the column width has to be a variable"
    assert "--agents-width" in js, "and the script has to write it"
    assert "localStorage" in js and "aiui-agents-width" in js


def test_the_divider_is_reachable_without_a_mouse():
    """A drag handle nobody can tab to is not a control."""
    page, js = _page(), _script()
    assert "<button" in page.split('id="ap-resize"')[0].rsplit("<", 1)[0] + "<button" \
        or 'class="ap-resize"' in page
    assert "ArrowLeft" in js and "ArrowRight" in js
    assert 'aria-label="Resize the agents column"' in page


def test_the_width_is_clamped_so_a_column_cannot_be_dragged_away():
    js = _script()
    assert "MIN_AGENTS" in js and "MAX_AGENTS" in js
    assert "Math.max" in js and "Math.min" in js


def _int_after(js, name):
    import re
    m = re.search(r"var %s = (\d+);" % name, js)
    assert m, name + " is not a plain number any more"
    return int(m.group(1))


def test_a_width_saved_above_the_ceiling_is_pulled_back():
    """Reported 2026-10-08 with a screenshot: the office and the conversation
    were squeezed because the roster had been dragged out wide in an earlier
    session and the width is remembered per browser.

    Nobody should have to clear their storage to get the room back. The
    restore puts the stored value through applyWidth, and applyWidth clamps,
    so lowering the ceiling is what rescues a column already wider than it.
    This pins that path: the restore must NOT set the width directly."""
    js = _script()
    restore = js.split("function restoreWidth()")[1].split("})()")[0]
    assert "applyWidth(" in restore, (
        "the saved width has to go through the clamp, or an old wide value "
        "survives for ever")
    assert "setProperty" not in restore, (
        "restoring by writing the variable straight out would skip the clamp")


def test_the_roster_leaves_the_room_to_the_office_and_the_chat():
    """The roster is reference; the office and the conversation are what the
    page is for. The numbers are a judgement rather than a law, so this pins
    only the direction: a default that is not most of the page, and a ceiling
    low enough that the chat column keeps the larger half on a normal
    screen."""
    js, css = _script(), _styles()
    assert _int_after(js, "MAX_AGENTS") <= 460, "the roster can still hog the page"
    assert _int_after(js, "MIN_AGENTS") >= 200, "too narrow to read a card in"
    import re
    m = re.search(r"var\(--agents-width, (\d+)px\)", css)
    assert m, "the default width is not in the variable any more"
    assert int(m.group(1)) <= 320, "the default leans the wrong way"


def test_escape_is_handled_in_one_place():
    """Two Escape handlers, each closing "its" dialog, close two layers on
    one press. agents.html has the page's one handler, which closes only the
    top-most layer; agent-chat.js has none."""
    assert '"Escape"' not in _script(), (
        "agent-chat.js still handles Escape itself")
    assert _page().count('"Escape"') == 1, "expected exactly one Escape check"
