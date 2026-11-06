"""A tool that was renamed stops being searchable.

2026-11-06. Ralph asked a FRESH chat to create a ClickUp space. It
answered "the tool runner is refusing every call, including the workspace
listing", and nothing was created. The proxy log:

    Tool: my-clickup_list_my_workspaces
    POST /meta/call_tool  404 Not Found      (five times)

The ClickUp catalogue had been regenerated from ClickUp's own spec, so
list_my_workspaces became get_authorized_teams. describe_tools correctly
answered "Tool not found" and call_tool correctly 404'd. But search_tools
still OFFERED the old name, so the model picked it every time:

    my-clickup_list_spaces          <- gone
    my-clickup_list_my_workspaces   <- gone
    my-clickup_get_spaces           <- the real one

Two indexes and only one was refreshed. TOOLS_CACHE is rebuilt from each
server's OpenAPI on boot; the embeddings table is upserted and never
cleaned, and prune_stale_tools removes rows only for servers that are
GONE. my-clickup is still registered and enabled, so its renamed tools
survived.

The careful part is the existing rule, which this must not break: a
server that is up but momentarily failed to list its tools keeps every
row, or one bad boot empties the index. So a server is only pruned
tool-by-tool when it actually listed tools this boot.
"""
import pytest

from tool_embeddings import stale_tool_keys, unknown_server_ids


LIVE = {"my-clickup", "trello", "gmail"}


def _indexed(*pairs):
    return [{"server_id": s, "tool_name": t} for s, t in pairs]


# --- the existing rule still holds --------------------------------------

def test_a_server_that_is_gone_is_still_pruned_whole():
    assert unknown_server_ids({"my-clickup", "ghost"}, LIVE) == {"ghost"}


def test_an_empty_live_list_prunes_nothing():
    """"the registry did not load" and "no server exists" must stay
    distinct, or one bad boot empties the index."""
    assert unknown_server_ids({"my-clickup"}, set()) == set()


# --- the new rule -------------------------------------------------------

def test_a_renamed_tool_is_pruned():
    indexed = _indexed(("my-clickup", "my-clickup_list_my_workspaces"),
                       ("my-clickup", "my-clickup_get_authorized_teams"))
    live = {"my-clickup": {"my-clickup_get_authorized_teams"}}
    assert stale_tool_keys(indexed, live) == {
        ("my-clickup", "my-clickup_list_my_workspaces")}


def test_a_tool_that_is_still_there_survives():
    indexed = _indexed(("my-clickup", "my-clickup_get_authorized_teams"))
    live = {"my-clickup": {"my-clickup_get_authorized_teams"}}
    assert stale_tool_keys(indexed, live) == set()


def test_a_server_that_listed_nothing_keeps_every_row():
    """THE guard. A server that is up but failed to list its tools this
    boot must not have its index emptied: that is one bad boot away from
    a chat with no tools at all."""
    indexed = _indexed(("my-clickup", "my-clickup_get_authorized_teams"),
                       ("my-clickup", "my-clickup_list_my_workspaces"))
    assert stale_tool_keys(indexed, {"my-clickup": set()}) == set()
    assert stale_tool_keys(indexed, {}) == set()
    assert stale_tool_keys(indexed, None) == set()


def test_a_server_not_in_the_listing_is_left_to_the_server_rule():
    """Tool-level pruning only speaks about servers that listed. Whether
    a missing server should go at all is unknown_server_ids' decision,
    and two rules answering one question is how this drifts again."""
    indexed = _indexed(("ghost", "ghost_do_thing"))
    live = {"my-clickup": {"my-clickup_get_authorized_teams"}}
    assert stale_tool_keys(indexed, live) == set()


def test_an_odd_row_does_not_delete_anything():
    for rows in (None, [], [{}], [{"server_id": None, "tool_name": None}],
                 "nonsense"):
        assert stale_tool_keys(rows, {"my-clickup": {"x"}}) == set()


def test_the_decision_is_pure():
    """Destructive, so it is decided without a database and tested
    without one, like unknown_server_ids beside it."""
    import inspect
    src = inspect.getsource(stale_tool_keys)
    for forbidden in ("await", "conn", "pool", "DELETE"):
        assert forbidden not in src, (
            "the decision touches the database: " + forbidden)


# --- the SQL, which the pure tests never touched ------------------------

def test_the_delete_does_not_send_an_anonymous_composite():
    """The first version used

        WHERE (server_id, tool_name) = ANY($1::record[])

    and asyncpg answered "input of anonymous composite types is not
    supported". Every test above passed, because they all test the pure
    decision and none of them run the statement. It failed on the box,
    silently, caught only by its own fail-open log.
    """
    import inspect

    import tool_embeddings

    src = inspect.getsource(tool_embeddings.prune_renamed_tools)
    # The STATEMENT, not the comments: the comment above it names the
    # broken form on purpose, so a whole-source search finds itself.
    i = src.index("DELETE FROM")
    statement = src[i:i + 220]
    assert "record[]" not in statement, (
        "asyncpg cannot send an anonymous composite; delete per server")
    assert "server_id = $1 AND tool_name = ANY($2::text[])" in statement


def test_the_delete_is_scoped_to_one_server_at_a_time():
    """A statement that names only tool_name would delete another
    server's tool of the same name."""
    import inspect

    import tool_embeddings

    src = inspect.getsource(tool_embeddings.prune_renamed_tools)
    i = src.index("DELETE FROM")
    statement = src[i:i + 200]
    assert "server_id = $1" in statement, statement


def test_it_still_fails_open():
    """An index with an extra row is worse than one that could not be
    tidied. Neither is worth refusing to boot, and this is how the broken
    query was survivable at all."""
    import inspect

    import tool_embeddings

    src = inspect.getsource(tool_embeddings.prune_renamed_tools)
    assert "except Exception" in src
    assert "return 0" in src.split("except Exception")[1]
