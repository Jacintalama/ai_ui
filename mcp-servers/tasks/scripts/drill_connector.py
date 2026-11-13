"""Ask a vendor whether we read its documentation right.

    docker exec -i -e PYTHONPATH=/app -w /app tasks \
        python scripts/drill_connector.py jira [--email you@example.com]

NAMED drill_connector, not connector_drill, and that matters: Python puts
a script's OWN directory first on sys.path, so a script called
connector_drill.py imports ITSELF when it asks for the module of that
name, whatever it then inserts on the path. Measured on the box
2026-11-13: "module 'connector_drill' has no attribute 'order'", after the
script was already inside a running container. There is a test for it now,
test_a_script_never_shadows_a_module.

Runs every READ tool of one connector against that person's own stored
credential, feeding each answer's ids into the tools that need them, and
prints what came back. Nothing is written unless `--writes` is passed, and
then only after it says what it is about to do.

This is the one thing a test cannot do. The suites cover the shaping, the
auth and the wiring against fakes; whether the vendor agrees with the
endpoints, the parameter names and the body shapes is settled by one real
call. Jira and Dropbox both shipped on 2026-11-13 with that question open,
because nobody here has an account on either.

Decisions live in connector_drill.py, which is pure and tested. This file
only talks.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import connector_drill as D                                 # noqa: E402
import mytools                                              # noqa: E402

DEFAULT_EMAIL = os.environ.get("DRILL_EMAIL", "ralphbenitez32@gmail.com")


def _short(value, width=300):
    text = json.dumps(value, default=str)
    return text if len(text) <= width else text[:width] + "..."


async def drill(provider: str, email: str, allow_writes: bool,
                given: dict) -> dict:
    tools = mytools.PROVIDER_TOOLS.get(provider)
    if not tools:
        print("No such connector: %s" % provider)
        print("Have: %s" % ", ".join(sorted(mytools.PROVIDER_TOOLS)))
        return {}

    print("=" * 72)
    print("  %s, as %s" % (provider, email))
    print("=" * 72)

    seen, results = {}, []
    for tool in D.order(tools):
        if D.writes(tool) and not allow_writes:
            results.append({"tool": tool.name, "skipped": "it writes"})
            print("  -  %-22s skipped: it writes, and --writes was not given"
                  % tool.name)
            continue
        args, missing = D.fill(tool, seen, given)
        if missing:
            results.append({"tool": tool.name,
                            "skipped": ",".join(missing)})
            print("  -  %-22s skipped: nothing answered %s"
                  % (tool.name, ", ".join(missing)))
            continue
        if D.writes(tool):
            print("  !  %-22s WRITES, with %s" % (tool.name, _short(args, 120)))
        out = await mytools._call(provider, tool, email, args)
        if not out.get("ok"):
            results.append({"tool": tool.name, "error": out.get("error")})
            print("  X  %-22s %s" % (tool.name, out.get("error")))
            continue
        payload = out.get("items", out.get("item"))
        seen[tool.name] = payload
        count = out.get("count")
        results.append({"tool": tool.name, "ok": True, "count": count})
        print("  OK %-22s %s%s"
              % (tool.name,
                 ("%d row(s): " % count) if count is not None else "",
                 _short(payload)))

    v = D.verdict(results)
    print("-" * 72)
    print("  %d tools: %d answered, %d refused, %d skipped"
          % (v["tools"], v["answered"], v["refused"], v["skipped"]))
    print("  the vendor agreed with at least one endpoint: %s"
          % v["proved_the_vendor_agrees"])
    if not v["proved_the_vendor_agrees"]:
        print("  so this run proves NOTHING about the endpoints. Connect the "
              "account, or pass the ids by hand with -a name=value.")
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("provider", help="e.g. jira, dropbox, airtable")
    ap.add_argument("--email", default=DEFAULT_EMAIL,
                    help="whose stored credential to use")
    ap.add_argument("--writes", action="store_true",
                    help="also run the tools that CHANGE something")
    ap.add_argument("-a", "--arg", action="append", default=[],
                    metavar="name=value",
                    help="supply an argument the drill cannot find")
    ns = ap.parse_args()
    given = {}
    for pair in ns.arg:
        if "=" in pair:
            name, value = pair.split("=", 1)
            given[name.strip()] = value.strip()
    asyncio.run(drill(ns.provider, ns.email, ns.writes, given))


if __name__ == "__main__":
    main()
