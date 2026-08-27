"""Stop the two starter agents being shared, and record who already has theirs.

Scout and Triage were two rows in one person's account carrying a wildcard read
grant, so all nine users saw the same two and only the owner could change them.
They are templates now and every user gets their own copy, so the grants that
made them public have to go.

WHAT THIS MUST NOT DO
---------------------
Base models carry the same kind of wildcard grant, and that is how every user
reaches gpt-4o-mini and the other 130. Deleting those would lock all nine
people out of every model on the platform. Channels carry two more.

Measured on production before this was written:

    wildcard grants on DERIVED models (agents, to remove)  2
    wildcard grants on BASE models (must survive)        131
    wildcard grants on non-model resources (untouched)     2

So this script selects the exact rows first, prints them, refuses to run if the
set does not look like what it expects, deletes by explicit id, and then proves
the other 133 are still there. A sibling script on this repo once came close to
publishing every private agent by trusting an unfiltered WHERE clause, which is
why nothing here is deleted by predicate alone.

Idempotent: a second run finds nothing to do.

Usage, inside the tasks container:
    python3 retire_platform_grants.py --dry-run
    python3 retire_platform_grants.py
"""
import asyncio
import os
import sys

import asyncpg

DERIVED_WILDCARD = """
    SELECT g.id, g.resource_id, m.name
      FROM public.access_grant g
      JOIN public.model m ON m.id = g.resource_id
     WHERE g.principal_id = '*'
       AND g.resource_type = 'model'
       AND m.base_model_id IS NOT NULL
     ORDER BY g.resource_id
"""

COUNT_BASE = """
    SELECT count(*) FROM public.access_grant g
      JOIN public.model m ON m.id = g.resource_id
     WHERE g.principal_id = '*' AND g.resource_type = 'model'
       AND m.base_model_id IS NULL
"""

COUNT_OTHER = """
    SELECT count(*) FROM public.access_grant
     WHERE principal_id = '*' AND resource_type <> 'model'
"""

OWNERS = """
    SELECT DISTINCT u.email
      FROM public.model m
      JOIN public.user u ON u.id = m.user_id
     WHERE m.base_model_id IS NOT NULL
       AND u.email IS NOT NULL
"""


async def main(dry_run: bool) -> int:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        base_before = await conn.fetchval(COUNT_BASE)
        other_before = await conn.fetchval(COUNT_OTHER)
        targets = await conn.fetch(DERIVED_WILDCARD)

        print("before")
        print("  wildcard grants on base models   :", base_before)
        print("  wildcard grants on other things  :", other_before)
        print("  wildcard grants on agents        :", len(targets))
        for t in targets:
            print("     %-34s %s" % (t["resource_id"], t["name"]))

        if base_before == 0:
            print("\nREFUSING: no base model carries a wildcard grant, which "
                  "is not a state this platform has ever been in. Something "
                  "is wrong with the query or the database. Nothing changed.")
            return 2

        if not targets:
            print("\nnothing to retire")
        elif dry_run:
            print("\ndry run, nothing deleted")
        else:
            # By explicit id. A predicate here would be one typo away from
            # taking the 131 base model grants with it.
            ids = [t["id"] for t in targets]
            deleted = await conn.execute(
                "DELETE FROM public.access_grant WHERE id = ANY($1::text[])", ids)
            print("\ndeleted:", deleted)

        owners = [r["email"] for r in await conn.fetch(OWNERS)]
        print("\nusers who already own agents:", owners or "none")
        if owners and not dry_run:
            # So nobody who already has agents is handed a second pair.
            await conn.executemany(
                "INSERT INTO tasks.agent_seed (user_email) VALUES ($1) "
                "ON CONFLICT (user_email) DO NOTHING",
                [(e,) for e in owners])
            print("marked as already seeded:", len(owners))
        elif owners:
            print("dry run, seed records not written")

        base_after = await conn.fetchval(COUNT_BASE)
        other_after = await conn.fetchval(COUNT_OTHER)
        left = len(await conn.fetch(DERIVED_WILDCARD))
        seeded = await conn.fetchval("SELECT count(*) FROM tasks.agent_seed")

        print("\nafter")
        print("  wildcard grants on base models   :", base_after,
              "(unchanged)" if base_after == base_before else "CHANGED, INVESTIGATE")
        print("  wildcard grants on other things  :", other_after,
              "(unchanged)" if other_after == other_before else "CHANGED, INVESTIGATE")
        print("  wildcard grants on agents        :", left)
        print("  rows in tasks.agent_seed         :", seeded)

        if base_after != base_before or other_after != other_before:
            print("\nSOMETHING ELSE MOVED. Every user's access to every base "
                  "model runs through those rows. Check before going further.")
            return 1
        if not dry_run and left:
            print("\nan agent still carries a wildcard grant")
            return 1
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
