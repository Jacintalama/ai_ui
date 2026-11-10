"""An argument description has to reach the MODEL, not just the Tool.

Found 2026-11-10, immediately after shipping the list-name lookup. The
served schema for create_task was:

    list_id   -> {"type": "string", "title": "List Id"}
    assignees -> {"anyOf": [{"items": {}, "type": "array"}, ...]}
    status    -> {"anyOf": [{"type": "string"}, {"type": "null"}]}

No descriptions. `_model_for` unpacked `desc` out of each arg and never
used it, so every word written for a model about an argument was dropped
on the way out: the list_id wording added that morning, the assignee
wording ("their id, their email or their name"), the column wording. The
model saw a name and a type.

mcp-proxy caches this schema and `describe_tools` is how a model learns
what to send, so this is the whole channel. A lookup nothing announces
is a lookup nothing uses, which is the exact bug the list lookup was
fixing one layer up.

Why it survived: the tests for all of it asserted `tool.args[field][1]`,
the description on the Tool dataclass. That is the thing that was
correct. The served schema, which is what anybody actually reads, was
never checked. So these tests go through the HTTP surface on purpose.
"""
import pytest
from fastapi.testclient import TestClient

import mytools


@pytest.fixture(scope="module")
def schemas():
    """The OpenAPI each provider serves, as mcp-proxy fetches it."""
    app = mytools.build_app()
    out = {}
    with TestClient(app) as c:
        for provider in mytools.PROVIDER_TOOLS:
            out[provider] = c.get("/" + provider + "/openapi.json").json()
    return out


def _args_of(doc, tool_name):
    """The argument schema a model is handed for one tool."""
    body = doc["paths"]["/" + tool_name]["post"].get("requestBody")
    if not body:
        return {}
    ref = body["content"]["application/json"]["schema"]
    name = None
    for option in ref.get("anyOf", [ref]):
        if "$ref" in option:
            name = option["$ref"].rsplit("/", 1)[-1]
    if not name:
        return {}
    return doc["components"]["schemas"][name].get("properties", {})


def _said(doc, tool_name, field):
    return (_args_of(doc, tool_name).get(field) or {}).get("description", "")


# --- the words that were being dropped ----------------------------------

def test_the_model_is_told_a_list_id_may_be_a_name(schemas):
    said = _said(schemas["clickup"], "create_task", "list_id").lower()
    assert "name" in said, said
    assert "project 1" in said, said


def test_the_model_is_told_an_assignee_may_be_a_name_or_email(schemas):
    """PR #168's wording. It was on the Tool and nowhere a model reads."""
    for tool in ("create_task", "update_task"):
        said = _said(schemas["clickup"], tool, "assignees").lower()
        assert "email" in said, (tool, said)
        assert "name" in said, (tool, said)


def test_the_model_is_told_a_status_is_a_column(schemas):
    said = _said(schemas["clickup"], "update_task", "status").lower()
    assert "column" in said, said


def test_a_field_with_fixed_choices_serves_its_choices(schemas):
    said = _said(schemas["clickup"], "create_chat_message", "type")
    assert "One of:" in said, said


def test_find_list_serves_what_its_name_argument_means(schemas):
    said = _said(schemas["clickup"], "find_list", "name").lower()
    assert "project 1" in said, said


# --- the rule, not the examples -----------------------------------------

def test_every_argument_description_written_is_an_argument_description_served(schemas):
    """Whatever was written for a model has to arrive. Checked across
    every provider so this cannot rot back to one hand-picked tool."""
    missing = []
    for provider, tools in mytools.PROVIDER_TOOLS.items():
        doc = schemas[provider]
        for tool in tools:
            served = _args_of(doc, tool.name)
            for field, (_kind, desc, _required) in (tool.args or {}).items():
                written = str(desc or "").strip()
                if not written:
                    continue
                got = (served.get(field) or {}).get("description", "")
                if got != written:
                    missing.append("%s.%s: served %r" % (tool.name, field,
                                                         got[:40]))
    assert not missing, "descriptions dropped on the way out: %s" % missing[:8]


# --- what must not change while fixing it -------------------------------

def test_a_required_argument_is_still_required(schemas):
    """The old code left a required field out of the class namespace to
    make it required. Attaching a description must not quietly give
    every field a default and make nothing required."""
    doc = schemas["clickup"]
    body = doc["paths"]["/create_task"]["post"]["requestBody"]
    ref = body["content"]["application/json"]["schema"]
    name = [o["$ref"].rsplit("/", 1)[-1]
            for o in ref.get("anyOf", [ref]) if "$ref" in o][0]
    required = doc["components"]["schemas"][name].get("required", [])
    assert "list_id" in required and "name" in required, required
    assert "status" not in required, required


def test_an_optional_argument_still_takes_nothing(schemas):
    """It has to stay nullable, or a tool call that omits it is refused
    before it reaches us."""
    status = _args_of(schemas["clickup"], "create_task").get("status", {})
    assert {"type": "null"} in status.get("anyOf", []), status


def test_a_tool_with_no_arguments_still_serves(schemas):
    """whoami takes nothing. It must not grow a body schema or break."""
    assert "/whoami" in schemas["clickup"]["paths"]
    assert _args_of(schemas["clickup"], "whoami") == {}


def test_the_declared_type_is_unchanged(schemas):
    """A list field says it is a list, an object field an object. Those
    are pinned elsewhere; this is here so a change to how fields are
    built cannot pass by moving them."""
    args = _args_of(schemas["clickup"], "create_task")
    assert {"items": {}, "type": "array"} in args["assignees"]["anyOf"]
    assert args["list_id"]["type"] == "string"


@pytest.mark.parametrize("provider,tool,field", [
    ("github", "read_file", "path"),
    ("github", "create_issue", "title"),
    ("trello", "create_card", "list_id"),
    ("n8n", "list_my_workflows", "limit"),
])
def test_the_hand_written_providers_serve_their_wording_too(
        schemas, provider, tool, field):
    """Not a ClickUp fix. Every provider here writes argument
    descriptions and every one of them was being dropped."""
    assert _said(schemas[provider], tool, field)
