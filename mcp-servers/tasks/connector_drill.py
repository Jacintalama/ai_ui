"""Exercise every tool of one connector against a real stored credential.

Why this exists. Two connectors shipped on 2026-11-13, Jira and Dropbox,
and neither has ever been answered by its vendor, because nobody on this
platform has an account on either. Their tests cover the shaping, the
auth and the wiring; what no test can cover is whether the vendor agrees
with the endpoint, the parameter names and the body shape I read off its
documentation. The only thing that settles that is one real call.

So the gap is not knowledge, it is COST: finding out used to mean writing
a throwaway script per provider, which is why it kept not happening. This
turns it into one command, the same command for every provider, and the
same one again the next time a credential lands.

Pure decisions live in this module and the I/O lives in
scripts/connector_drill.py, so the argument filling and the skip
reporting are tested with no network and no database
(tests/test_the_connector_drill.py).

READS ONLY unless asked. A drill that created a task every time somebody
checked a connector would be a connector nobody dares check.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: Where a value for a missing argument comes from: the argument name, then
#: the (tool, field) pairs that carry it, in order of preference.
#:
#: NAMED BY TOOL, not by field alone, and that is the whole lesson of the
#: first live run (2026-11-13, Airtable). The map used to say `base_id`
#: comes from any `id`, so the drill took the id out of `whoami`, which
#: runs first and answers the USER's id, and then reported
#: "Airtable could not find that. NOT_FOUND" for list_tables and
#: list_records. Two endpoints looked broken and both were fine. An id is
#: only an id in the answer it came from.
#:
#: Free text is excluded by construction: an argument this map does not
#: name is never filled, so a comment, a message or an address is reported
#: as missing rather than invented. There is no second deny-list.
FROM_RESULT: Dict[str, Tuple[Tuple[str, str], ...]] = {
    # Airtable
    "base_id": (("list_my_bases", "id"),),
    "table": (("list_tables", "name"), ("list_tables", "id")),
    "record_id": (("list_records", "id"),),
    # Trello
    "board_id": (("list_my_boards", "id"),),
    "list_id": (("list_board_lists", "id"),),
    "card_id": (("list_cards", "id"),),
    # GitHub. `owner` is the one honest use of whoami's own answer.
    "owner": (("whoami", "login"),),
    "repo": (("list_my_repos", "name"),),
    # Notion. Its search returns pages AND databases, so one of these two
    # will sometimes be handed the other kind and the vendor will say so.
    "page_id": (("search", "id"),),
    "database_id": (("search", "id"),),
    # n8n
    "workflow_id": (("list_my_workflows", "id"),),
    # Jira
    "issue_key": (("search_issues", "key"),),
    "project_key": (("list_my_projects", "key"),),
    # Dropbox
    "path": (("list_folder", "path_display"),),
    # ClickUp has 172 tools and most of its ids come from a walk this
    # drill deliberately does not do. They are reported as skipped, which
    # is the honest answer, and -a name=value fills any of them by hand.
    "task_id": (("get_tasks", "id"),),
    "space_id": (("get_spaces", "id"),),
}


# NOTE on what stops the drill inventing free text. There is no deny-list,
# and there was one until I mutated it and found it guarded nothing:
# FROM_RESULT is an ALLOW-LIST, so an argument it does not name is never
# filled, whatever is in the answers already collected. A comment, a
# message or an address is therefore excluded by construction rather than
# by a second rule that could drift out of step with the first. The test
# that covers this asserts the general property, not the old list.


def required(tool) -> List[str]:
    """The argument names this tool cannot be called without."""
    out = []
    for name, spec in (getattr(tool, "args", None) or {}).items():
        if len(spec) > 2 and spec[2]:
            out.append(name)
    return out


def writes(tool) -> bool:
    """Whether this tool changes anything at the vendor.

    Mirrors mytools._writes without importing it, so this module stays
    pure: `writes` on the tool wins, otherwise the method decides.
    """
    flag = getattr(tool, "writes", None)
    if flag is not None:
        return bool(flag)
    return str(getattr(tool, "method", "") or "").upper() != "GET"


def _value_from(items: Any, field: str) -> Optional[Any]:
    """The first usable `field` in one tool's answer.

    An empty value does not count: a vendor that answers {"id": ""} would
    otherwise have the next call made with an empty id and a 404 reported
    as a broken endpoint.
    """
    rows = items if isinstance(items, list) else [items]
    for row in rows:
        if isinstance(row, dict):
            value = row.get(field)
            if value not in (None, "", [], {}):
                return value
    return None


def fill(tool, seen: Dict[str, Any],
         given: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any],
                                                          List[str]]:
    """(arguments, still missing) for one tool.

    `seen` is what earlier tools answered, keyed by tool name. Values
    passed on the command line win over anything found, because the person
    running this knows their own account.
    """
    args: Dict[str, Any] = {}
    missing: List[str] = []
    given = given or {}
    for name in required(tool):
        if name in given:
            args[name] = given[name]
            continue
        found = None
        for tool_name, field in FROM_RESULT.get(name) or ():
            if tool_name in seen:
                found = _value_from(seen[tool_name], field)
                if found is not None:
                    break
        if found is None:
            missing.append(name)
        else:
            args[name] = found
    return args, missing


def order(tools) -> List[Any]:
    """Tools in the order they should be drilled.

    Whoami first, because it is the one that proves the credential and
    names the account. Then the tools that need nothing, because they are
    what the later ones take their ids from. Writes last, and only when
    they were asked for.
    """
    def rank(tool):
        name = getattr(tool, "name", "")
        return (1 if writes(tool) else 0,
                0 if name == "whoami" else 1,
                len(required(tool)),
                name)
    return sorted(tools, key=rank)


def verdict(results: List[dict]) -> dict:
    """What the whole drill proved, in numbers.

    `answered` is the only figure that matters: a vendor answered, which
    is what no test can tell us.
    """
    answered = [r for r in results if r.get("ok")]
    refused = [r for r in results if r.get("error")]
    skipped = [r for r in results if r.get("skipped")]
    return {"tools": len(results), "answered": len(answered),
            "refused": len(refused), "skipped": len(skipped),
            "proved_the_vendor_agrees": bool(answered)}
