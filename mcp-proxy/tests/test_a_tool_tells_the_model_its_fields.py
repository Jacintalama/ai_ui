"""describe_tools must name a tool's fields, not point at them.

2026-11-06. Ralph's chat could not use Trello or ClickUp. Every call came
back 500 and the chat blamed the connection. The real exchange:

    POST /get_lists  body {'board_id': '...'}   -> 500
    POST /get_lists  body {}                    -> 500
    MCP error -32602: boardId is required when no default board is configured

The field is `boardId`. The model sent `board_id`, and then nothing,
because it was never told. describe_tools answered:

    "parameters": []
    "request_body": {"schema": {"$ref": "#/components/schemas/get_lists_form_model"}}

A $ref into a document the model does not have. Every mcpo-backed tool is
shaped this way, which is why Trello and ClickUp failed together and the
tools written in this repo did not.

So the index inlines the schema at the moment it reads it, while the
server's components are still in hand. Four things this pins:

  * a ref is replaced by the real schema, so field names reach the model
  * a ref that cannot be found is LEFT as it is rather than crashing the
    whole index: one odd tool must not cost every other tool on that server
  * a schema that refers to itself terminates
  * nested refs resolve, because mcpo emits them inside properties
"""
import pytest

import main


COMPONENTS = {
    "get_lists_form_model": {
        "type": "object",
        "properties": {
            "boardId": {"type": "string",
                        "description": "ID of the Trello board"},
        },
    },
    "nested_model": {
        "type": "object",
        "properties": {"inner": {"$ref": "#/components/schemas/leaf_model"}},
    },
    "leaf_model": {"type": "object", "properties": {"deep": {"type": "string"}}},
    "loop_model": {
        "type": "object",
        "properties": {"again": {"$ref": "#/components/schemas/loop_model"}},
    },
}

BODY = {"content": {"application/json": {
    "schema": {"$ref": "#/components/schemas/get_lists_form_model"}}},
    "required": True}


def test_the_resolver_exists():
    assert hasattr(main, "_inline_refs"), (
        "nothing resolves a $ref, so the model is still handed a pointer")


def test_a_ref_becomes_the_real_schema():
    out = main._inline_refs(BODY, COMPONENTS)
    schema = out["content"]["application/json"]["schema"]
    assert "$ref" not in schema
    assert "boardId" in schema["properties"], schema


def test_the_field_name_the_model_needs_is_actually_there():
    """The whole point. Written as the symptom rather than the mechanism:
    if this passes, the chat can call get_lists."""
    import json
    out = json.dumps(main._inline_refs(BODY, COMPONENTS))
    assert "boardId" in out
    assert "$ref" not in out


def test_a_nested_ref_resolves_too():
    out = main._inline_refs(
        {"$ref": "#/components/schemas/nested_model"}, COMPONENTS)
    assert out["properties"]["inner"]["properties"]["deep"]["type"] == "string"


def test_a_ref_that_is_not_there_is_left_alone():
    """One tool with an odd schema must not take down the whole server's
    index. mcpo's own resolver asserts instead, and that is how seven
    connectors spent the day crash-looping."""
    body = {"schema": {"$ref": "#/components/schemas/nope"}}
    out = main._inline_refs(body, COMPONENTS)
    assert out["schema"]["$ref"].endswith("nope")


def test_a_schema_that_refers_to_itself_terminates():
    out = main._inline_refs(
        {"$ref": "#/components/schemas/loop_model"}, COMPONENTS)
    assert isinstance(out, dict)


def test_nothing_is_mutated_in_place():
    """The components dict is the server's own spec and is read for every
    tool on it. Resolving one tool must not rewrite it for the rest."""
    import copy
    before = copy.deepcopy(COMPONENTS)
    main._inline_refs(BODY, COMPONENTS)
    assert COMPONENTS == before


def test_a_body_with_no_ref_comes_back_unchanged():
    plain = {"content": {"application/json": {
        "schema": {"type": "object", "properties": {"q": {"type": "string"}}}}}}
    assert main._inline_refs(plain, COMPONENTS) == plain


def test_the_index_actually_uses_it():
    """A resolver nothing calls fixes nothing."""
    import inspect
    src = inspect.getsource(main)
    assert src.count("_inline_refs(") >= 2, (
        "the resolver is defined but never applied while indexing")
