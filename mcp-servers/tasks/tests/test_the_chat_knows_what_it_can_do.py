"""Asked what it can do, the chat answered from the free model's idea of
itself, which is a general model that has never heard of this platform.

Found live 2026-11-11, minutes after Airtable one-click went in. Ralph
asked "can you access airtable?" and was told:

    "I don't have Airtable access in this chat, so I can't read from or
     write to your Airtable bases directly right now."

False, and everything underneath it was working at that moment: the
credential was stored, a real call returned his account and his base, and
his exact words ranked my-airtable_list_tables top of everything he can
reach. Two screenshots in the same session show what actually happened:

    "create me a space in clickup named IO team"
        -> "Used your account and the web"           TOOLS RAN
    "can you access airtable?"
        -> "Auto-routed to the free general model"   NO TOOLS RAN

Jev is working. It picks tools for a TASK and picks none for a CAPABILITY
QUESTION, which is right on its own terms: there is nothing to fetch in
order to answer "can you". But with no tool in hand the free model
answers out of its own head.

WHY IT MATTERS MORE THAN IT LOOKS. "Can you do X" is the first thing
anybody asks after connecting an app, so the platform's answer at the
exact moment somebody is checking whether their connection worked is a
confident, wrong no. It teaches people the feature does not exist.

THE ANSWER IS A LOOKUP, NOT A GUESS. Which apps this person has connected
is a row in a table, and what IO can do with each is already written down
per app, tool by tool, in app_triage.APPS. So the facts go in front of
the model and the model only does the wording.

NARROW ON PURPOSE. "An ordinary question goes straight to the free model"
(CLAUDE.md) is a rule worth keeping: the assistant turn is the slow path.
So this fires only for a question about what IO can do that names an app
this platform knows, or for "what can you do" itself. "Can you explain
how DNS works" is not that question.
"""
import asyncio

import pytest

import app_triage
import can_do
import routes_agent_turn as rt


# --- is this a question about what IO can do ------------------------------

def test_the_question_that_started_it():
    assert can_do.question("can you access airtable?") == ["airtable"]


def test_the_shapes_people_actually_use():
    for said in ("can you access airtable",
                 "can u access airtable",
                 "are you able to read my airtable",
                 "do you have access to airtable?",
                 "are you connected to airtable",
                 "is it possible for you to use airtable",
                 "do you have airtable access",
                 "CAN YOU ACCESS AIRTABLE"):
        assert can_do.question(said) == ["airtable"], said


def test_it_is_found_in_the_middle_of_a_sentence():
    assert can_do.question(
        "hey quick question, can you access airtable") == ["airtable"]


def test_an_app_named_the_way_an_answer_names_it():
    """`says` is the catalogue's own list of other words for an app, so
    "my drive" is Google Drive without a second list to keep in step."""
    assert can_do.question("can you read my drive") == ["gdrive"]
    assert can_do.question("can you see my calendar") == ["calendar"]


def test_two_apps_in_one_question_in_the_order_they_were_said():
    assert can_do.question("can you access clickup and airtable?") == [
        "clickup", "airtable"]


def test_what_can_you_do_is_the_general_form():
    """Nothing named, so the answer is everything they have connected."""
    assert can_do.question("what can you do?") == []
    assert can_do.question("what are you able to do") == []


def test_an_ordinary_question_is_left_alone():
    """The rule being kept: an ordinary question goes straight to the free
    model, at once, with no brief and no tool loop in front of it."""
    for said in ("can you explain how DNS works?",
                 "can you believe it",
                 "summarise this",
                 "write me a poem about trello cards",
                 ""):
        assert can_do.question(said) is None, said


def test_naming_an_app_in_a_task_is_not_asking_whether_it_can():
    """A task phrasing is the tool pick's, and it works today."""
    assert can_do.question(
        "create a table in airtable for name, status and role") is None


def test_a_question_that_is_also_a_task_is_both():
    """Ralph, 2026-11-12: "can you check airtable and create a a table in
    it for aiui team name, status, role". The tools still get picked; the
    facts ride along so the first half is answered truthfully."""
    assert can_do.question(
        "can you check airtable and create a a table in it") == ["airtable"]


def test_a_word_inside_another_word_is_not_the_app():
    assert can_do.question("can you tell me about driven development") is None


# --- what the model is told -----------------------------------------------

def _facts(ids, connected):
    return can_do.brief(can_do.plan(ids, connected))


def test_it_says_whether_the_app_is_connected():
    assert "Airtable (connected)" in _facts(["airtable"], {"airtable"})
    assert "Airtable (not connected)" in _facts(["airtable"], set())


def test_it_says_what_io_can_do_with_it():
    said = _facts(["airtable"], {"airtable"})
    assert app_triage.APPS["airtable"].can in said


def test_it_says_what_io_cannot_do_with_it():
    """Both halves or neither. An answer that only knows the yes side
    promises the delete this platform has no tool for."""
    said = _facts(["airtable"], {"airtable"})
    assert app_triage.APPS["airtable"].cannot in said


def test_the_instruction_forbids_the_answer_that_started_this():
    said = _facts(["airtable"], {"airtable"})
    assert "never say io cannot" in said.lower(), said


def test_the_instruction_forbids_promising_to_go_and_look():
    """Measured live 2026-11-12, the first real turn after this shipped:
    "Yes, Airtable is connected. Let me check what I can see in your
    account." It never does, because a capability question picks no tool,
    so that sentence is a promise the turn cannot keep. The list IS the
    answer."""
    said = _facts(["airtable"], {"airtable"}).lower()
    assert "do not say you are about to go and check" in said


def test_the_general_question_is_answered_with_what_they_have():
    said = _facts([], {"airtable", "trello"})
    assert "Airtable (connected)" in said
    assert "Trello (connected)" in said
    assert "GitHub (" not in said, (
        "an app nobody connected is not one of IO's abilities")


def test_the_general_question_says_what_else_could_be_connected():
    """"What can you do" with one app connected is not "one app". The
    rest of the catalogue is a sentence away from being true."""
    said = _facts([], {"airtable"})
    assert "Connections" in said
    assert "GitHub" in said


def test_nothing_known_is_no_block_at_all():
    """A question about an app this platform does not have must not put an
    empty instruction in front of the model."""
    assert can_do.brief(can_do.plan(["nonesuch"], set())) == ""


def test_with_nothing_connected_the_general_question_still_has_an_answer():
    """The person most likely to ask "what can you do" is the one who has
    connected nothing, and "nothing" is the wrong answer: every app in the
    catalogue is one button away."""
    said = can_do.brief(can_do.plan([], set()))
    assert "Connections" in said
    assert "Airtable" in said


# --- the wiring -----------------------------------------------------------

class _Body:
    def __init__(self, text):
        self.user_email = "ralph@example.com"
        self.messages = [{"role": "user", "content": text}]
        self.model = "auto"
        self.conversation_id = "c1"


def _wire(monkeypatch, answer="Yes, Airtable is connected.", connected=()):
    seen = {}

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        seen["graph"], seen["tool_ids"] = graph, tool_ids
        return {"agent": agent, "answer": answer, "notes": []}

    async def graph_block(_email, _text):
        return "GRAPH"

    async def providers(_email, strict=False):
        return list(connected)

    import routes_agents
    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(routes_agents, "_connected_providers", providers)
    return seen


ASKED = "can you access airtable?"


def test_the_assistant_answers_a_capability_question_with_no_tool(monkeypatch):
    """The bug. Today this returns None and the free model answers from
    its own idea of itself."""
    seen = _wire(monkeypatch, connected=("airtable",))
    out = asyncio.run(rt._assistant_reply(_Body(ASKED), ASKED, [], picked=[]))
    assert out is not None
    assert seen["tool_ids"] == []
    assert "Airtable (connected)" in seen["graph"]


def test_the_facts_are_read_now_rather_than_assumed(monkeypatch):
    """The state has to come from the person's own connections, not from
    whatever the triage pick happened to carry. _triage_pick returns an
    EMPTY connected set when it recommends nothing, and treating that as
    "nothing connected" is the same lie with the sign flipped."""
    seen = _wire(monkeypatch, connected=("airtable",))
    asyncio.run(rt._assistant_reply(_Body(ASKED), ASKED, [], picked=[],
                                    triage={"picks": [], "connected": set()}))
    assert "Airtable (connected)" in seen["graph"]


def test_an_app_not_connected_gets_its_connect_button(monkeypatch):
    seen = _wire(monkeypatch, answer="Notion is not connected yet.",
                 connected=())
    text = "can you access notion?"
    out = asyncio.run(rt._assistant_reply(_Body(text), text, [], picked=[]))
    assert "Notion (not connected)" in seen["graph"]
    assert app_triage.connect_href("notion") in out["turns"][0]["answer"]


def test_the_graph_block_is_still_there(monkeypatch):
    seen = _wire(monkeypatch, connected=("airtable",))
    asyncio.run(rt._assistant_reply(_Body(ASKED), ASKED, [], picked=[]))
    assert seen["graph"].startswith("GRAPH")


def test_the_question_that_is_also_a_task_keeps_its_tools(monkeypatch):
    seen = _wire(monkeypatch, connected=("airtable",))
    text = "can you check airtable and create a table in it"
    asyncio.run(rt._assistant_reply(_Body(text), text, [],
                                    picked=["my-airtable_create_table"]))
    assert seen["tool_ids"] == ["my-airtable_create_table"]
    assert "Airtable (connected)" in seen["graph"]


def test_an_ordinary_question_still_goes_to_the_free_model(monkeypatch):
    _wire(monkeypatch, connected=("airtable",))
    text = "can you explain how DNS works?"
    assert asyncio.run(
        rt._assistant_reply(_Body(text), text, [], picked=[])) is None


def test_a_failed_read_does_not_cost_the_answer(monkeypatch):
    """A database that will not answer must not turn a question with tools
    picked into no answer at all. The facts are dropped, the turn runs."""
    seen = _wire(monkeypatch, connected=("airtable",))
    import routes_agents

    async def boom(_email, strict=False):
        raise RuntimeError("no database")

    monkeypatch.setattr(routes_agents, "_connected_providers", boom)
    text = "can you check airtable and create a table in it"
    out = asyncio.run(rt._assistant_reply(_Body(text), text, [],
                                          picked=["my-airtable_create_table"]))
    assert out is not None
    assert seen["graph"] == "GRAPH"


def test_a_failed_read_leaves_a_bare_question_to_the_free_model(monkeypatch):
    """With no tool and no facts there is nothing for the assistant to add,
    and a slow empty turn is worse than the fast answer."""
    _wire(monkeypatch, connected=("airtable",))
    import routes_agents

    async def boom(_email, strict=False):
        raise RuntimeError("no database")

    monkeypatch.setattr(routes_agents, "_connected_providers", boom)
    assert asyncio.run(
        rt._assistant_reply(_Body(ASKED), ASKED, [], picked=[])) is None


def test_the_person_is_told_what_is_happening(monkeypatch):
    """It reads the database, which takes a moment, and the chat says so
    rather than sitting silent."""
    said = []
    monkeypatch.setattr(rt.agent_progress, "say", said.append)
    _wire(monkeypatch, connected=("airtable",))
    asyncio.run(rt._assistant_reply(_Body(ASKED), ASKED, [], picked=[]))
    assert said == [can_do.CHECKING_LINE]
