# -*- coding: utf-8 -*-
"""What node shapes does THIS n8n actually write.

The changelog says what the latest n8n supports. It does not say what
Ralph's instance accepts, and a typeVersion his n8n does not know makes
a node that loads broken in the editor. His own workflows, built by his
own n8n's UI, are the only authority on that.

Read only. Touches nothing.
"""
import asyncio
import collections

import httpx

import connections as C
from routes_connections import secrets_for

EMAIL = "ralphbenitez32@gmail.com"


async def main():
    v = await secrets_for(EMAIL, "n8n")
    a = C.vendor_auth("n8n", v)
    base = a.base_url.rstrip("/")

    seen = collections.defaultdict(set)
    counts = collections.Counter()
    params = {}

    async with httpx.AsyncClient(timeout=40) as hx:
        cursor, pages = None, 0
        while pages < 10:
            q = {"limit": 100}
            if cursor:
                q["cursor"] = cursor
            r = await hx.get(base + "/api/v1/workflows", params=q,
                             headers=dict(a.headers))
            if r.status_code != 200:
                print("list ->", r.status_code)
                return
            body = r.json() or {}
            for w in body.get("data") or []:
                for n in w.get("nodes") or []:
                    t = n.get("type") or "?"
                    seen[t].add(n.get("typeVersion"))
                    counts[t] += 1
                    # Keep one real example of each node's parameters, so
                    # the shape comes from his n8n rather than from memory.
                    if t not in params and n.get("parameters"):
                        params[t] = n["parameters"]
            cursor = body.get("nextCursor")
            pages += 1
            if not cursor:
                break

    print("nodes in use, most used first\n")
    print("%-44s %5s  %s" % ("type", "uses", "typeVersions"))
    for t, c in counts.most_common():
        vers = sorted(x for x in seen[t] if x is not None)
        print("%-44s %5d  %s" % (t.replace("n8n-nodes-base.", ""), c,
                                 ", ".join(str(x) for x in vers)))


asyncio.run(main())
