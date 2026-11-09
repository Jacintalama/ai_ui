"""A field that takes an object says so, and names what goes in it.

Measured 2026-11-09, an hour after the array half of this shipped. Ralph
asked the chat to assign an existing task to himself. It asked him to
approve the same call three times and never completed:

    my-clickup_update_task
       task_id: 14zhcp5fd46
       assignees: {'add': [106928073]}

The model had it exactly right. ClickUp's spec for PUT /task/{task_id}:

    assignees   {"type": "object", "required": ["add", "rem"],
                 "properties": {"add": {...}, "rem": {...}}}

and ours said:

    assignees   ('string', 'Assignees', False)

`_type_of` mapped every object to "string", so the model's dict could
not get through a field declared `str`, and `_describe` fell back to the
field's own title. PR #159 fixed the array case and I wrote in it that
"an object still reads as a string: that is a separate shape and no tool
has needed it yet". update_task needed it within the hour.

Note the two are genuinely different shapes and both are right:

    POST /list/{id}/task   assignees  array of integers
    PUT  /task/{id}        assignees  object {add: [...], rem: [...]}

so this cannot be fixed by making every assignees field the same thing.
It has to come from the spec, per operation.

18 body fields in the v2 spec are objects and 13 carry no description,
so each was a bare string named after itself: `features` with nine
required sub-fields, `tag` with name, fg_color and bg_color.
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


# --- the one that was asked for three times ------------------------------

def test_updating_assignees_is_declared_an_object():
    kind, _desc, _req = _arg("update_task", "assignees")
    assert kind == "object", kind


def test_updating_assignees_names_add_and_rem():
    _kind, desc, _req = _arg("update_task", "assignees")
    assert "add" in desc and "rem" in desc, desc


def test_updating_assignees_is_not_described_as_its_own_title():
    _kind, desc, _req = _arg("update_task", "assignees")
    assert desc.strip().lower() != "assignees", desc


def test_the_schema_the_model_sees_has_an_object_there():
    model = mytools._model_for("clickup", TOOLS["update_task"])
    field = (model.model_json_schema().get("properties") or {}).get("assignees")
    assert "object" in str(field), field


def test_the_dict_the_model_sends_is_sent_as_a_dict():
    sent = mytools._payload_for(TOOLS["update_task"],
                                {"assignees": {"add": [106928073]}})
    assert sent["assignees"] == {"add": [106928073]}, sent


# --- the two shapes stay different ---------------------------------------

def test_creating_a_task_still_takes_a_list_of_assignees():
    """The same field name, a different shape, one operation apart. A fix
    that made them agree would break one of them."""
    kind, desc, _req = _arg("create_task", "assignees")
    assert kind == "array", kind
    assert "list" in desc.lower(), desc


# --- the rest of the catalogue -------------------------------------------

def test_an_objects_required_fields_are_named():
    """`tag` on POST /space/{id}/tag requires name, tag_fg and tag_bg, and
    a call missing one fails after somebody approved it."""
    _kind, desc, _req = _arg("create_space_tag", "tag")
    low = desc.lower()
    assert "name" in low, desc
    assert "tag_fg" in low or "tag_bg" in low, desc


def test_every_object_field_says_it_is_an_object():
    seen, bare = 0, []
    for tool in TOOLS.values():
        for field, (kind, desc, _req) in (tool.args or {}).items():
            if kind != "object":
                continue
            seen += 1
            if "object" not in (desc or "").lower():
                bare.append("%s.%s: %r" % (tool.name, field, desc))
    # Not a loop that passes by finding nothing: v2 alone has 18.
    assert seen >= 18, "only %d object fields found; v2 has 18" % seen
    assert not bare, "object fields that do not say so:\n" + "\n".join(bare[:12])


def test_a_plain_string_field_is_still_a_plain_string():
    kind, desc, _req = _arg("update_task", "name")
    assert kind == "string", kind
    assert "object" not in desc.lower(), desc


def test_the_catalogue_still_has_every_operation():
    assert len(TOOLS) >= 172, len(TOOLS)


def test_the_shape_sentence_does_not_repeat_the_title():
    """ClickUp gives these fields a `title` and an empty `description`, so
    the fallback used to supply the field's own name. Once the shape is
    stated the title adds nothing, and "...required. Assignees" reads like
    a generated string rather than a sentence."""
    for tool, field in (("update_task", "assignees"),
                        ("create_space_tag", "tag"),
                        ("update_space", "features")):
        _kind, desc, _req = _arg(tool, field)
        assert not desc.strip().endswith(("Assignees", "Tag", "Features")), (
            "%s.%s: %r" % (tool, field, desc))


def test_a_real_description_is_still_kept():
    """Only the title is dropped. A sentence ClickUp actually wrote is
    worth more than anything generated."""
    _kind, desc, _req = _arg("create_task", "group_assignees")
    assert "user group" in desc.lower(), desc
