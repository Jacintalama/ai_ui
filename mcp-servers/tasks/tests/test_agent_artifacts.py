"""A main chat reply keeps what it carries, whatever the model wrote
(2026-11-09).

A tool that starts a build or a video ends its result with a line the page
reads and the person never sees:

    [aiui-artifact]: #build/528f5422-5dea-4c5a-8638-8e919a01109b

The model was asked to copy it. Nothing checked. On 2026-11-05 a reply said
"Building it now as tip-calculator-badb" with no id, and the chat never said
the build had finished.
"""
import asyncio

import agent_activity
import agent_artifacts as A
import agent_runner

BUILD = "[aiui-artifact]: #build/528f5422-5dea-4c5a-8638-8e919a01109b"
APP = "[aiui-artifact]: #app/tip-calculator-badb"
SAID = "Building it now as tip-calculator-badb."


def tool(content, name="create_app"):
    return {"role": "tool", "tool_call_id": "c1", "name": name, "content": content}


USER = {"role": "user", "content": "build me a tip calculator"}


def test_a_dropped_line_comes_back_after_a_blank_line():
    convo = [USER, tool("Building it now.\n\n" + BUILD)]
    # A blank line because a reference definition cannot interrupt a
    # paragraph: without it markdown would print the line to the person.
    assert A.carried(SAID, convo) == SAID + "\n\n" + BUILD


def test_a_line_the_model_kept_is_not_doubled():
    convo = [USER, tool("Building it now.\n\n" + BUILD)]
    kept = SAID + "\n\n" + BUILD
    assert A.carried(kept, convo) == kept


def test_every_line_this_turn_comes_back_in_order_once():
    convo = [USER, tool("x\n\n" + BUILD), tool("y\n\n" + APP, "build_status"),
             tool("again\n\n" + BUILD, "build_status")]
    assert A.declared_this_turn(convo) == [BUILD, APP]
    assert A.carried(SAID, convo) == SAID + "\n\n" + BUILD + "\n" + APP


def test_an_earlier_turn_is_not_this_turn():
    """Otherwise every later reply in the chat re-declares an old build."""
    convo = [USER, tool("x\n\n" + BUILD),
             {"role": "assistant", "content": "done"},
             {"role": "user", "content": "thanks, what else can you do"}]
    assert A.declared_this_turn(convo) == []


def test_only_a_tool_result_can_declare_something():
    """The person's own words and the model's are not declarations."""
    convo = [{"role": "user", "content": BUILD},
             {"role": "assistant", "content": BUILD}]
    assert A.declared_this_turn(convo) == []


def test_a_line_that_is_not_quite_one_is_ignored():
    convo = [USER, tool("see [aiui-artifact]: #build/abc in the text\n"
                        "[aiui-artifact]: #secret/abc\n")]
    assert A.declared_this_turn(convo) == []


def test_nothing_declared_leaves_the_answer_alone():
    assert A.carried(SAID, [USER, tool("3 unread")]) == SAID


def test_an_empty_answer_stays_empty():
    """The callers fall back on the notes when the answer is empty."""
    assert A.carried("", [USER, tool("x\n\n" + BUILD)]) == ""


def test_odd_messages_do_not_break_it():
    assert A.declared_this_turn([None, "x", {"role": "tool", "content": None},
                                 {"role": "tool", "content": [1]}]) == []


# --- wired into the turn ---------------------------------------------------

def test_the_main_chat_turn_gets_the_line_and_a_bot_turn_does_not(monkeypatch):
    """Discord and Slack have no markdown that hides the line, so they would
    print it to the person. Only the main chat carries it."""
    convo = [USER, tool("Building it now.\n\n" + BUILD)]
    assert agent_runner._finished(SAID, convo) == SAID
    with agent_activity.main_chat():
        assert agent_runner._finished(SAID, convo) == SAID + "\n\n" + BUILD
