"""The panel is actually on the page.

A route nobody reaches is not a feature. This checks the page carries the
panel, its scripts, and the elements the fragments target, because the last
attempt shipped with the server side correct and the screen wrong.
"""
import pathlib

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
    for cls in (".aempty", ".astream", ".alive", ".awork", ".awaiting",
                ".achatlist"):
        assert cls in css, cls
    assert "var(--panel)" not in css, "that token does not exist on this page"
