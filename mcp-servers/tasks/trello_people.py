"""Trello people, the way a person says them (2026-11-11).

Trello puts somebody on a card by 24-character member id. A model knows
people by name, so "assign that card to Clarenz" had nothing it could send,
and the per-user Trello tools had no assign tool at all: the shared
connector was the only way, which meant acting as somebody else's account.

This runs before a per-user Trello call leaves the service and turns a name,
a username or an id into the id, using Trello's own answers. When it cannot,
it says who IS on the board, so the next attempt can be right. Nothing is
written to Trello on a guess.

The same shape as `clickup_people`, deliberately, with two differences that
Trello forces:

  - A member id is 24 hex characters, so the SHAPE of the value decides
    whether to look it up, the way `needs_list_lookup` reads a ClickUp list.
    There is no cheap "is this an id" test on a name.
  - A card knows its board but a card id is not a board id, so resolving a
    name costs two reads: the card, then that board's members.

It also fills in the constants for `archive_card` and `complete_card`.
Trello takes those as query parameters rather than a JSON body, and `query`
maps a parameter to an ARGUMENT, so a constant has nowhere else to live.
Putting it here keeps `_call`, which all eight providers share, untouched.

Pure apart from `prepare`, which is handed a `get(path)` that reads Trello as
the person and returns the parsed JSON or None.
"""
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

#: How many names a "nobody matches" answer lists.
MAX_NAMED = 10

#: A Trello object id: 24 lowercase hex characters.
_ID = re.compile(r"^[0-9a-f]{24}$")


def members_of(payload: Any) -> List[Dict[str, Any]]:
    """Everybody on a board, once each, from GET /boards/{id}/members.

    Trello answers with a flat list and no envelope, unlike ClickUp's
    {"teams": [{"members": [{"user": {...}}]}]}.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    rows = payload if isinstance(payload, list) else []
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid,
                    "username": str(m.get("username") or ""),
                    "fullName": str(m.get("fullName") or "")})
    return out


def _low(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def needs_lookup(value: Any) -> bool:
    """True when a member is named rather than identified.

    Blank is not a name: there is nothing to look up, and a walk would
    return the whole board as a suggestion for a value nobody gave.
    """
    if isinstance(value, bool):
        return False
    text = str(value if value is not None else "").strip()
    return bool(text) and not _ID.match(text.lower())


def _who(members: List[Dict[str, Any]]) -> str:
    names = [m["username"] or m["fullName"] for m in members
             if m["username"] or m["fullName"]]
    more = len(names) - MAX_NAMED
    said = ", ".join(names[:MAX_NAMED])
    return said + (" and %d more" % more if more > 0 else "")


def _ambiguous(said: str, hits: List[Dict[str, Any]]) -> str:
    return ("More than one person on this Trello board could be %r: %s. "
            "Say which one, by username." % (said, _who(hits)))


def resolve_person(
    value: Any, members: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """(member id, None), or (None, a sentence saying why not)."""
    if isinstance(value, bool):
        return None, "A member has to be a person, not %r." % value
    said = str(value or "").strip()
    if not said:
        return None, "No Trello member was given."
    if _ID.match(said.lower()):
        return said, None

    text = _low(said)
    for field in ("username", "fullName"):
        hits = [m for m in members if m[field] and _low(m[field]) == text]
        if len(hits) == 1:
            return hits[0]["id"], None
        if len(hits) > 1:
            return None, _ambiguous(said, hits)

    #: A first name, which is how people are usually named out loud. The
    #: HS RESEARCH TEAM board has two accounts both called "Lukas Herajt",
    #: so this genuinely has to refuse rather than pick.
    hits = [m for m in members
            if _low(m["fullName"]).split(" ")[:1] == [text]]
    if len(hits) == 1:
        return hits[0]["id"], None
    if len(hits) > 1:
        return None, _ambiguous(said, hits)

    if not members:
        return None, ("Trello did not list anybody on this board, so %r "
                      "could not be found. Use their Trello member id."
                      % said)
    return None, ("Nobody on this Trello board is %r. The people here are: "
                  "%s." % (said, _who(members)))


Get = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]

#: Tools whose whole job is to set one flag, and the flag they set.
#: `query` maps a parameter to an argument, so a constant needs somewhere
#: to be written, and this is it.
FLAGS = {"archive_card": ("closed", "true"),
         "complete_card": ("dueComplete", "true")}

#: Tools that take a member and therefore may need a lookup.
TAKES_MEMBER = ("assign_member_to_card", "remove_member_from_card")


async def prepare(
    tool_name: str, args: Dict[str, Any], get: Get,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """The arguments Trello should receive, or a reason to send nothing.

    Reads only what it needs: nothing at all unless a member was named
    rather than identified, and then the card (for its board) and that
    board's members.
    """
    args = dict(args or {})

    flag = FLAGS.get(tool_name)
    if flag:
        args[flag[0]] = flag[1]
        return args, None

    if tool_name not in TAKES_MEMBER:
        return args, None

    member = args.get("member")
    if member in (None, "") or not needs_lookup(member):
        return args, None

    members: List[Dict[str, Any]] = []
    card = await get("/cards/" + str(args.get("card_id") or ""), None)
    board = (card or {}).get("idBoard") if isinstance(card, dict) else None
    if board:
        members = members_of(
            await get("/boards/" + str(board) + "/members", None))

    who, problem = resolve_person(member, members)
    if problem:
        return args, problem
    args["member"] = who
    return args, None
