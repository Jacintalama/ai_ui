"""A field that takes a list says so, and says what goes in it.

Measured on production 2026-11-09. Ralph asked the chat to create a
ClickUp task and assign it to him. It took two approvals from him:

    my-clickup_create_task
       list_id: 1301320000003388
       name: New Task
       assignees: ralphbenitez32@gmail.com     <- rejected
    ...then...
    my-clickup_update_task
       task_id: 14zhcp5f9vd
       assignees: 252150963                    <- accepted

The model was not wrong to send an email address. This is everything it
was told about the field:

    assignees   {"anyOf": [{"type": "string"}, {"type": "null"}],
                 "title": "Assignees"}

A plain string, described by repeating its own name. ClickUp's spec says
something quite different:

    assignees   {"type": "array",
                 "items": {"type": "integer"},
                 "description": ""}

So the spec knows it is a list of integer user ids, and both facts are
dropped: `_type_of` collapses every array to "string", and `_describe`
falls back to the field's own name when ClickUp leaves the description
empty. The model is then told "assignees: string" and fills in the only
identifier it has for a person, which is an email address.

It is not one field. In the v2 spec alone, 20 body fields are arrays and
8 of those carry no description at all, so each is presented as a bare
string named after itself.

`_describe`'s own docstring already makes this argument for enums: "a
model that is not told invents a value and gets a 400 after somebody
approved the call. Dropping the enum was throwing away the most useful
half of the spec." An array's item type is the same kind of fact.
"""
import pytest

import clickup_generated
import mytools

TOOLS = {t.name: t for t in clickup_generated.build(mytools.Tool)}


def _arg(tool_name, field):
    tool = TOOLS[tool_name]
    assert field in (tool.args or {}), (
        "%s has no %s argument" % (tool_name, field))
    return tool.args[field]


# --- what the model is told ---------------------------------------------

def test_assignees_is_not_described_as_the_word_assignees():
    """The description that caused this: the field's own name, which adds
    nothing to a model that can already read the name."""
    _kind, desc, _req = _arg("create_task", "assignees")
    assert desc.strip().lower() != "assignees", (
        "the description is just the field name again: %r" % desc)


def test_assignees_says_it_takes_a_list():
    _kind, desc, _req = _arg("create_task", "assignees")
    assert "list" in desc.lower(), desc


def test_assignees_says_the_list_holds_whole_numbers():
    """The whole failure: an id, not a name and not an email."""
    _kind, desc, _req = _arg("create_task", "assignees")
    low = desc.lower()
    assert "integer" in low or "number" in low or "id" in low, desc


def test_a_list_of_text_is_not_called_a_list_of_numbers():
    """tags is an array of strings in the same request. If every array got
    the same sentence the description would be a decoration, not a fact."""
    _kind, desc, _req = _arg("create_task", "tags")
    assert "list" in desc.lower(), desc
    assert "integer" not in desc.lower(), desc


def test_a_field_that_already_had_a_description_keeps_it():
    """group_assignees is an array ClickUp DOES describe. Its own sentence
    is worth more than anything generated, so it must survive."""
    _kind, desc, _req = _arg("create_task", "group_assignees")
    assert "user group" in desc.lower(), desc


def test_a_plain_string_field_is_untouched():
    _kind, desc, _req = _arg("create_task", "name")
    assert "list" not in desc.lower(), desc


# --- what the schema says ------------------------------------------------

def test_a_list_field_is_declared_as_a_list():
    """Telling the model in prose while declaring a string leaves it
    guessing whether to send [1,2] or "1,2". The declared type is the
    half a model trusts."""
    kind, _desc, _req = _arg("create_task", "assignees")
    assert kind == "array", kind


def test_the_schema_built_for_the_model_has_an_array_there():
    """Through mytools, which is what mcp-proxy actually publishes."""
    model = mytools._model_for("clickup", TOOLS["create_task"])
    schema = model.model_json_schema()
    field = (schema.get("properties") or {}).get("assignees") or {}
    flat = str(field)
    assert "array" in flat, field


def test_a_list_the_caller_gives_is_sent_as_a_list():
    """The body the vendor receives. A list in, a list out, unchanged."""
    sent = mytools._payload_for(TOOLS["create_task"],
                                {"name": "New Task", "assignees": [252150963]})
    assert sent["assignees"] == [252150963], sent


# --- the rest of the catalogue -------------------------------------------

def test_every_array_field_says_it_is_a_list():
    """8 of the 20 array body fields in v2 carry no description at all, so
    this cannot be a one-field fix."""
    bare, seen = [], 0
    for tool in TOOLS.values():
        for field, (kind, desc, _req) in (tool.args or {}).items():
            if kind != "array":
                continue
            seen += 1
            if "list" not in (desc or "").lower():
                bare.append("%s.%s: %r" % (tool.name, field, desc))
    # Without this the loop passes by finding nothing, which is exactly how
    # a structural test reports safety it does not have.
    assert seen >= 20, (
        "only %d array fields found; v2 alone has 20" % seen)
    assert not bare, "array fields that do not say so:\n" + "\n".join(bare[:14])


def test_the_catalogue_still_has_every_operation():
    """A generator change must not quietly drop tools. 172 at the last
    regeneration, and the count only ever goes up with ClickUp's spec."""
    assert len(TOOLS) >= 172, len(TOOLS)
