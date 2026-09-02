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


# --- naming more than one agent --------------------------------------------

def test_two_names_return_both_in_spoken_order_not_list_order():
    """The list order must not leak through, so each case here is given the
    OPPOSITE of the order the names are spoken in: "hi mia and ada" speaks
    Mia first but is given a list with Ada first, and vice versa. A
    match_agents that merely echoed the input list order would get both of
    these backwards."""
    ada_first = [ADA, MIA]
    names = [a["name"] for a in ar.match_agents("hi mia and ada", ada_first)]
    assert names == ["Mia", "Ada"]

    mia_first = [MIA, ADA]
    names = [a["name"] for a in ar.match_agents("hi ada and mia", mia_first)]
    assert names == ["Ada", "Mia"]


def test_the_same_name_twice_returns_one_entry():
    names = [a["name"] for a in ar.match_agents("mia, are you there mia?", AGENTS)]
    assert names == ["Mia"]


def test_one_name_returns_one_entry():
    names = [a["name"] for a in ar.match_agents("hi mia how can you help me", AGENTS)]
    assert names == ["Mia"]


def test_no_name_returns_empty():
    assert ar.match_agents("what is the weather", AGENTS) == []


@pytest.mark.parametrize("text", [
    "can you adapt this for me",
    "the adapter is broken",
    "miami is far away",
    "nomiadic patterns",
    "readapt the layout",
    "",
    "   ",
])
def test_match_agents_rejects_the_same_false_positives_as_match_agent(text):
    """The false-positive guard must hold for match_agents too, not just the
    single-agent wrapper."""
    assert ar.match_agents(text, AGENTS) == []


@pytest.mark.parametrize("agents", [
    [], None, ["not a dict"], [{"id": "x"}], [{"name": ""}], [{"name": "   "}],
])
def test_match_agents_with_a_malformed_agent_list_never_raises(agents):
    assert ar.match_agents("hi mia", agents) == []


@pytest.mark.parametrize("text,agents", [
    (123, AGENTS),
    (None, AGENTS),
    ("hi mia", 123),
    ("hi mia", "not a list"),
])
def test_match_agents_with_wrong_types_never_raises(text, agents):
    assert ar.match_agents(text, agents) == []


@pytest.mark.parametrize("agents", [
    [], None, ["not a dict"], [{"id": "x"}], [{"name": ""}], [{"name": "   "}],
])
def test_a_malformed_agent_list_never_raises(agents):
    """This list comes from a model listing over HTTP, so the shape cannot be
    trusted. A crash here takes down every message in the chat."""
    assert ar.match_agent("hi mia", agents) is None


@pytest.mark.parametrize("text,agents", [
    (123, AGENTS),
    (None, AGENTS),
    ("hi mia", 123),
    ("hi mia", "not a list"),
])
def test_match_agent_with_wrong_types_never_raises(text, agents):
    """Type guard for text and agents parameters. A non-string or non-list
    must not crash the routing logic."""
    assert ar.match_agent(text, agents) is None


# --- waking every agent at once ---------------------------------------------

@pytest.mark.parametrize("word", ["team", "everyone", "all of you", "guys"])
def test_each_collective_word_wakes_every_agent_in_list_order(word):
    """"in the order the agents were given", not spoken order: there is no
    single position for "everyone" to be sorted by."""
    names = [a["name"] for a in ar.match_agents("hi %s, quick update" % word, AGENTS)]
    assert names == ["Ada", "Mia"]

    reversed_list = [MIA, ADA]
    names = [a["name"] for a in ar.match_agents("hi %s" % word, reversed_list)]
    assert names == ["Mia", "Ada"]


def test_a_collective_word_combined_with_a_name_still_returns_everyone_once():
    names = [a["name"] for a in ar.match_agents("hi team, ada first", AGENTS)]
    assert names == ["Ada", "Mia"]
    assert len(names) == len(set(names)), "no agent may appear twice"


def test_match_agent_with_a_collective_word_returns_the_first_agent_given():
    assert ar.match_agent("hi team", AGENTS)["name"] == "Ada"


@pytest.mark.parametrize("agents", [[], None])
def test_a_collective_word_with_no_agents_returns_empty_not_an_error(agents):
    assert ar.match_agents("hi team", agents) == []
    assert ar.match_agent("hi everyone", agents) is None


@pytest.mark.parametrize("text", [
    "that was some real teamwork today",
    "let off some steam",
    "guyshire is a town nobody has heard of",
    "the esteamed guest arrived",
])
def test_a_collective_word_inside_another_word_is_not_a_match(text):
    """The same false-positive guard names already get, proven for the
    collective words too: "team" must not fire inside "teamwork" or "steam",
    and "guys" must not fire inside "guyshire"."""
    assert ar.match_agents(text, AGENTS) == []


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


@pytest.mark.parametrize("msgs", [
    123,
    "not a list",
])
def test_last_user_text_with_wrong_type_never_raises(msgs):
    """Type guard for messages parameter. A non-list must not crash."""
    assert ar.last_user_text(msgs) == ""


def test_no_dashes_in_the_release_vocabulary():
    for p in ar.RELEASE_PHRASES:
        assert "\u2014" not in p and "\u2013" not in p
