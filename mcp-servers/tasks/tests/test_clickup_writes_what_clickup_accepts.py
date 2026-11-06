"""The ClickUp write tools send what ClickUp actually requires.

This replaces the suite written for the six hand-made tools. Those are
gone: ClickUp is generated from ClickUp's own spec now, all 172
operations, so a name or a field can no longer be wrong because I read
the docs quickly. What a generator CANNOT get right on its own is what a
person means when they leave a required field out, and that is what is
tested here.

The failure this guards against is specific and was real on 2026-11-06:
a required field quietly absent, the call approved by the person, and the
400 arriving afterwards. By then they have already said yes.
"""
import pytest

import clickup_generated
import mytools

TOOLS = {t.name: t for t in clickup_generated.build(mytools.Tool)}


# --- a required field with one obvious answer ---------------------------

def test_a_chat_message_carries_a_type_even_when_nobody_said_one():
    """ClickUp requires `type` and accepts only message or post. A person
    asking to send a message means message; post is a different thing in
    their UI and is never the implied one."""
    t = TOOLS["create_chat_message"]
    assert t.defaults.get("type") == "message"
    assert mytools._payload_for(t, {"content": "hi"}) == {
        "content": "hi", "type": "message"}


def test_a_type_the_caller_gives_is_kept():
    t = TOOLS["create_chat_message"]
    assert mytools._payload_for(t, {"content": "hi", "type": "post"})["type"] \
        == "post"


def test_a_default_is_never_invented_for_a_field_the_tool_does_not_send():
    for tool in mytools.ALL_TOOLS_FLAT:
        for field in tool.defaults:
            assert field in tool.body, (
                "%s defaults %s but never sends it" % (tool.name, field))


def test_a_default_is_never_set_on_a_tool_that_did_not_ask_for_one():
    """The table is keyed by tool AND field so a default cannot leak to
    another endpoint that happens to have a field of the same name."""
    import tools.generate_clickup_tools as g
    for (name, field) in g.DEFAULTS:
        assert name in TOOLS, "default for a tool that does not exist: " + name
        assert field in TOOLS[name].body, (name, field)


# --- the model is told what it may send ---------------------------------

def test_a_field_with_fixed_choices_says_what_they_are():
    """ClickUp declares type as one of message or post. A model that is
    not told invents a value and the call 400s after approval."""
    t = TOOLS["create_chat_message"]
    kind, description, required = t.args["type"]
    assert "One of:" in description, description
    assert "message" in description and "post" in description
    assert required is True


def test_choices_are_carried_wherever_the_spec_gives_them():
    with_choices = [t.name for t in TOOLS.values()
                    if any("One of:" in d for _, d, _ in t.args.values())]
    assert len(with_choices) >= 5, (
        "enums are being dropped again: %s" % with_choices)


# --- names a person and a model can both read ---------------------------

def test_no_tool_name_is_an_unreadable_run_of_words():
    """ClickUp's own operationIds include createatimeentry. A name with no
    word breaks cannot be matched against a request and cannot be read in
    an approval prompt."""
    bad = [n for n in TOOLS if "_" not in n and len(n) > 12]
    assert not bad, bad


@pytest.mark.parametrize("name", [
    "create_task", "create_list", "create_space", "create_folder",
    "create_chat_channel", "create_chat_message", "create_a_time_entry",
    "start_a_time_entry", "create_webhook", "set_custom_field_value",
    "create_goal", "create_checklist", "create_space_tag", "create_doc_public",
])
def test_the_everyday_write_exists(name):
    assert name in TOOLS, "missing: " + name
