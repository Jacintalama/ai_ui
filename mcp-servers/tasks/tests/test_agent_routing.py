"""Working out who the person is talking to.

The rule is ported from the channel gateway, which has run in Discord and
Telegram for weeks: a whole-word match on the agent's name anywhere in the
sentence, because people write "hi mia, are you there" rather than an
@mention.

The dangerous half is the false positive. An agent named Ada must not be
summoned by "adapt", or somebody discussing adapters gets an agent every time.
"""
import pytest

import agent_routing as ar

ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
AGENTS = [ADA, MIA]


@pytest.mark.parametrize("text,expected", [
    ("hi mia how can you help me", "Mia"),
    ("MIA, any news?", "Mia"),
    ("  ada: what is up", "Ada"),
    ("could you ask Ada about the invoice", "Ada"),
    ("gisingin mo si Mia", "Mia"),
    ("hey ada!", "Ada"),
])
def test_a_name_spoken_in_a_sentence_picks_that_agent(text, expected):
    assert ar.match_agent(text, AGENTS)["name"] == expected


@pytest.mark.parametrize("text", [
    "can you adapt this for me",
    "the adapter is broken",
    "miami is far away",
    "nomiadic patterns",
    "readapt the layout",
    "",
    "   ",
])
def test_a_name_inside_another_word_is_not_a_mention(text):
    """The whole reason boundaries are hand rolled. A false wake is worse than
    a missed one: it hijacks an unrelated conversation."""
    assert ar.match_agent(text, AGENTS) is None


def test_the_first_name_said_wins():
    """Two names in one sentence means the first is being addressed."""
    assert ar.match_agent("mia and ada are both here", AGENTS)["name"] == "Mia"
    assert ar.match_agent("ada and mia are both here", AGENTS)["name"] == "Ada"


def test_an_unknown_name_matches_nothing():
    assert ar.match_agent("hi scout", AGENTS) is None


@pytest.mark.parametrize("agents", [
    [], None, ["not a dict"], [{"id": "x"}], [{"name": ""}], [{"name": "   "}],
])
def test_a_malformed_agent_list_never_raises(agents):
    """This list comes from a model listing over HTTP, so the shape cannot be
    trusted. A crash here takes down every message in the chat."""
    assert ar.match_agent("hi mia", agents) is None


# --- sending the agent back to sleep --------------------------------------

@pytest.mark.parametrize("text", [
    "stop", "Stop", "  STOP  ", "stop using that", "never mind", "nevermind",
    "back to normal", "no agent",
])
def test_a_release_phrase_is_recognised(text):
    assert ar.wants_release(text) is True


@pytest.mark.parametrize("text", [
    "stop the server please",
    "can you stop it from failing",
    "never mind the details, keep going",
    "what should I stop doing",
    "",
])
def test_an_ordinary_sentence_does_not_release(text):
    """Matched on the WHOLE message. Somebody mid-conversation who writes
    "stop the server" must not lose the agent they are talking to."""
    assert ar.wants_release(text) is False


# --- reading the message ---------------------------------------------------

def test_the_last_user_message_is_what_gets_matched():
    msgs = [
        {"role": "user", "content": "hi ada"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "now hi mia"},
    ]
    assert ar.last_user_text(msgs) == "now hi mia"


@pytest.mark.parametrize("msgs", [
    [], None, [{"role": "assistant", "content": "x"}],
    [{"role": "user"}], [{"role": "user", "content": None}],
    [{"role": "user", "content": ["not", "a", "string"]}], ["not a dict"],
])
def test_reading_the_message_never_raises(msgs):
    assert ar.last_user_text(msgs) == ""


def test_no_dashes_in_the_release_vocabulary():
    for p in ar.RELEASE_PHRASES:
        assert "—" not in p and "–" not in p
