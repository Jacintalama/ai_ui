"""The panel is actually on the page.

A route nobody reaches is not a feature. This checks the page carries the
panel, its scripts, and the elements the fragments target, because the last
attempt shipped with the server side correct and the screen wrong.
"""
import pathlib

PAGE = pathlib.Path(__file__).resolve().parents[1] / "static" / "agents.html"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


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
    for target in ('id="agent-panel"', 'id="agent-room"', 'id="agent-thread"',
                   'id="agent-chatlist"'):
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
