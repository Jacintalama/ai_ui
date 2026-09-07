"""The panel's markup.

Two rules here are load-bearing rather than cosmetic. Every fragment is one
line, because some of them travel as SSE data where a newline is a field
separator. And an approval bubble shows the tool call only: the held
conversation and the owner's email stay on the server.
"""
import agent_chat_render as render

CALLS = [{"function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]


def _fragments():
    return [
        render.user_bubble("hi team"),
        render.agent_bubble("Ada", "hello"),
        render.approval_bubble("Ada", "agent-research-assistant-0001", CALLS),
        render.working("Ada"),
        render.note("something happened"),
        render.stream_block(),
        render.empty_thread(),
        render.chips([{"id": "agent-a", "name": "Ada"}], ["agent-a"]),
        render.chat_list([{"id": "c1", "title": "About the invoices"}], "c1"),
        render.thread([{"role": "user", "content": "hi"},
                       {"role": "assistant", "agent_name": "Ada",
                        "content": "hello"}]),
    ]


def test_no_fragment_contains_a_newline():
    for fragment in _fragments():
        assert "\n" not in fragment, fragment
        assert "\r" not in fragment, fragment


def test_every_agent_answer_is_its_own_row():
    html = render.thread([
        {"role": "user", "content": "hi team"},
        {"role": "assistant", "agent_name": "Ada", "content": "Ada here"},
        {"role": "assistant", "agent_name": "Mia", "content": "Mia here"},
    ])
    assert html.count('class="am agent"') == 2
    assert "Ada here" in html and "Mia here" in html


def test_user_text_is_escaped():
    assert "<script>" not in render.user_bubble("<script>alert(1)</script>")
    assert "&lt;script&gt;" in render.user_bubble("<script>alert(1)</script>")


def test_agent_answer_is_escaped():
    assert "<img" not in render.agent_bubble("Ada", '<img onerror=x>')


def test_approval_shows_the_call_and_offers_both_answers():
    html = render.approval_bubble("Ada", "agent-a", CALLS)
    assert "send_email" in html
    assert "boss@example.com" in html
    assert ">Yes<" in html and ">No<" in html
    assert 'hx-post="/tasks/agents/chat/approve"' in html


def test_approval_never_leaks_the_held_conversation():
    # _pending_payload carries these two next to the calls. Neither may reach
    # a browser, so the renderer is only ever handed the calls.
    html = render.approval_bubble("Ada", "agent-a", CALLS)
    assert "conversation" not in html
    assert "user_email" not in html


def test_stream_block_closes_the_connection_and_has_both_targets():
    html = render.stream_block()
    assert 'sse-connect="/tasks/agents/chat/stream"' in html
    assert 'sse-close="close"' in html
    assert 'sse-swap="message"' in html
    assert 'sse-swap="working"' in html


def test_chips_mark_who_is_in_the_room():
    html = render.chips([{"id": "agent-a", "name": "Ada"},
                         {"id": "agent-m", "name": "Mia"}], ["agent-a"])
    assert html.count("chip") >= 2
    assert "chip in" in html
