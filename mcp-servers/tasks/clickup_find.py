"""Turn a list name into a ClickUp list id, in one tool call.

Why this is not just another generated tool
-------------------------------------------
Every ClickUp write needs an id, and ClickUp's API has no endpoint that
takes a name. The only route is to climb the tree: GET /team, then
/team/{id}/space, then /space/{id}/folder, then /folder/{id}/list. Each
rung is a separate round of the chat's tool loop, which is why "create a
task in Project 1" ended in "Stopped after 7 rounds of tool use" having
done nothing. Five of those seven rounds were spent finding out where to
put the task.

Measured against the connected account on 2026-11-10, the ladder was
worse than slow, it was a dead end: that workspace has three spaces and
NO folders, and "Project 1" is a folderless list. So `get_folders`
answers with an empty array for every space, and `get_lists` has no
folder id to ask about. The lists only exist behind /space/{id}/list, a
branch nothing in the tool's own description pointed at.

The whole walk of that account is eight HTTP calls. Eight HTTP calls take
about a second and cost nothing; one round of a model's tool loop costs a
whole turn. That is the trade this module makes, deliberately.

It does no I/O itself. `find_list` takes a `get` callable, so the walk
is tested against the real shape of a real workspace with no vendor, no
credential and no network.

Not cached, on purpose. A list somebody created a minute ago is exactly
the one they are about to ask for by name, and a cache that misses it
sends them hunting for a list the platform can see in ClickUp's own UI
and claims not to find.
"""
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("tasks.clickup_find")

#: How close a name is, lowest first. Only the best tier found is
#: returned: mixing them is what answers an exact "Project 1" with
#: "Project 10" alongside it and puts the choice back on the model.
EXACT, PREFIX, CONTAINS, WORDS = 0, 1, 2, 3

#: A match on the containing folder or space, ranked after every match on
#: a list's own name. Somebody who says "in Marketing", where Marketing
#: is a folder, means a list inside it, because a task cannot live in a
#: folder. But a LIST called Marketing is what they meant first.
_VIA_FOLDER = 10
_VIA_SPACE = 20

#: Hard ceiling on vendor requests for one search. A workspace with
#: hundreds of spaces must not turn one question into hundreds of
#: requests against the person's own rate limit.
MAX_CALLS = 40

#: Most workspaces walked when the caller named none.
MAX_WORKSPACES = 5

#: Most rows returned. Mirrors mytools.MAX_ITEMS, declared here because
#: mytools imports this module and the reverse would be a cycle.
MAX_ITEMS = 25

#: Names reported when nothing matched, so "I could not find it" arrives
#: with the answer to the obvious next question.
MAX_AVAILABLE = 40

Getter = Callable[..., Awaitable[Any]]


def normalise(text: Any) -> str:
    """A name as somebody typed it, compared the way they meant it."""
    return " ".join(str(text or "").split()).casefold()


def tier(asked: Any, name: Any) -> Optional[int]:
    """How close `name` is to what was asked, or None for no match."""
    a, n = normalise(asked), normalise(name)
    if not a or not n:
        return None
    if a == n:
        return EXACT
    if n.startswith(a):
        return PREFIX
    if a in n:
        return CONTAINS
    words = a.split()
    if len(words) > 1 and all(w in n for w in words):
        return WORDS
    return None


def best(rows: List[Dict]) -> List[Dict]:
    """Only the closest matches, dropping every weaker tier."""
    scored = [r for r in rows if r.get("tier") is not None]
    if not scored:
        return []
    top = min(r["tier"] for r in scored)
    return [r for r in scored if r["tier"] == top]


class _Walk:
    """The tree read once, with the request count held down."""

    def __init__(self, get: Getter) -> None:
        self._get = get
        self.calls = 0
        self.truncated = False

    async def rows(self, path: str, key: str,
                   fatal: bool = False) -> List[Dict]:
        """One collection from ClickUp.

        `fatal` is for the first call only, the one that stands in for
        "is this credential any good". After that a part of the tree that
        cannot be read is skipped: a private space answers 401 for
        itself, and failing the whole search would make this useless on
        any workspace with one locked space in it.
        """
        if self.calls >= MAX_CALLS:
            self.truncated = True
            return []
        self.calls += 1
        if fatal:
            payload = await self._get(path)
        else:
            try:
                payload = await self._get(path)
            except Exception:                               # noqa: BLE001
                logger.info("clickup_find: skipped %s", path)
                return []
        rows = (payload or {}).get(key)
        return [r for r in rows if isinstance(r, dict)] \
            if isinstance(rows, list) else []


def _row(entry: Dict, folder: Optional[Dict], space: Dict, workspace: Dict,
         asked: str, folder_tier: Optional[int],
         space_tier: Optional[int]) -> Dict:
    """One list, with how it matched and where it lives."""
    own = tier(asked, entry.get("name"))
    if own is not None:
        rank, via = own, "list"
    elif folder_tier is not None:
        rank, via = _VIA_FOLDER + folder_tier, "folder"
    elif space_tier is not None:
        rank, via = _VIA_SPACE + space_tier, "space"
    else:
        rank, via = None, ""
    folder_name = str((folder or {}).get("name") or "") or None
    parts = [p for p in (workspace.get("name"), space.get("name"),
                         folder_name, entry.get("name")) if p]
    return {
        # `list_id`, not `id`: create_task's required argument is
        # list_id, so the model copies it across rather than translating
        # it, and a model that translates an id sometimes gets it wrong.
        "list_id": str(entry.get("id") or ""),
        "name": entry.get("name"),
        "space": space.get("name"),
        "space_id": str(space.get("id") or ""),
        "folder": folder_name,
        "path": " > ".join(str(p) for p in parts),
        "task_count": entry.get("task_count"),
        "matched_via": via,
        "tier": rank,
    }


async def find_list(get: Getter, args: Optional[Dict[str, Any]] = None) -> Dict:
    """Find the ClickUp lists whose name is the one somebody said.

    `get(path)` returns ClickUp's parsed JSON for one GET, and raises
    when the credential itself is refused.
    """
    args = args or {}
    asked = str(args.get("name") or "").strip()
    if not asked:
        return {"ok": False,
                "error": "Say which name to look for, as it appears in "
                         "ClickUp, like 'Project 1'."}
    workspace_id = str(args.get("workspace_id") or "").strip()

    walk = _Walk(get)
    if workspace_id:
        workspaces: List[Dict] = [{"id": workspace_id}]
    else:
        workspaces = await walk.rows("/team", "teams", fatal=True)

    rows: List[Dict] = []
    available: List[str] = []
    seen = set()

    for n, workspace in enumerate(workspaces[:MAX_WORKSPACES]):
        team_id = str(workspace.get("id") or "")
        if not team_id or walk.truncated:
            continue
        spaces = await walk.rows("/team/%s/space" % team_id, "spaces",
                                 fatal=bool(workspace_id) and n == 0)
        for space in spaces:
            if walk.truncated:
                break
            space_id = str(space.get("id") or "")
            if not space_id:
                continue
            space_tier = tier(asked, space.get("name"))

            for folder in await walk.rows("/space/%s/folder" % space_id,
                                          "folders"):
                folder_id = str(folder.get("id") or "")
                folder_tier = tier(asked, folder.get("name"))
                # ClickUp's Get Folders embeds each folder's lists.
                # Asking again is one request per folder for rows already
                # in hand, but not every response carries them.
                inner = folder.get("lists")
                if not isinstance(inner, list) or not inner:
                    inner = await walk.rows("/folder/%s/list" % folder_id,
                                            "lists") if folder_id else []
                for entry in inner:
                    if not isinstance(entry, dict):
                        continue
                    rows.append(_row(entry, folder, space, workspace, asked,
                                     folder_tier, space_tier))

            for entry in await walk.rows("/space/%s/list" % space_id, "lists"):
                rows.append(_row(entry, None, space, workspace, asked,
                                 None, space_tier))

    for row in rows:
        name = row.get("name")
        if name and name not in seen:
            seen.add(name)
            available.append(str(name))

    matches = best(rows)
    out: Dict[str, Any] = {
        "ok": True,
        "count": len(matches),
        "items": [{k: v for k, v in m.items() if k != "tier"}
                  for m in matches[:MAX_ITEMS]],
        "truncated": walk.truncated or len(matches) > MAX_ITEMS,
    }
    if not matches:
        out["available"] = available[:MAX_AVAILABLE]
        out["note"] = ("No list, folder or space is called that. The names "
                       "above are what this account actually has.")
    return out


async def resolve_list(name: Any, get: Getter):
    """One list id for a name, or a sentence saying why there isn't one.

    This is the half that gets used. Measured on the box the day
    find_list shipped: it is ranked FIRST for "which ClickUp list is
    Project 1", and nowhere in the top eight for "create a task in
    Project 1", because tool search matches the person's own words and
    their words are "create a task". So the lookup also has to live
    where the model already lands, which is the argument of the call it
    did find.

    Returns (list_id, None) or (None, sentence). Never guesses between
    two lists of the same name: putting a task somewhere nobody named is
    not discovered until somebody goes looking for it.
    """
    found = await find_list(get, {"name": name})
    if not found.get("ok"):
        return None, found.get("error") or "That list could not be looked up."
    items = found.get("items") or []
    if len(items) == 1:
        return items[0]["list_id"], None
    if not items:
        names = ", ".join(found.get("available") or [])
        return None, ("There is no list called %r. The lists in this "
                      "account are: %s." % (str(name), names or "none I can see"))
    where = "; ".join(i.get("path") or str(i.get("name")) for i in items)
    return None, ("More than one of those matches %r: %s. Which one?"
                  % (str(name), where))
