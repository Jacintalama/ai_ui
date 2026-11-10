"""ClickUp people and columns, the way a person says them (2026-11-10).

ClickUp assigns by numeric user id and moves a task by setting a status that
must be one of its list's statuses. A model knows people by name or email and
columns by what they look like, so on production it sent
`assignees: ['ralphbenitez32@gmail.com']`, and once, asked to assign a task to
"ralph", sent no assignee at all.

This runs before a ClickUp create_task or update_task leaves the service. It
turns a name, an email or an id into the id, and a column as said into the
list's own status, using ClickUp's answers. When it cannot, it says what IS
there, so the next attempt can be right; nothing is written to ClickUp on a
guess.

Pure apart from `prepare`, which is handed a `get(path)` that reads ClickUp as
the person and returns the parsed JSON or None.
"""
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

#: Words people use for the last column, whatever that list calls it.
DONE_WORDS = {"done", "complete", "completed", "finished", "finish", "closed"}

#: How many names a "nobody matches" answer lists.
MAX_NAMED = 10


def members_of(team_payload: Any) -> List[Dict[str, Any]]:
    """Everybody in the person's workspaces, once each, from GET /team."""
    out, seen = [], set()
    teams = (team_payload or {}).get("teams") if isinstance(team_payload, dict) else None
    for team in teams or []:
        for m in (team or {}).get("members") or []:
            u = (m or {}).get("user") or {}
            uid = u.get("id")
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                continue
            if uid in seen:
                continue
            seen.add(uid)
            out.append({"id": uid, "username": str(u.get("username") or ""),
                        "email": str(u.get("email") or "")})
    return out


def _low(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _key(value: Any) -> str:
    """For comparing columns: 'In Progress', 'in-progress' and 'inprogress'
    are one column."""
    return re.sub(r"[\s_\-]+", "", str(value or "").lower())


def _who(members: List[Dict[str, Any]]) -> str:
    names = [m["username"] or m["email"] for m in members if m["username"] or m["email"]]
    more = len(names) - MAX_NAMED
    said = ", ".join(names[:MAX_NAMED])
    return said + (" and %d more" % more if more > 0 else "")


def resolve_person(value: Any, members: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[str]]:
    """(user id, None), or (None, a sentence saying why not)."""
    if isinstance(value, bool):
        return None, "An assignee has to be a person, not %r." % value
    if isinstance(value, int):
        return value, None
    said = str(value or "").strip()
    text = _low(said)
    if not text:
        return None, "One of the assignees was empty."
    if text.isdigit():
        return int(text), None
    for field in ("email", "username"):
        hits = [m for m in members if m[field] and _low(m[field]) == text]
        if len(hits) == 1:
            return hits[0]["id"], None
    hits = [m for m in members
            if _low(m["username"]).split(" ")[:1] == [text]
            or (m["email"] and _low(m["email"]).split("@")[0] == text)]
    if len(hits) == 1:
        return hits[0]["id"], None
    if len(hits) > 1:
        return None, ("More than one person in ClickUp could be %r: %s. Say which one."
                      % (said, _who(hits)))
    if not members:
        return None, ("ClickUp did not list anybody in this workspace, so %r could "
                      "not be found. Use their ClickUp user id." % said)
    return None, ("Nobody in this ClickUp workspace is %r. The people here are: %s."
                  % (said, _who(members)))


def _ids(values: Any, members) -> Tuple[Optional[List[int]], Optional[str]]:
    if values in (None, ""):
        return [], None
    if not isinstance(values, (list, tuple)):
        values = [values]
    out = []
    for v in values:
        uid, problem = resolve_person(v, members)
        if problem:
            return None, problem
        if uid not in out:
            out.append(uid)
    return out, None


def resolve_assignees(value: Any, members, for_update: bool):
    """create_task takes a list of ids. update_task takes {"add": [...],
    "rem": [...]}, and ClickUp's reference marks both keys required, so a
    missing one is sent empty rather than letting the call fail."""
    if not for_update:
        return _ids(value, members)
    if not isinstance(value, dict):
        value = {"add": value}
    out = {}
    for half in ("add", "rem"):
        ids, problem = _ids(value.get(half), members)
        if problem:
            return None, problem
        out[half] = ids
    return out, None


def needs_lookup(value: Any) -> bool:
    """Whether any assignee is something other than an id."""
    if isinstance(value, dict):
        return any(needs_lookup(v) for v in value.values())
    if not isinstance(value, (list, tuple)):
        value = [value]
    for v in value:
        if isinstance(v, bool):
            return True
        if isinstance(v, int):
            continue
        if not str(v or "").strip().isdigit():
            return True
    return False


def resolve_status(value: Any, statuses: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """(the list's own status, None), or (None, the columns it does have).

    Columns that could not be read leave the value as given: ClickUp then
    decides, and its reason now reaches the model."""
    names = [str(s.get("status")) for s in statuses or [] if s and s.get("status")]
    if not names:
        return value, None
    want = _key(value)
    for n in names:
        if _key(n) == want:
            return n, None
    if _low(value) in DONE_WORDS:
        closed = [str(s.get("status")) for s in statuses
                  if s and s.get("status") and s.get("type") in ("closed", "done")]
        if len(closed) == 1:
            return closed[0], None
    return None, ("That list has no column called %r. Its columns are: %s."
                  % (str(value), ", ".join(names)))


Get = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]


def needs_list_lookup(value: Any) -> bool:
    """True when a list_id is a name rather than an id.

    ClickUp's ids are digits and a person says "Project 1", so the shape
    of the value is the whole test, the same way needs_lookup reads an
    assignee. Blank is not a name: there is nothing to look up and a
    walk would return every list in the account as a suggestion.
    """
    if isinstance(value, bool):
        return False
    text = str(value if value is not None else "").strip()
    return bool(text) and not text.isdigit()


async def prepare(tool_name: str, args: Dict[str, Any], get: Get) -> Tuple[Dict[str, Any], Optional[str]]:
    """The arguments ClickUp should receive, or a reason to send nothing.

    Reads only what it needs: the list when its name was given instead of
    its id, the workspace members when an assignee is not already an id,
    and the list's statuses when a status is given."""
    args = dict(args or {})

    # A list named rather than numbered, for ANY tool that takes one.
    # On the argument and not on create_task, because "show me the tasks
    # in Project 1" is the same dead end as creating one, and because a
    # per-tool list would go stale against 174 generated tools.
    #
    # First, so the status lookup below reads /list/<the real id> rather
    # than /list/Project 1, finds the columns, and stops sending the
    # person's own word for ClickUp to refuse.
    if needs_list_lookup(args.get("list_id")):
        import clickup_find
        value, problem = await clickup_find.resolve_list(args["list_id"], get)
        if problem:
            return args, problem
        args["list_id"] = value

    if tool_name not in ("create_task", "update_task"):
        return args, None
    for_update = tool_name == "update_task"

    assignees = args.get("assignees")
    if assignees not in (None, "", [], {}):
        members: List[Dict[str, Any]] = []
        if needs_lookup(assignees):
            members = members_of(await get("/team", None))
        value, problem = resolve_assignees(assignees, members, for_update)
        if problem:
            return args, problem
        args["assignees"] = value

    status = args.get("status")
    if status not in (None, ""):
        list_id = args.get("list_id")
        if for_update:
            params = None
            if args.get("custom_task_ids"):
                params = {"custom_task_ids": "true", "team_id": args.get("team_id")}
            task = await get("/task/" + str(args.get("task_id") or ""), params)
            list_id = ((task or {}).get("list") or {}).get("id") if isinstance(task, dict) else None
        statuses = []
        if list_id:
            got = await get("/list/" + str(list_id), None)
            statuses = (got or {}).get("statuses") or [] if isinstance(got, dict) else []
        value, problem = resolve_status(status, statuses)
        if problem:
            return args, problem
        args["status"] = value

    return args, None
