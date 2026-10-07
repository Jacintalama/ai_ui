"""Give an owner's agents the tool that lets them ask each other.

`scripts/install_colleague_tool.py` installs the tool row and its grant, and
says plainly that the third step "is a person's decision and not this
script's":

    3. The ATTACH, which is a person's decision and not this script's: add
       `colleague` to an agent's meta.toolIds.

This is that step. It exists because leaving it undone looks exactly like a
working install: measured on prod 2026-10-07, the row was present with
generated specs and granted to `*`, and still only one agent out of twelve on
the whole platform could ask anybody anything. `tasks.agent_step` had two
handoff rows in its entire history.

Run it on the server, inside the tasks container, which already has
DATABASE_URL:

    docker cp scripts/attach_colleague_to_agents.py tasks:/tmp/ac.py
    docker exec tasks python /tmp/ac.py --owner you@example.com
    docker exec tasks python /tmp/ac.py --owner you@example.com --apply

Without `--apply` it only prints what it would do.

Idempotent: an agent that already has the tool is left alone. Only
`meta.toolIds` is touched, and the rest of `meta` survives because the whole
object is read, edited and written back.

### This does not let an agent act for another

`agent_access` narrows the colleague surface: at an `access` level of `ask`
or `read`, an agent asked by another agent is forced read-only, and only
`all` may act. So the worst case here is that an agent answers a question it
was asked. Handoffs are capped at depth 2 and two per turn, so the cost of
granting this stays bounded.
"""
import argparse
import asyncio
import json
import os
import time

import asyncpg

TOOL = "colleague"


async def attach(owner: str, apply: bool) -> int:
    """Add TOOL to each of `owner`'s agents. Returns how many changed."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Run this inside the tasks "
                         "container, which already has it.")
    conn = await asyncpg.connect(url)
    try:
        # text on this box, but jsonb elsewhere is plausible and the cast has
        # to match or the write fails with a type error rather than silently.
        meta_type = await conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'model' AND column_name = 'meta'")

        user = await conn.fetchrow(
            "SELECT id FROM public.user WHERE email = $1", owner)
        if not user:
            raise SystemExit("no such owner: %s" % owner)

        rows = await conn.fetch(
            "SELECT id, name, meta FROM public.model "
            "WHERE id LIKE 'agent-%' AND user_id = $1 ORDER BY name", user["id"])
        print("agents owned by %s: %d" % (owner, len(rows)))

        cast = {"jsonb": "$1::jsonb", "json": "$1::json"}.get(meta_type, "$1")
        changed = 0
        for row in rows:
            meta = row["meta"]
            meta = json.loads(meta) if isinstance(meta, str) else dict(meta or {})
            tools = list(meta.get("toolIds") or [])
            if TOOL in tools:
                print("  %-10s already has it" % (row["name"] or row["id"]))
                continue

            tools.append(TOOL)
            meta["toolIds"] = tools
            changed += 1
            print("  %-10s -> %s" % (row["name"] or row["id"], ",".join(tools)))
            if apply:
                await conn.execute(
                    "UPDATE public.model SET meta = %s, updated_at = $2 "
                    "WHERE id = $3" % cast,
                    json.dumps(meta), int(time.time()), row["id"])

        print(("applied to %d" if apply else "would change %d (dry run)") % changed)
        return changed
    finally:
        await conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--owner", required=True, help="the owner's email address")
    p.add_argument("--apply", action="store_true",
                   help="write the change; without it, only print")
    a = p.parse_args()
    asyncio.run(attach(a.owner, a.apply))


if __name__ == "__main__":
    main()
