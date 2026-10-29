"""The main chat hears the whole message, however short, however attached.

Two findings from 2026-10-29, both in the path every single message takes,
and both measured rather than reasoned about.

ONE. A turn with a file attached arrives from Open WebUI as a LIST of parts
rather than a string, and `agent_routing.last_user_text` read "" from every
one of them. Proven before the fix:

    text from a message with an image: ''
    agents matched: []
    agents matched on plain text:     [Mia]

So attaching a screenshot and typing "mia, what is in this" reached nobody.
No name matched, Jev was never asked, no tool was picked. The person watched
their own agent ignore them while the free model answered instead.

TWO. `JEV_MIN_WORDS = 4` was meant to keep greetings away from Jev, and it
did, but it swallowed the shortest real requests with them: "check my inbox"
is three words, "any new email" is three, "read my emails" is three. All of
them skipped the tool pick and went to a model with no mailbox, which is the
one thing this chat is asked for most. A greeting is not distinguished from a
request by its length; it is distinguished by its words.
"""
import pytest

import agent_routing
import routes_agent_turn as rt

AGENTS = [{"id": "a1", "name": "Mia"}, {"id": "a2", "name": "Ada"}]


def _attached(text, kind="image_url"):
    """A user turn the way Open WebUI sends one with something attached."""
    parts = [{"type": kind, kind: {"url": "data:image/png;base64,iVBOR"}}]
    if text is not None:
        parts.insert(0, {"type": "text", "text": text})
    return [{"role": "user", "content": parts}]


# --- one: the words survive an attachment ------------------------------------

def test_the_words_are_read_from_a_turn_with_an_attachment():
    assert agent_routing.last_user_text(
        _attached("mia, what is in this screenshot?")
    ) == "mia, what is in this screenshot?"


def test_an_agent_named_alongside_an_attachment_is_reached():
    """The reported failure, end to end through the matcher."""
    text = agent_routing.last_user_text(_attached("mia, what is in this?"))
    assert [a["name"] for a in agent_routing.match_agents(text, AGENTS)] == ["Mia"]


def test_several_text_parts_are_joined_in_order():
    parts = [{"role": "user", "content": [
        {"type": "text", "text": "check this"},
        {"type": "image_url", "image_url": {"url": "data:x"}},
        {"type": "text", "text": "against my inbox"}]}]
    assert agent_routing.last_user_text(parts) == "check this against my inbox"


def test_an_attachment_with_no_words_is_still_empty():
    """Nothing typed is nothing to route on, and must not raise."""
    assert agent_routing.last_user_text(_attached(None)) == ""


def test_a_part_with_no_text_key_is_skipped_not_fatal():
    parts = [{"role": "user", "content": [
        {"type": "text"}, {"type": "text", "text": "find the invoice"}]}]
    assert agent_routing.last_user_text(parts) == "find the invoice"


def test_a_malformed_part_does_not_take_the_turn_down():
    parts = [{"role": "user", "content": ["bare string", None, 7,
                                          {"type": "text", "text": "ok go"}]}]
    assert agent_routing.last_user_text(parts) == "ok go"


def test_a_plain_string_turn_is_unchanged():
    """The common case must not regress: no attachment, no list, no joining."""
    assert agent_routing.last_user_text(
        [{"role": "user", "content": "hello there"}]) == "hello there"


def test_the_latest_user_turn_still_wins_over_an_earlier_one():
    msgs = [{"role": "user", "content": "the old question"},
            {"role": "assistant", "content": "an answer"}]
    msgs += _attached("the new question")
    assert agent_routing.last_user_text(msgs) == "the new question"


def test_the_reflection_reads_an_attached_turn_too():
    """routes_agent_turn had its own copy of this blind spot, so an agent
    reflected on nothing for every message with a file on it."""
    assert rt._last_user_text(
        _attached("remember that the invoice is paid")
    ) == "remember that the invoice is paid"


# --- two: a short request is still a request ---------------------------------

@pytest.mark.parametrize("said", [
    "check my inbox",
    "any new email",
    "read my emails",
    "what is on my calendar",
    "find the invoice",
    "my unread mail",
    "book it",
])
def test_a_short_request_still_reaches_jev(said):
    """Every one of these is under the old four-word floor. Each is a request
    for something only a tool can see."""
    assert not rt.is_small_talk(said), said


@pytest.mark.parametrize("said", [
    "hi",
    "hey",
    "hello there",
    "good morning",
    "good morning everyone",
    "thanks",
    "thanks mate",
    "thank you",
    "ok cool",
    "perfect, thanks!",
    "yes",
    "no",
    "bye",
])
def test_a_greeting_is_still_not_jev_s_business(said):
    """What the word count was for. It keeps doing that job, by the words."""
    assert rt.is_small_talk(said), said


def test_one_word_that_means_something_makes_it_a_request():
    """The line between the two lists: a pleasantry with a request attached is
    a request. "thanks" alone is not."""
    assert rt.is_small_talk("thanks")
    assert not rt.is_small_talk("thanks, check my inbox")


def test_an_empty_message_is_not_treated_as_small_talk():
    """Empty is not a greeting, it is nothing. The callers above it already
    handle nothing; claiming it is small talk would hide that."""
    assert not rt.is_small_talk("")
    assert not rt.is_small_talk("   ")
    assert not rt.is_small_talk(None)


def test_punctuation_and_case_do_not_smuggle_a_greeting_past():
    assert rt.is_small_talk("HI!!")
    assert rt.is_small_talk("Thanks :)")
    assert rt.is_small_talk("...hey")


def test_the_word_count_gate_is_gone():
    """Named so that reintroducing a length gate is a visible failure rather
    than a quiet return to sending three-word requests to a bare model."""
    assert not hasattr(rt, "JEV_MIN_WORDS"), (
        "a length gate is back; the words decide, not the count")
