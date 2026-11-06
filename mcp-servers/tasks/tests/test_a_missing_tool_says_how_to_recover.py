"""A tool that is not there tells the model how to find the one that is.

2026-11-06. The ClickUp catalogue was regenerated from ClickUp's own spec,
so `list_my_workspaces` became `get_authorized_teams` and `list_spaces`
became `get_spaces`. A chat already in progress kept calling the old
names from its own history. Every call came back:

    The tool my-clickup_list_my_workspaces is not available.

which the model relayed to Ralph as "the execution route is not
available", and then spent all seven of its rounds retrying the same two
dead names. Nothing was created.

The proxy was right and the service was right: `describe_tools` knew
`get_authorized_teams` and correctly did not know the old name. The only
thing missing was a sentence telling the model what to do about it.

`PROXY_META_ABSENT` already says exactly that for a name that never
existed. A name that USED to exist deserves the same, and it is the more
common case, because any rename does this to every chat already open.
"""
import pytest

import agent_tools as T


def test_the_sentence_exists():
    assert hasattr(T, "NO_SUCH_TOOL"), (
        "nothing tells a model what to do when a tool name is wrong")


def test_it_names_the_tool_that_was_missing():
    said = T.NO_SUCH_TOOL.format(name="my-clickup_list_my_workspaces")
    assert "my-clickup_list_my_workspaces" in said


def test_it_says_to_look_the_name_up():
    """Without this the model retries the same dead name until its rounds
    run out, which is what happened."""
    said = T.NO_SUCH_TOOL.format(name="x").lower()
    assert "search_tools" in said
    assert "call_tool" in said


def test_it_says_a_name_may_have_changed():
    """The reason matters: the model is not wrong to have believed in the
    name, it read it earlier in the same conversation."""
    said = T.NO_SUCH_TOOL.format(name="x").lower()
    assert "changed" in said or "renamed" in said


def test_the_runner_uses_it_for_a_404():
    import inspect
    src = inspect.getsource(T)
    i = src.index("status_code == 404")
    nearby = src[i:i + 400]
    assert "NO_SUCH_TOOL" in nearby, (
        "a 404 still answers with a dead end")


def test_the_absent_meta_methods_say_the_same_thing():
    """Two sentences for one situation drift. This is the one place that
    explains a missing tool."""
    src = __import__("inspect").getsource(T)
    assert src.count("NO_SUCH_TOOL") >= 3, (
        "the meta-absent branch still carries its own copy of the advice")
