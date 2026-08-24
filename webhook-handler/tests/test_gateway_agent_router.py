"""Which agent answers, and the guard rails around that choice.

The router is a model reading a short message, so it can be wrong and it can
invent an id. Everything it returns is checked against the caller's own
candidates before it becomes a model id, because an id it made up must never be
able to route a real request.
"""
from unittest.mock import AsyncMock

import pytest

from gateway import agent_router


def _model(mid, name, desc="", base="gpt-4o-mini"):
    return {"id": mid, "name": name, "base_model_id": base,
            "meta": {"description": desc, "toolIds": []}}


MODELS = [
    _model("gpt-4o-mini", "gpt-4o-mini", base=None),
    _model("agent-inbox-triage-0002", "Inbox Triage",
           "You read the user's unread email and say what needs them."),
    _model("agent-research-assistant-0001", "Research Assistant",
           "You research questions and answer with what you found."),
]
CANDS = agent_router.candidates(MODELS)


@pytest.mark.parametrize("bad", [None, "", 0, {"items": []}, object()])
def test_a_non_list_yields_no_candidates(bad):
    """The models endpoint can return something that is not a list, and a stub
    certainly can. Raising here would surface as an unexplained failure two
    layers up."""
    assert agent_router.candidates(bad) == []


def test_only_agents_are_candidates():
    """A base model is not an agent, and neither is a preset the user made in
    Open WebUI's own workspace."""
    ids = [c["id"] for c in CANDS]
    assert ids == ["agent-inbox-triage-0002", "agent-research-assistant-0001"]


def test_a_candidate_carries_its_name_and_one_line():
    c = CANDS[0]
    assert c["name"] == "Inbox Triage"
    assert "unread email" in c["description"]


@pytest.mark.parametrize("bad_item", [
    None,
    "oops",
    {"id": 123, "name": "X", "meta": {}},
])
def test_an_unusable_item_is_skipped_not_raised(bad_item):
    """Not a dict, or an id that is not a string: there is nothing to fall
    back to, so the row is dropped rather than raising."""
    assert agent_router.candidates([bad_item]) == []


@pytest.mark.parametrize("bad_item", [
    {"id": "agent-x", "meta": "not-a-dict"},
    {"id": "agent-x", "name": 55, "meta": {}},
])
def test_a_malformed_field_falls_back_instead_of_raising(bad_item):
    """A bad meta or name is not fatal to the row: meta falls back to {} and
    name falls back to the id, same as the finding specified."""
    got = agent_router.candidates([bad_item])
    assert got == [{"id": "agent-x", "name": "agent-x", "description": ""}]


def test_a_malformed_item_does_not_cost_the_good_ones_in_the_same_list():
    good = _model("agent-inbox-triage-0002", "Inbox Triage", "reads mail")
    mixed = [None, "oops", {"id": "agent-x", "meta": "not-a-dict"},
             {"id": 123, "name": "X", "meta": {}},
             {"id": "agent-x", "name": 55, "meta": {}}, good]
    got = agent_router.candidates(mixed)
    ids = [c["id"] for c in got]
    assert "agent-inbox-triage-0002" in ids
    assert got[-1]["name"] == "Inbox Triage"


def test_the_prompt_never_carries_full_instructions():
    """Instructions run to 4000 characters and this call happens on every
    message, so the prompt is names and one-liners on purpose."""
    long_agent = _model("agent-long-0003", "Long", "x" * 400)
    cands = agent_router.candidates([long_agent])
    text = "".join(m["content"] for m in agent_router.build_messages("hi", cands))
    assert len(text) < 1200
    assert "agent-long-0003" in text


def test_a_valid_answer_is_accepted():
    got = agent_router.validate("agent-inbox-triage-0002", CANDS)
    assert got["id"] == "agent-inbox-triage-0002"


@pytest.mark.parametrize("answer", [
    "agent-not-mine-9999",          # an id it invented
    "agent-inbox-triage-0002-x",    # close but not real
    "NONE",
    "",
    None,
    "I think you want Inbox Triage",
])
def test_anything_not_in_the_candidates_is_refused(answer):
    assert agent_router.validate(answer, CANDS) is None


def test_a_quoted_or_padded_id_is_still_accepted():
    """Models like to wrap an answer in quotes or a newline."""
    got = agent_router.validate('  "agent-inbox-triage-0002"  \n', CANDS)
    assert got["id"] == "agent-inbox-triage-0002"


@pytest.mark.parametrize("answer", [
    {"id": "agent-inbox-triage-0002"},
    ["agent-inbox-triage-0002"],
    123,
])
def test_a_non_string_answer_is_refused_not_raised(answer):
    """validate() is the boundary between an untrusted answer and a candidate
    dict. A caller other than pick() may hand it something that is not a
    string, and that must be refused the same way a wrong id is."""
    assert agent_router.validate(answer, CANDS) is None


def test_only_the_first_non_blank_line_is_ever_checked():
    """Deliberate and fail-safe, not an oversight: a valid id on a later line
    is missed rather than found by scanning past text the router was told not
    to write."""
    answer = "Sure, I would pick this one:\nagent-inbox-triage-0002"
    assert agent_router.validate(answer, CANDS) is None


async def test_pick_returns_the_chosen_candidate():
    owui = AsyncMock()
    owui.chat_completion.return_value = "agent-inbox-triage-0002"

    got = await agent_router.pick(owui, "check my mail", CANDS, "gpt-4o-mini")

    assert got["name"] == "Inbox Triage"


async def test_no_candidates_means_no_model_call():
    """This is the cost guard. The router would otherwise run on every message
    from every user, including users who have no agents."""
    owui = AsyncMock()

    got = await agent_router.pick(owui, "hello", [], "gpt-4o-mini")

    assert got is None
    owui.chat_completion.assert_not_called()


async def test_a_router_failure_is_not_an_error():
    """The person is waiting. A router that cannot answer must not stop them
    getting a reply."""
    owui = AsyncMock()
    owui.chat_completion.side_effect = RuntimeError("router down")

    got = await agent_router.pick(owui, "check my mail", CANDS, "gpt-4o-mini")

    assert got is None


@pytest.mark.parametrize("bad_answer", [
    {"id": "agent-inbox-triage-0002"},
    ["agent-inbox-triage-0002"],
])
async def test_a_non_string_completion_is_not_an_error(bad_answer):
    """pick() promises never to raise. chat_completion is typed to return a
    string, but that typing is not enforced at the boundary, so a caller that
    hands back a dict or a list must fall back to no agent, not raise."""
    owui = AsyncMock()
    owui.chat_completion.return_value = bad_answer

    got = await agent_router.pick(owui, "check my mail", CANDS, "gpt-4o-mini")

    assert got is None


@pytest.mark.parametrize("text,expected", [
    ("use Inbox Triage", "agent-inbox-triage-0002"),
    ("Use inbox triage", "agent-inbox-triage-0002"),
    ("switch to Research Assistant", "agent-research-assistant-0001"),
    ("talk to Inbox Triage.", "agent-inbox-triage-0002"),
])
def test_a_pin_phrase_naming_a_real_agent_pins_it(text, expected):
    got = agent_router.match_pin_request(text, CANDS)
    assert got["id"] == expected


@pytest.mark.parametrize("text", [
    "use my email to find the invoice",
    "use the research I sent you",
    "switch to a different tone",
    "can you use Inbox Triage",
    "Inbox Triage",
    "",
])
def test_an_ordinary_message_is_not_a_pin(text):
    """A message silently turning into a setting is worse than a router that
    picks wrong, so the match is deliberately narrow: the rest of the message
    must BE the agent's name."""
    assert agent_router.match_pin_request(text, CANDS) is None


@pytest.mark.parametrize("text,expected", [
    ("stop using that", True),
    ("Stop using it.", True),
    ("back to normal", True),
    ("stop using my email", False),
    ("hello", False),
])
def test_unpin_detection(text, expected):
    assert agent_router.is_unpin_request(text) is expected


def test_the_pin_key_is_per_conversation():
    a = agent_router.pin_key("telegram", "42")
    b = agent_router.pin_key("telegram", "43")
    c = agent_router.pin_key("discord", "42")
    assert a != b and a != c
