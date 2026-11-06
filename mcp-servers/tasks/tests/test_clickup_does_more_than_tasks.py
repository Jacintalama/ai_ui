"""The per-user ClickUp tools cover more than tasks and lists.

2026-11-06. Ralph asked the chat to make a ClickUp channel called "aiui".
It answered that ClickUp channels "can't be made through a task-based API
connection like this one", which is not true: his account has five of them
already. The real reason was ours. The per-user service implemented six
tools, all on ClickUp's v2 API, and chat lives on v3, while every request
is built as `auth.base_url + path` with the base pinned to v2. There was
no route to a v3 path at all.

So this adds the v3 escape hatch and the tools that were missing. Two
rules it pins down:

  * a tool may override the base URL, and ONLY for that tool, so one v3
    endpoint cannot quietly move every v2 endpoint with it
  * the write tools send what ClickUp actually requires, checked against
    its reference rather than guessed: creating a message needs `type`
    as well as `content`, and sending only the text is a 400
"""
import pytest

import mytools

CLICKUP = {t.name: t for t in mytools.CLICKUP_TOOLS}


def _names():
    return set(CLICKUP)


# --- the v3 escape hatch -------------------------------------------------

def test_a_tool_can_override_the_base_url():
    """Without this, chat is unreachable: the vendor base is v2 and every
    URL is base + path."""
    assert hasattr(mytools.Tool("x", "x", "GET", "/x"), "base")


def test_only_the_chat_tools_leave_v2():
    """The override is per tool on purpose. Moving the shared base to v3
    would take list_tasks and create_task with it."""
    on_v3 = {t.name for t in mytools.CLICKUP_TOOLS if t.base}
    assert on_v3, "nothing uses the override, so chat cannot work"
    for name in on_v3:
        assert "chat" in name, name
        assert mytools.CLICKUP_TOOLS[0].base == "", (
            "a v2 tool picked up a base override")


@pytest.mark.parametrize("name", ["create_chat_channel", "list_chat_channels",
                                  "send_chat_message"])
def test_the_chat_tools_point_at_v3(name):
    tool = CLICKUP[name]
    assert tool.base.endswith("/api/v3"), tool.base
    assert tool.path.startswith("/workspaces/"), tool.path


# --- what was missing ----------------------------------------------------

@pytest.mark.parametrize("name", [
    "create_list", "create_folder", "list_folders", "create_space",
    "get_task", "update_task", "add_comment", "list_comments",
    "create_chat_channel", "list_chat_channels", "send_chat_message",
])
def test_the_tool_exists(name):
    assert name in _names(), "missing: " + name


def test_the_six_that_already_worked_are_untouched():
    for name in ("list_my_workspaces", "list_spaces", "list_lists",
                 "list_tasks", "create_task", "whoami"):
        assert name in _names(), name
        assert CLICKUP[name].base == "", name


# --- the shapes ClickUp actually requires --------------------------------

def test_creating_a_channel_sends_the_name():
    t = CLICKUP["create_chat_channel"]
    assert t.method == "POST"
    assert "name" in t.body
    assert t.args["name"][2] is True, "name is required by ClickUp"
    assert t.args["workspace_id"][2] is True


def test_sending_a_message_sends_type_as_well_as_content():
    """ClickUp's reference requires both. Sending only the text is a 400,
    and a tool that is wrong here fails at the worst moment, after the
    person has approved it."""
    t = CLICKUP["send_chat_message"]
    assert t.method == "POST"
    assert "content" in t.body
    assert "type" in t.body, "ClickUp rejects a message with no type"
    assert "{channel_id}" in t.path


def test_a_write_tool_never_sends_a_field_it_does_not_declare():
    """body is what goes to the vendor; args is what the model may pass.
    A field in body with no arg can never be filled, and an arg the model
    can set that is not in body is silently dropped."""
    for tool in mytools.CLICKUP_TOOLS:
        for field in tool.body:
            assert field in tool.args, (
                "%s sends %s but never asks for it" % (tool.name, field))


def test_every_tool_says_what_it_is_for():
    for tool in mytools.CLICKUP_TOOLS:
        assert tool.summary.strip(), tool.name
        assert tool.summary.strip().endswith("."), tool.name


def test_no_tool_name_repeats():
    names = [t.name for t in mytools.CLICKUP_TOOLS]
    assert len(names) == len(set(names)), names


# --- a default that is actually applied ----------------------------------

def test_a_message_with_no_type_still_carries_one():
    """ClickUp requires `type` and rejects the message without it. It was
    declared optional with a comment saying it defaults to "message", and
    nothing applied that default: the payload is built from the args that
    were PASSED, so an unset field is simply absent and the call is a 400.

    A comment claiming a behaviour that does not exist is worse than no
    comment, because it reads as settled.
    """
    t = CLICKUP["send_chat_message"]
    assert t.defaults.get("type") == "message"

    payload = mytools._payload_for(t, {"content": "hello"})
    assert payload == {"content": "hello", "type": "message"}


def test_a_type_the_caller_gives_is_not_overridden():
    t = CLICKUP["send_chat_message"]
    payload = mytools._payload_for(t, {"content": "hi", "type": "post"})
    assert payload["type"] == "post"


def test_a_default_never_invents_a_field_the_tool_does_not_send():
    for tool in mytools.ALL_TOOLS_FLAT:
        for key in tool.defaults:
            assert key in tool.body, (
                "%s defaults %s but never sends it" % (tool.name, key))
