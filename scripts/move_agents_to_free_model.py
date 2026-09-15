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

#: /api/v1/models/list pages at 30. The cap only stops a wrong total from
#: spinning forever; 200 pages is 6000 models, far past anything real.
MAX_PAGES = 200

#: The admin key, kept so _scrub can take it back out of anything printed.
_SECRETS = [KEY]


class HttpFailure(Exception):
    """An HTTP call that did not return a usable body."""


def _scrub(text: str) -> str:
    """Take the admin key back out of text before it is printed.

    An error body can echo what we sent, and every request we send carries
    the key in a header. Cheap insurance against printing it.
    """
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def call(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise HttpFailure(f"HTTP {e.code} {_scrub(detail)[:200]}")
    except urllib.error.URLError as e:
        raise HttpFailure(str(e.reason))
    try:
        return json.loads(body)
    except ValueError:
        raise HttpFailure(f"reply was not JSON: {_scrub(body)[:200]}")


def list_agents():
    """Every model row whose id starts with agent-, across all pages.

    One function for both the listing and the verification at the end, so
    the two cannot disagree about where the pages stop; they did when the
    paging condition was written out twice.
    """
    rows, page = [], 1
    while page <= MAX_PAGES:
        listed = call(f"/api/v1/models/list?page={page}")
        batch = listed.get("items") or []
        rows.extend(batch)
        total = listed.get("total")
        if not batch or not isinstance(total, int) or len(rows) >= total:
            break
        page += 1
    agents = [r for r in rows if str(r.get("id", "")).startswith("agent-")]
    return [r for r in agents if r["id"] == ONLY] if ONLY else agents


def write_backup(agents) -> str:
    """Record what each agent was on before anything is written.

    Only what is needed to put it back by hand: the id, who owns it and the
    base model. No params, because the system prompt is the person's own
    text and this file is left lying in a working directory.
    """
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(os.getcwd(), f"agents-before-move-{stamp}.json")
    rows = [{"id": a.get("id"), "name": a.get("name"), "user_id": a.get("user_id"),
             "base_model_id": a.get("base_model_id")} for a in agents]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True)
    return path


def update_body(agent) -> dict:
    body = {"id": agent["id"], "name": agent.get("name"), "base_model_id": TARGET,
            "meta": agent.get("meta") or {}, "params": agent.get("params") or {},
            "is_active": agent.get("is_active", True)}
    # Older rows predate access_grants. Sending the field as an empty list
    # when the row does not carry it would look like "share with nobody"
    # rather than "leave sharing alone", so send it only when it is there.
    if "access_grants" in agent:
        body["access_grants"] = agent.get("access_grants") or []
    return body


def main() -> int:
    agents = list_agents()
    if not agents:
        print("no agents matched" + (f" --only {ONLY}" if ONLY else ""))
        return 1 if ONLY else 0

    print("%-34s %-28s -> %s" % ("agent", "base now", "base after"))
    for a in agents:
        base = a.get("base_model_id") or ""
        after = TARGET if base != TARGET else "(already)"
        print("%-34s %-28s -> %s" % (a["id"], base, after))
    if not APPLY:
        print("dry run; pass --apply to write")
        return 0

    print("backup:", write_backup(agents))
    moved, failed = 0, []
    for a in agents:
        if a.get("base_model_id") == TARGET:
            continue
        path = "/api/v1/models/id/%s/update" % urllib.parse.quote(str(a["id"]), safe="")
        try:
            call(path, update_body(a))
        except HttpFailure as exc:
            # Keep going. Stopping half way through leaves the agents split
            # across two models with no record of where the run stopped.
            print("failed:", a["id"], exc)
            failed.append(a["id"])
            continue
        moved += 1
    print("moved:", moved)

    call("/api/models")
    check = {r["id"]: r.get("base_model_id") for r in list_agents()}
    wrong = {k: v for k, v in check.items() if v != TARGET}
    print("verified:", "all on " + TARGET if not wrong
          else "STILL WRONG " + json.dumps(wrong, sort_keys=True))
    if failed:
        print("could not update:", json.dumps(sorted(failed)))
    return 1 if (failed or wrong) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpFailure as exc:
        print("failed:", exc)
        sys.exit(1)
