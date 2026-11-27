"""The rules for a person's own MCP server, with no I/O in them.

A person pastes an address and a token, and the tools their server lists
become tools in our catalogue, for them only. Everything here decides
something about that: whether the address is acceptable, what the tools are
called, which of them we use, and which may run without asking first.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import own_mcp  # noqa: E402


# --- the address -----------------------------------------------------------

def test_only_https_with_a_host_is_accepted():
    assert own_mcp.address_problem("https://mcp.example.com/mcp") == ""
    for bad in ("http://mcp.example.com/mcp", "ftp://mcp.example.com",
                "https://", "mcp.example.com", "", None):
        said = own_mcp.address_problem(bad)
        assert said, bad
        assert "mcp.example.com" not in said, "a refusal never repeats the address"


# --- names -----------------------------------------------------------------

def test_a_slug_is_short_lowercase_and_unique_per_person():
    assert own_mcp.slug_for("Acme Billing!", set()) == "acmebilling"
    assert own_mcp.slug_for("Acme", {"acme"}) == "acme2"
    assert own_mcp.slug_for("Acme", {"acme", "acme2"}) == "acme3"
    assert len(own_mcp.slug_for("x" * 50, set())) == 20
    assert own_mcp.slug_for("!!!", set()) == ""


def test_a_unique_slug_still_fits_in_20():
    taken = {"x" * 20}
    slug = own_mcp.slug_for("x" * 50, taken)
    assert slug not in taken and len(slug) <= 20


def test_a_tool_name_is_cleaned_and_capped():
    assert own_mcp.tool_name("acme", "create.invoice") == "own-acme_create_invoice"
    assert own_mcp.tool_name("acme", "a b/c") == "own-acme_a_b_c"
    assert len(own_mcp.tool_name("a" * 20, "t" * 100)) == 64


# --- the snapshot ----------------------------------------------------------

def test_the_snapshot_keeps_40_and_says_why_the_rest_are_not_used():
    listed = {"tools": [{"name": f"t{i}", "inputSchema": {}} for i in range(45)]}
    used, skipped = own_mcp.snapshot("acme", listed)
    assert len(used) == 40
    assert len(skipped) == 5
    assert used[0]["name"] == "own-acme_t0" and used[0]["tool"] == "t0"


def test_junk_from_a_server_never_raises():
    for junk in (None, {}, [], "x", {"tools": "x"},
                 {"tools": [{}, {"name": "!!!"}, 7, {"name": None}]}):
        used, skipped = own_mcp.snapshot("acme", junk)
        assert isinstance(used, list) and isinstance(skipped, list)


def test_a_name_with_nothing_usable_in_it_is_not_used():
    used, skipped = own_mcp.snapshot("acme", {"tools": [{"name": "!!!"}]})
    # "!!!" cleans to "___", which is still a name; an empty one is not.
    used2, skipped2 = own_mcp.snapshot("acme", {"tools": [{"name": "  "}]})
    assert used2 == [] and len(skipped2) == 1


def test_a_schema_over_8kb_is_not_used():
    big = {"tools": [{"name": "big", "inputSchema": {"d": "x" * 9000}}]}
    used, skipped = own_mcp.snapshot("acme", big)
    assert used == [] and len(skipped) == 1


def test_two_tools_that_clean_to_one_name_keep_the_first():
    used, skipped = own_mcp.snapshot(
        "acme", {"tools": [{"name": "get.item"}, {"name": "get_item"}]})
    assert [t["tool"] for t in used] == ["get.item"]
    assert len(skipped) == 1 and "get_item" in skipped[0]


def test_descriptions_are_cut_at_600():
    used, _ = own_mcp.snapshot(
        "acme", {"tools": [{"name": "t", "description": "d" * 900}]})
    assert len(used[0]["description"]) <= 600


def test_a_missing_schema_is_an_empty_object():
    used, _ = own_mcp.snapshot("acme", {"tools": [{"name": "t"}]})
    assert used[0]["input_schema"] == {"type": "object", "properties": {}}


# --- asking first ----------------------------------------------------------

def test_read_only_needs_the_hint_and_a_read_verb():
    listed = {"tools": [
        {"name": "list_customers", "annotations": {"readOnlyHint": True}},
        {"name": "create_invoice", "annotations": {"readOnlyHint": True}},
        {"name": "list_items"},
        {"name": "get_item", "annotations": {"readOnlyHint": "yes"}}]}
    used, _ = own_mcp.snapshot("acme", listed)
    assert [t["read_only"] for t in used] == [True, False, False, False]


def test_read_only_is_per_person_and_unknown_is_a_write():
    own_mcp.remember("a@x.com", [{"name": "own-acme_list", "read_only": True},
                                 {"name": "own-acme_make", "read_only": False}])
    assert own_mcp.read_only("a@x.com", "own-acme_list") is True
    assert own_mcp.read_only("a@x.com", "own-acme_make") is False
    assert own_mcp.read_only("b@x.com", "own-acme_list") is False
    assert own_mcp.read_only("a@x.com", "own-acme_other") is False
    assert own_mcp.read_only("", "own-acme_list") is False


def test_remembering_again_replaces_what_was_known():
    own_mcp.remember("c@x.com", [{"name": "own-acme_list", "read_only": True}])
    own_mcp.remember("c@x.com", [])
    assert own_mcp.read_only("c@x.com", "own-acme_list") is False


# --- the catalogue ---------------------------------------------------------

def test_the_catalogue_entry_has_the_describe_shape():
    used, _ = own_mcp.snapshot("acme", {"tools": [
        {"name": "list_customers", "description": "Lists customers",
         "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
         "annotations": {"readOnlyHint": True}}]})
    [entry] = own_mcp.catalogue("acme", "Acme", used)
    assert entry == {
        "name": "own-acme_list_customers",
        "description": "Lists customers",
        "request_body": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"q": {"type": "string"}}}}}},
        "server_id": "own-acme",
        "server_name": "Acme",
        "read_only": True,
    }


# --- Jev -------------------------------------------------------------------

def test_the_jev_note_is_empty_without_servers():
    assert own_mcp.jev_note([]) == ""
    assert own_mcp.jev_note([{"label": "Acme", "tools": []}]) == ""


def test_the_jev_note_names_up_to_8_tools_per_server():
    note = own_mcp.jev_note([{"label": "Acme",
                              "tools": [{"tool": f"t{i}"} for i in range(10)]}])
    assert note.startswith(" and their own servers: Acme (t0, t1,")
    assert note.count(",") == 8 and note.endswith(", ...)")  # 8 names, then ", ..."


def test_the_jev_note_has_no_ellipsis_when_nothing_was_cut():
    note = own_mcp.jev_note([{"label": "Acme", "tools": [{"tool": "a"}, {"tool": "b"}]},
                             {"label": "Zed", "tools": [{"tool": "c"}]}])
    assert note == " and their own servers: Acme (a, b); Zed (c)"
