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
        render.approval_bubble("Ada", "9f2c1ab34de54f0b", CALLS),
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
    html = render.approval_bubble("Ada", "q-1", CALLS)
    assert "send_email" in html
    assert "boss@example.com" in html
    assert ">Yes<" in html and ">No<" in html
    assert 'hx-post="/tasks/agents/chat/approve"' in html


def test_approval_never_leaks_the_held_conversation():
    # _pending_payload carries these two next to the calls. Neither may reach
    # a browser, so the renderer is only ever handed the calls.
    html = render.approval_bubble("Ada", "q-1", CALLS)
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


def test_an_approval_is_addressed_by_its_question_not_by_its_agent():
    """Two questions from one agent must be two elements the page can tell
    apart, or htmx sends the second one's Yes at the first one's bubble."""
    first = render.approval_bubble("Ada", "q-1", CALLS)
    second = render.approval_bubble("Ada", "q-2", CALLS)
    assert 'id="await-q-1"' in first
    assert 'id="await-q-2"' in second
    assert '"ask_id": "q-1"' in first
    assert 'hx-target="#await-q-1"' in first
    assert "q-2" not in first


def test_a_replayed_approval_keeps_the_question_it_belongs_to():
    html = render.thread([
        {"role": "assistant", "agent_id": "agent-a", "agent_name": "Ada",
         "content": "May I?", "awaiting": {"ask_id": "q-7", "calls": CALLS}},
    ])
    assert 'id="await-q-7"' in html
    assert '"ask_id": "q-7"' in html


def test_a_note_the_round_stored_is_drawn_on_the_way_back():
    """Persisted deliberately by _run_round. Dropping it here meant a skipped
    agent was explained live and unexplained on reload."""
    html = render.thread([
        {"role": "user", "content": "hi"},
        {"role": "note", "content": "An agent that was in this room no "
                                    "longer exists, so it was skipped."},
        {"role": "assistant", "agent_name": "Mia", "content": "Mia here"},
    ])
    assert "no longer exists" in html
    assert 'class="am note"' in html


def test_round_bookkeeping_still_draws_as_nothing():
    html = render.thread([{"role": "round", "content": ""}])
    # Nothing to show, so the empty state is what a person gets.
    assert "Pick who is in the room" in html
