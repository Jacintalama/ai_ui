"""What "what tools do you have" answers with (2026-11-03).

Lukas asked to see the tools available from every MCP server behind the
proxy. The three meta tools could only search, so the honest answer to "what
can you do" was whatever a search happened to return.
"""
from tool_listing import by_server


def test_each_server_with_its_tool_names_and_a_count():
    got = by_server([
        ("trello", "Trello", [{"name": "list_boards"}, {"name": "get_lists"}]),
        ("github", "GitHub", [{"name": "search_repositories"}]),
    ])
    assert got["servers"] == [
        {"server_id": "github", "name": "GitHub", "tool_count": 1,
         "tools": ["search_repositories"]},
        {"server_id": "trello", "name": "Trello", "tool_count": 2,
         "tools": ["get_lists", "list_boards"]},
    ]
    assert got["tool_count"] == 3 and got["server_count"] == 2


def test_a_server_that_answered_with_an_error_says_so_and_counts_nothing():
    """ClickUp answers [{"error": ...}] while its container crash loops
    (2026-11-03, 129,410 restarts). Listing that as a tool would offer one
    that cannot run."""
    got = by_server([("clickup", "ClickUp", [{"error": "Could not fetch tools from clickup"}])])
    assert got["servers"] == [{"server_id": "clickup", "name": "ClickUp",
                               "tool_count": 0, "tools": [],
                               "note": "not answering right now"}]
    assert got["tool_count"] == 0


def test_a_missing_name_falls_back_to_the_id():
    got = by_server([("my-trello", "", [{"name": "whoami"}])])
    assert got["servers"][0]["name"] == "my-trello"
