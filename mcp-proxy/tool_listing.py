"""The answer to "what tools do you have", one server at a time (2026-11-03).

Pure, so it is testable without a network. The endpoint in main.py does the
fetching, with the same live per-server call GET /{server_id} makes. Not the
search index behind /meta/stats: that one still counts 172 ClickUp tools for
a server that answers with none.
"""


def by_server(entries) -> dict:
    """entries: (server_id, display name, tools as fetch_server_tools gives
    them). A tool without a name is an error object, never a tool."""
    servers = []
    for server_id, name, tools in entries:
        names = sorted(str(t["name"]) for t in tools or []
                       if isinstance(t, dict) and t.get("name"))
        row = {"server_id": server_id, "name": name or server_id,
               "tool_count": len(names), "tools": names}
        if not names:
            row["note"] = "not answering right now"
        servers.append(row)
    servers.sort(key=lambda s: s["server_id"])
    return {"server_count": len(servers),
            "tool_count": sum(s["tool_count"] for s in servers),
            "servers": servers}
