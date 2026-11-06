"""Every ClickUp operation a person could want, from ClickUp's own spec.

2026-11-06. Ralph: "can you dive to all documentation in clickup to work
in oauth so user can be able to work on the system itself so we dont
missed anything that user cannot do".

Six hand-written tools covered tasks, lists and spaces, and the chat told
him ClickUp could not do the rest. ClickUp's API has 173 operations. So
the tools are GENERATED from the specs ClickUp publishes:

    v2  developer.clickup.com/openapi/clickup-api-v2-reference.json
    v3  developer.clickup.com/openapi/ClickUp_PUBLIC_API_V3.yaml

Generated rather than hand-written because a field name wrong by one
character fails AFTER the person has approved the call, and that already
happened today: the model sent `board_id` where Trello wanted `boardId`.

Committed rather than fetched at runtime, so the tool list cannot change
without a commit somebody reviewed, and so a person's tools do not depend
on ClickUp's docs site being up.
"""
import re

import pytest

import clickup_generated as gen
import mytools

GENERATED = gen.build(mytools.Tool)
TOOLS = {t.name: t for t in GENERATED}


# --- the shape of the catalogue -----------------------------------------

def test_it_covers_the_whole_api_not_a_corner():
    assert len(GENERATED) >= 170, (
        "the generated set shrank; ClickUp has ~173 operations")


def test_no_name_is_used_twice():
    names = [t.name for t in GENERATED]
    assert len(names) == len(set(names)), (
        "a duplicate name means one tool silently shadows another")


def test_both_api_versions_are_present():
    on_v3 = [t for t in GENERATED if t.base]
    on_v2 = [t for t in GENERATED if not t.base]
    assert len(on_v3) >= 30, "chat and docs live on v3"
    assert len(on_v2) >= 130
    for t in on_v3:
        assert t.base.endswith("/api/v3"), (t.name, t.base)


def test_no_path_carries_its_version_twice():
    """The provider base already ends in /api/v2 and a v3 tool carries its
    own base, so a path beginning /v2 or /api/v3 would resolve to
    .../api/v2/v2/task and 404."""
    for t in GENERATED:
        assert not t.path.startswith("/v2"), t.name
        assert not t.path.startswith("/v3"), t.name
        assert not t.path.startswith("/api/"), t.name
        assert t.path.startswith("/"), t.name


# --- the things Ralph actually asked for --------------------------------

@pytest.mark.parametrize("name", [
    "create_chat_channel",      # "create a new channel name it aiui"
    "create_space",             # "can you create a space in click up"
    "create_list",              # "yes name it customer"
    "create_task",              # "create me a task to fix aiui builder"
])
def test_the_thing_he_asked_for_exists(name):
    assert name in TOOLS, "missing: " + name


def test_the_chat_channel_tool_is_the_v3_one():
    t = TOOLS["create_chat_channel"]
    assert t.base.endswith("/api/v3")
    assert t.path == "/workspaces/{workspace_id}/chat/channels"
    assert t.method == "POST"
    assert t.args["name"][2] is True, "ClickUp requires a channel name"


# --- the generator's promises -------------------------------------------

def test_every_body_field_is_also_an_argument():
    """body is what goes to ClickUp, args is what the model may set. A
    body field with no arg can never be filled."""
    for t in GENERATED:
        for field in t.body:
            assert mytools._safe_name(field) in t.args if hasattr(
                mytools, "_safe_name") else field in t.args, (
                "%s sends %s but never asks for it" % (t.name, field))


def test_every_path_placeholder_is_an_argument():
    """A brace nobody fills becomes 'Missing required value' at call time,
    which is a failure the person sees after approving."""
    for t in GENERATED:
        for placeholder in re.findall(r"\{([^}]+)\}", t.path):
            assert placeholder in t.args, (
                "%s has {%s} in its path and no argument for it"
                % (t.name, placeholder))
            assert t.args[placeholder][2] is True, (
                "%s: path value %s must be required" % (t.name, placeholder))


def test_every_query_parameter_maps_to_an_argument():
    for t in GENERATED:
        for param, arg in (t.query or {}).items():
            assert arg in t.args, (
                "%s sends query %s from an argument it does not declare"
                % (t.name, param))


def test_every_tool_says_what_it_does():
    for t in GENERATED:
        assert t.summary.strip(), t.name
        assert t.summary.strip().endswith("."), t.name


def test_a_destructive_tool_says_so_in_its_summary():
    """Somebody reads this sentence before pressing yes."""
    for t in GENERATED:
        if t.name.startswith(("delete_", "remove_")):
            assert "deletes something" in t.summary.lower(), (
                "%s does not warn: %r" % (t.name, t.summary))


def test_the_oauth_token_exchange_is_not_offered():
    """It needs the client secret, which a person's own connection does
    not carry. Offering it is a door with no room behind it."""
    assert "get_access_token" not in TOOLS
    for t in GENERATED:
        assert "oauth" not in t.path.lower(), t.name


def test_a_listing_tool_trims_what_it_returns():
    """ClickUp returns ~40 fields per task. 172 tools answering in full
    is a wall of text the model reads past instead of answering."""
    bare = [t.name for t in GENERATED
            if t.method == "GET" and not t.keep]
    assert len(bare) <= 12, (
        "too many GETs return whole objects: %s" % bare[:10])


# --- it is really generated, not drifted --------------------------------

def test_the_file_says_not_to_edit_it_by_hand():
    import pathlib
    text = pathlib.Path(gen.__file__).read_text(encoding="utf-8")
    assert "GENERATED" in text
    assert "generate_clickup_tools.py" in text


def test_the_generator_is_committed_beside_it():
    import os
    here = os.path.dirname(gen.__file__)
    assert os.path.isfile(os.path.join(here, "tools",
                                       "generate_clickup_tools.py")), (
        "the generated file cannot be regenerated, so it is now hand-written")
