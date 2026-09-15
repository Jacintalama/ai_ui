"""Move every agent to the free model. Dry run unless --apply.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py --apply
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py --apply --only agent-ada-a1bc

Needs an admin key: Open WebUI lets an admin update any user's model, and
the agents belong to four people. Prints a before/after table, the path of
the backup it writes before the first change, and any agent it could not
move. Ends by calling /api/models, which rebuilds the model cache that
otherwise answers "Model not found" for a moved agent.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
TARGET = os.environ.get("AGENT_DEFAULT_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

APPLY = "--apply" in sys.argv
if "--only" in sys.argv:
    _at = sys.argv.index("--only") + 1
    if _at >= len(sys.argv):
        sys.exit("--only needs an agent id")
    ONLY = sys.argv[_at]
else:
    ONLY = None

#: The update route this version of Open WebUI actually has. The id rides in
#: the query string; there is no /api/v1/models/id/{id}/update route at all.
#: This is the spelling that already works in
#: mcp-servers/tasks/scripts/create_platform_agents.py.
UPDATE_PATH = "/api/v1/models/model/update?id="

#: /api/v1/models/list pages at 30. The cap only stops a wrong total from
#: spinning forever; 200 pages is 6000 models, far past anything real.
MAX_PAGES = 200

#: The admin key, kept so _scrub can take it back out of anything printed.
_SECRETS = [KEY]


class HttpFailure(Exception):
    """An HTTP call that did not return a usable body."""


def _scrub(text: str, extra=()) -> str:
    """Take secrets, and anything else named, back out of text before printing.

    An error body can echo what we sent, and every request we send carries
    the key in a header. The extra list is how a caller keeps the agent
    owner's own words out of the output: a 422 answers with a detail that
    repeats the body it rejected, and that body carries params.system.
    """
    for secret in list(_SECRETS) + list(extra):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def call(path, payload=None, redact=()):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # The RESPONSE body, never the body we posted.
        detail = e.read().decode("utf-8", "replace")
        raise HttpFailure("HTTP %s %s" % (e.code, _scrub(detail, redact)[:200]))
    except urllib.error.URLError as e:
        raise HttpFailure(_scrub(str(e.reason), redact))
    try:
        return json.loads(body)
    except ValueError:
        raise HttpFailure("reply was not JSON: " + _scrub(body, redact)[:200])


def list_agents():
    """Every agent- model across all pages, and whether the listing is whole.

    Returns (agents, complete). complete is False when the loop stopped
    before it could tell whether every row had been fetched: a page came
    back with no usable total, or the page cap tripped. A caller must not
    read "not in what we got" as "does not exist" while it is False, which
    is the contract agent_runner._list_agents already keeps.

    One function serves both the listing and the verification at the end, so
    the two cannot disagree about where the pages stop. They did when the
    paging condition was written out twice.
    """
    rows, page, complete = [], 1, False
    for _ in range(MAX_PAGES):
        listed = call("/api/v1/models/list?page=%d" % page)
        batch = listed.get("items") or []
        rows.extend(batch)
        total = listed.get("total")
        if not isinstance(total, int):
            # Nothing at all is a whole answer. Some rows and no total to
            # check them against is not.
            complete = not batch
            break
        if not batch or len(rows) >= total:
            complete = len(rows) >= total
            break
        page += 1
    agents = [r for r in rows if str(r.get("id", "")).startswith("agent-")]
    if ONLY:
        agents = [r for r in agents if r["id"] == ONLY]
    return agents, complete


def _instructions(agent) -> str:
    """The agent's instructions as the list endpoint handed them over.

    /api/v1/models/list blanks params for any row the caller cannot write,
    so this can come back empty for an agent that certainly has
    instructions. meta.agent_instructions is not blanked, which is why the
    agents page reads params first and falls back to it; see instructionsOf
    in mcp-servers/tasks/static/agents.html.
    """
    return str((agent.get("params") or {}).get("system") or "")


def _fallback_instructions(agent) -> str:
    """The unblanked copy of the same text, kept beside meta.toolIds."""
    return str((agent.get("meta") or {}).get("agent_instructions") or "")


def _blanked(agent) -> bool:
    """params.system is empty while meta says the agent has instructions.

    An update posts params back as a whole, so writing an empty
    params.system over a real one erases that agent's instructions for its
    owner. An admin key should see every row in full, but this script moves
    every agent across four people in one pass, and "should" is not worth
    an unrecoverable wipe.
    """
    return not _instructions(agent).strip() and bool(_fallback_instructions(agent).strip())


def write_backup(agents) -> str:
    """Record what each agent was before anything is written.

    The instructions text is in here on purpose, even though it is the
    owner's own words and this file is left lying in a working directory.
    An update posts params back wholesale, so if a run ever did go out with
    a blanked params.system this file is the only way to type the
    instructions back in. Treat it as agent contents: keep it off shared
    disks and delete it once the move is verified.

    Mode "x" on purpose. Two runs inside the same second land on the same
    filename, and the second one must not overwrite the first with a
    picture of a tree that has already been changed.
    """
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(os.getcwd(), "agents-before-move-%s.json" % stamp)
    rows = [{"id": a.get("id"), "name": a.get("name"), "user_id": a.get("user_id"),
             "base_model_id": a.get("base_model_id"),
             "params_system": _instructions(a),
             "meta_agent_instructions": _fallback_instructions(a)} for a in agents]
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True)
    return path


def update_body(agent) -> dict:
    # access_grants is ALWAYS sent, and always as a list. The update route
    # revalidates the payload as a ModelForm, where that field defaults to
    # None; omitting it fails validation and comes back as a bare 500. That
    # is measured rather than guessed: it is what made the platform agent
    # rename fail on its first run, recorded in the comment in
    # mcp-servers/tasks/scripts/create_platform_agents.py.
    return {"id": agent["id"], "name": agent.get("name"), "base_model_id": TARGET,
            "meta": agent.get("meta") or {}, "params": agent.get("params") or {},
            "access_grants": agent.get("access_grants") or [],
            "is_active": agent.get("is_active", True)}


def _own_words(agent):
    """The agent's instructions, so an echoed error body cannot print them."""
    return [t for t in (_instructions(agent), _fallback_instructions(agent))
            if t.strip()]


def main() -> int:
    agents, complete = list_agents()
    if not agents and complete:
        print("no agents matched" + ((" --only " + ONLY) if ONLY else ""))
        return 1 if ONLY else 0

    # The instructions column is a character count, never the text. It is
    # here so the operator can see a blanked params.system before applying
    # rather than after.
    print("%-34s %-40s    %-40s %s"
          % ("agent", "base now", "base after", "instructions"))
    for a in agents:
        base = a.get("base_model_id") or ""
        after = TARGET if base != TARGET else "(already)"
        print("%-34s %-40s -> %-40s instructions=%d%s"
              % (a["id"], base, after, len(_instructions(a)),
                 " BLANK" if _blanked(a) else ""))
    if not complete:
        # The table above is a partial picture. Writing from it would move
        # some unknown subset and report a count that means nothing.
        print("listing may be incomplete")
        return 1
    if not APPLY:
        print("dry run; pass --apply to write")
        return 0

    # Only the agents this run would actually post. One already on the
    # target is never written, so a blank on it cannot do harm.
    blanked = sorted(a["id"] for a in agents
                     if a.get("base_model_id") != TARGET and _blanked(a))
    if blanked:
        print("instructions came back blank for:", json.dumps(blanked))
        print("refusing to write: posting that blank back would erase what "
              "those agents were told to do")
        return 1

    print("backup:", write_backup(agents))
    moved, failed = 0, []
    for a in agents:
        if a.get("base_model_id") == TARGET:
            continue
        path = UPDATE_PATH + urllib.parse.quote(str(a["id"]), safe="")
        try:
            call(path, update_body(a), redact=_own_words(a))
        except HttpFailure as exc:
            # Keep going. Stopping half way through leaves the agents split
            # across two models with no record of where the run stopped.
            print("failed:", a["id"], exc)
            failed.append(a["id"])
            continue
        moved += 1
    print("moved:", moved)
    if failed:
        print("could not update:", json.dumps(sorted(failed)))

    call("/api/models")
    checked, complete = list_agents()
    if not complete:
        print("listing may be incomplete")
        return 1
    wrong = {r["id"]: r.get("base_model_id") for r in checked
             if r.get("base_model_id") != TARGET}
    print("verified:", "all on " + TARGET if not wrong
          else "STILL WRONG " + json.dumps(wrong, sort_keys=True))
    return 1 if (failed or wrong) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpFailure as exc:
        print("failed:", exc)
        sys.exit(1)
    except FileExistsError as exc:
        print("backup file already exists, refusing to overwrite:", exc.filename)
        sys.exit(1)
