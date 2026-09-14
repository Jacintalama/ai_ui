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
        render.turn_open("hi team", "abc123def456"),
        render.turn_close(),
        render.into_turn("abc123def456", render.agent_bubble("Ada", "hi")),
        render.turn_status("abc123def456", render.working("Ada")),
        render.agent_bubble("Ada", "hello"),
        render.approval_bubble("Ada", "9f2c1ab34de54f0b", CALLS),
        render.working("Ada"),
        render.note("something happened"),
        render.stream_block(),
        render.empty_thread(),
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


def test_agent_answer_is_escaped():
    assert "<img" not in render.agent_bubble("Ada", '<img onerror=x>')


def test_a_turn_carries_the_message_and_a_place_for_answers():
    from agent_chat_render import turn_open
    html = turn_open("what is in my inbox?", "abc123def456")
    assert "what is in my inbox?" in html
    assert "aturn-body" in html
    assert "aturn-status" in html


def test_a_turn_escapes_what_the_person_typed():
    from agent_chat_render import turn_open
    html = turn_open('<img src=x onerror="alert(1)">', "abc123def456")
    assert "<img" not in html
    assert "&lt;img" in html


def test_a_turn_carries_its_own_id():
    """Two other turns can be on screen at once (a queued message opens its
    own while an earlier one is still running), so the id is what tells a
    streamed answer which one it belongs to. Different ids must render
    different elements, not collide on a shared class."""
    from agent_chat_render import turn_open
    first = turn_open("one", "aaa111")
    second = turn_open("two", "bbb222")
    assert 'id="aturn-aaa111"' in first
    assert 'id="aturn-bbb222"' in second
    assert "bbb222" not in first


def test_the_turn_target_functions_agree_with_what_turn_open_renders():
    """turn_body_target/turn_status_target build a selector from an id, and
    turn_open has to stamp that exact id onto the element it creates, or the
    two drift apart with nothing to notice until an answer has nowhere to
    go. This only checks the two agree on the id; whether the resulting
    selector actually resolves against a real, rendered page is checked for
    real in tests/browser/test_agent_chat_turn_targets.py, since a selector
    that looks right as a string can still match nothing once the turn sits
    next to a sibling it did not have before (see that file's docstring for
    the bug this was written to catch)."""
    from agent_chat_render import turn_body_target, turn_open, turn_status_target
    tid = "abc123def456"
    html = turn_open("x", tid)
    assert f'id="aturn-{tid}"' in html
    assert turn_body_target(tid) == f"#aturn-{tid} .aturn-body"
    assert turn_status_target(tid) == f"#aturn-{tid} .aturn-status"


def test_into_turn_and_turn_status_wrap_a_fragment_out_of_band_for_its_id():
    from agent_chat_render import into_turn, turn_status
    tid = "abc123def456"
    body = into_turn(tid, "<div>hi</div>")
    assert 'hx-swap-oob="beforeend:#aturn-abc123def456 .aturn-body"' in body
    assert "<div>hi</div>" in body
    status = turn_status(tid, "Ada is working...")
    assert 'hx-swap-oob="innerHTML:#aturn-abc123def456 .aturn-status"' in status
    assert "Ada is working..." in status


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
    assert "Every agent hears it" in html


def test_a_replayed_conversation_groups_answers_into_turns():
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "one"},
        {"role": "assistant", "agent_name": "Mia", "content": "first"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "agent_name": "Ada", "content": "second"},
    ])
    assert html.count('class="aturn"') == 2
    assert html.count("</div>") >= 2
    assert html.index("first") < html.index("two"), "an answer escaped its turn"


def test_a_replay_with_no_messages_falls_back_to_the_empty_state():
    """/tasks/agents/chat/thread renders this on every page load, including a
    brand new conversation and one just cleared, and those already show the
    empty state today (see test_round_bookkeeping_still_draws_as_nothing
    above, which covers the same case with no visible content for a
    different reason). Turning this into "" would blank that placeholder out
    from under every first-time visitor and everyone who just hit Clear."""
    from agent_chat_render import empty_thread, thread
    assert thread([]) == empty_thread()
    assert thread(None) == empty_thread()


# The panel's avatars are ported from the agent cards so a person recognises
# the same mark in both places. If these drift, Ada is green on her card and
# some other colour two inches to the right in the panel.

def test_the_avatar_letters_match_the_cards():
    assert render._initials("Ada") == "AD"
    assert render._initials("Mia") == "MI"
    assert render._initials("Research Bot") == "RB"
    assert render._initials("") == "AI"
    assert render._initials(None) == "AI"


def test_the_avatar_hue_matches_the_pages_algorithm():
    """Recomputed here the way static/agents.html does it, rather than
    hardcoding an answer, so this fails if either side changes."""
    def js_avatar_hue(name):
        h = 0
        for ch in name:
            h = (h * 31 + ord(ch)) % 360
        return h

    for name in ("Ada", "Mia", "Scout", "Triage", ""):
        assert render._hue(name) == js_avatar_hue(name), name


def test_an_agent_bubble_carries_its_own_colour_and_letters():
    html = render.agent_bubble("Ada", "hello")
    assert "linear-gradient" in html
    assert f"hsl({render._hue('Ada')} 58% 46%)" in html
    assert ">AD<" in html
    assert "\n" not in html


def test_an_approval_bubble_carries_the_same_mark():
    html = render.approval_bubble("Mia", "ask-1", CALLS)
    assert "linear-gradient" in html
    assert ">MI<" in html
    assert "\n" not in html


# --- a failure is drawn as a failure, not a bubble --------------------------
#
# These used to arrive as prose in the thread, in the same shape as an
# answer, and a failure that looks like an answer is one people re-read as an
# answer.

def test_a_failure_is_not_a_bubble():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.")
    assert "afail" in html
    assert 'class="am agent"' not in html, "it renders as an answer"
    assert "Ada" in html
    assert "The free models are all busy." in html


def test_a_failure_can_carry_the_fix():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.",
                   "Ada is set to Auto (Free). Pick a specific model.")
    assert "Pick a specific model." in html


def test_a_failure_without_a_fix_shows_no_fix_line():
    """The fix line is real markup (afail-fix), not just an empty string
    inside afail-what. Something has to fail if the fragment always emitted
    the wrapper, fix text or not."""
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.")
    assert "afail-fix" not in html


def test_a_failure_escapes_everything():
    from agent_chat_render import failure
    html = failure("<b>x</b>", "<i>y</i>", "<u>z</u>")
    for tag in ("<b>", "<i>", "<u>"):
        assert tag not in html


def test_a_stored_failure_replays_with_its_own_reason_and_fix():
    """Step 8's replay must show what was actually on screen live, not
    rewrite a specific failure into the generic one. See routes_agent_chat's
    ROUTER_EXHAUSTED branch, which is what stores a reason and a fix."""
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "hi"},
        {"role": "failure", "agent_name": "Ada",
         "content": "the router gave up",
         "reason": "The free models are all busy right now.",
         "fix": "This agent is set to Auto (Free). Choosing a specific "
                "model on its card fixes this."},
    ])
    assert "afail" in html
    assert 'class="am agent"' not in html, "it replayed as an answer"
    assert "The free models are all busy right now." in html
    assert "Choosing a specific model on its card fixes this." in html


def test_a_stored_failure_without_a_reason_falls_back_to_the_generic_one():
    """Older conversations were saved before reason/fix existed. A missing
    key here must not blank the failure out or raise on reload."""
    from agent_chat_render import GENERIC_FAILURE_REASON, thread
    html = thread([
        {"role": "user", "content": "hi"},
        {"role": "failure", "agent_name": "Ada", "content": "whatever"},
    ])
    assert "afail" in html
    assert GENERIC_FAILURE_REASON in html
