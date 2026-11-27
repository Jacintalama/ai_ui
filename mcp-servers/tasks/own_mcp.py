"""The rules for a person's own MCP server. Pure: no I/O, no database.

A person pastes an address and an optional token in Connections, and the
tools their server lists become tools in our catalogue, for them only, named
``own-<slug>_<tool>``. This module decides everything about that which can
be decided without talking to anybody:

- whether an address is acceptable before we even resolve it (https only:
  the token travels in a header, and ``host_guard`` accepts http because
  n8n and Jira need it);
- the slug and the catalogue name of each tool;
- which tools we use (the first 40, each with a schema under 8 KB) and why
  the rest are not used;
- which tools count as reads, and the per-person memory of that the agent
  loop asks before holding a call for approval;
- the line Jev is shown about a person's own servers.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md
"""
from __future__ import annotations

import json
import re
import urllib.parse
from collections import OrderedDict
from typing import Any

MAX_SERVERS = 5
MAX_TOOLS = 40
DESC_CHARS = 600
SCHEMA_BYTES = 8192
NAME_CHARS = 64
LABEL_CHARS = 40
SLUG_CHARS = 20
PREFIX = "own-"
#: How many tool names per server Jev is shown.
JEV_TOOLS = 8
#: People whose read-only answers are kept in memory, oldest dropped.
REMEMBERED_PEOPLE = 500

EMPTY_SCHEMA = {"type": "object", "properties": {}}

_NOT_SLUG = re.compile(r"[^a-z0-9]")
_NOT_TOOL = re.compile(r"[^A-Za-z0-9_-]")


# --- the address -----------------------------------------------------------

def address_problem(url: Any) -> str:
    """"" for an https address with a host, else what is wrong with it.

    Never repeats the address: some vendors put the key in it.
    """
    if not isinstance(url, str) or not url.strip():
        return "Paste the address of your MCP server, starting with https://."
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return "That does not look like a web address. It should start with https://."
    if parts.scheme.lower() != "https":
        return ("The address must start with https://, because your token "
                "travels with every call.")
    if not parts.hostname:
        return "That address has no server name in it after https://."
    return ""


def label_problem(label: Any) -> str:
    """"" for a usable name, else what is wrong with it."""
    if not isinstance(label, str) or not label.strip():
        return "Give the server a name, so you can tell it apart."
    if len(label.strip()) > LABEL_CHARS:
        return f"Keep the name to {LABEL_CHARS} characters or fewer."
    if not _NOT_SLUG.sub("", label.lower()):
        return "Use at least one letter or number in the name."
    return ""


# --- names -----------------------------------------------------------------

def slug_for(label: str, taken: set[str]) -> str:
    """The tool prefix for a server: ``[a-z0-9]``, at most 20, unique among
    ``taken``. "" when the label has no letter or number in it."""
    base = _NOT_SLUG.sub("", str(label or "").lower())[:SLUG_CHARS]
    if not base:
        return ""
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = str(n)
        candidate = base[:SLUG_CHARS - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def tool_name(slug: str, tool: str) -> str:
    """``own-<slug>_<tool>``, cleaned and cut at 64."""
    cleaned = _NOT_TOOL.sub("_", str(tool or ""))
    return (PREFIX + slug + "_" + cleaned)[:NAME_CHARS]


def slug_of(name: str) -> str:
    """The slug inside a catalogue name, "" when it is not an own tool."""
    if not isinstance(name, str) or not name.startswith(PREFIX):
        return ""
    rest = name[len(PREFIX):]
    return rest.split("_", 1)[0] if "_" in rest else ""


# --- the snapshot ----------------------------------------------------------

def _reads(tool: str, hint: Any) -> bool:
    """A read only when the server says so AND the name is not a write.

    The server's word alone is not enough: a write verb in the name wins,
    as it does for every other tool on the platform.
    """
    if hint is not True:
        return False
    import agent_tools  # late: agent_tools imports this module
    return not agent_tools.is_write_tool(tool)


def snapshot(slug: str, listed: Any) -> tuple[list[dict], list[str]]:
    """What we keep from a server's ``tools/list`` answer.

    Returns (used, not_used). ``used`` is
    ``[{"name", "tool", "description", "input_schema", "read_only"}]``,
    where ``name`` is the catalogue name and ``tool`` the server's own.
    ``not_used`` is one sentence per tool we left out. Never raises,
    whatever the server sent.
    """
    tools = listed.get("tools") if isinstance(listed, dict) else None
    if not isinstance(tools, list):
        return [], []
    used: list[dict] = []
    not_used: list[str] = []
    seen: set[str] = set()
    for raw in tools:
        if not isinstance(raw, dict):
            continue
        tool = raw.get("name")
        if not isinstance(tool, str) or not tool.strip():
            not_used.append("A tool with no name was left out.")
            continue
        tool = tool.strip()
        if len(used) >= MAX_TOOLS:
            not_used.append(f"{tool}: only the first {MAX_TOOLS} tools are used.")
            continue
        name = tool_name(slug, tool)
        if name in seen:
            not_used.append(f"{tool}: its name is the same as another tool's "
                            f"once cleaned, so it was left out.")
            continue
        schema = raw.get("inputSchema")
        if not isinstance(schema, dict) or not schema:
            schema = dict(EMPTY_SCHEMA)
        try:
            size = len(json.dumps(schema))
        except (TypeError, ValueError):
            not_used.append(f"{tool}: its input could not be read.")
            continue
        if size > SCHEMA_BYTES:
            not_used.append(f"{tool}: its input description is over 8 KB.")
            continue
        description = raw.get("description")
        description = " ".join(description.split()) if isinstance(description, str) else ""
        annotations = raw.get("annotations")
        hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
        seen.add(name)
        used.append({
            "name": name,
            "tool": tool,
            "description": description[:DESC_CHARS],
            "input_schema": schema,
            "read_only": _reads(tool, hint),
        })
    return used, not_used


def catalogue(slug: str, label: str, tools: list[dict]) -> list[dict]:
    """The entries mcp-proxy serves for one server, in the shape its
    describe_tools already returns for built tools, plus ``read_only``."""
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "request_body": {"content": {"application/json": {
                "schema": t.get("input_schema") or dict(EMPTY_SCHEMA)}}},
            "server_id": PREFIX + slug,
            "server_name": label,
            "read_only": bool(t.get("read_only")),
        })
    return out


# --- asking first ----------------------------------------------------------

_READS: "OrderedDict[str, frozenset[str]]" = OrderedDict()


def remember(email: str, tools: list[dict]) -> None:
    """Keep which of this person's own tools are reads, replacing what was
    known. Filled whenever tasks lists their tools."""
    if not email:
        return
    key = email.strip().lower()
    _READS[key] = frozenset(t["name"] for t in tools or []
                            if isinstance(t, dict) and t.get("read_only")
                            and isinstance(t.get("name"), str))
    _READS.move_to_end(key)
    while len(_READS) > REMEMBERED_PEOPLE:
        _READS.popitem(last=False)


def read_only(email: str, name: str) -> bool:
    """True only when this person's server marked this tool a read at the
    last listing. Anything not remembered is a write."""
    if not email or not isinstance(name, str):
        return False
    return name in _READS.get(email.strip().lower(), frozenset())


# --- Jev -------------------------------------------------------------------

def jev_note(servers: list[dict]) -> str:
    """The words added to the gateway's note for a person with own servers.

    "" when there is nothing to add, so everyone else's note is unchanged
    byte for byte.
    """
    parts = []
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        names = [t.get("tool") for t in server.get("tools") or []
                 if isinstance(t, dict) and isinstance(t.get("tool"), str)]
        if not names:
            continue
        shown = ", ".join(names[:JEV_TOOLS])
        if len(names) > JEV_TOOLS:
            shown += ", ..."
        parts.append(f"{server.get('label') or 'their server'} ({shown})")
    if not parts:
        return ""
    return " and their own servers: " + "; ".join(parts)
