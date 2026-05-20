"""End-to-end backend smoke for the new schedules + projects endpoints.

Exercises the same TasksClient code path the Discord dispatcher uses.
Run inside the webhook-handler container so httpx is available and the
tasks DNS name resolves.

    docker exec -i webhook-handler python < scripts/e2e_backend_smoke.py
"""
import asyncio
import httpx

EMAIL = "alamajacintg04@gmail.com"
BASE = "http://tasks:8210"


async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        print("=== 1) GET /schedules (list before create) ===")
        r = await c.get(f"{BASE}/schedules", headers={"X-User-Email": EMAIL})
        print(f"  status={r.status_code} body={r.text[:200]}")

        print("\n=== 2) POST /schedules (create) ===")
        r = await c.post(
            f"{BASE}/schedules",
            headers={"X-User-Email": EMAIL},
            json={"name": "e2e-smoke", "cron_expr": "*/5 * * * *", "prompt": "ping"},
        )
        print(f"  status={r.status_code} body={r.text[:200]}")
        sid = r.json().get("id") if r.status_code in (200, 201) else None

        print(f"\n=== 3) GET /schedules (list after create, looking for {sid}) ===")
        r = await c.get(f"{BASE}/schedules", headers={"X-User-Email": EMAIL})
        after = r.json() if r.status_code == 200 else []
        found = any(s.get("id") == sid for s in after)
        print(f"  status={r.status_code} count={len(after)} found_new={found}")

        if sid:
            print(f"\n=== 4) DELETE /schedules/{sid} ===")
            r = await c.delete(
                f"{BASE}/schedules/{sid}", headers={"X-User-Email": EMAIL}
            )
            print(f"  status={r.status_code} body={r.text[:200]}")

        print("\n=== 5) GET /api/projects (list-my-projects, new endpoint) ===")
        r = await c.get(f"{BASE}/api/projects", headers={"X-User-Email": EMAIL})
        print(f"  status={r.status_code} body={r.text[:300]}")

        print("\n=== 6) Sanity: same call WITHOUT X-User-Email should 401 ===")
        r = await c.get(f"{BASE}/api/projects")
        print(f"  status={r.status_code} body={r.text[:200]}")

        print("\n=== 7) GET /api/aiuibuilder/build/<random> (mounted + owner-scoped) ===")
        import uuid as _uuid
        rid = str(_uuid.uuid4())
        r = await c.get(f"{BASE}/api/aiuibuilder/build/{rid}", headers={"X-User-Email": EMAIL})
        print(f"  status={r.status_code} (expect 404 — unknown id)")

        print("\n=== 8) same WITHOUT X-User-Email should 401 ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/build/{rid}")
        print(f"  status={r.status_code} (expect 401)")

        print("\n=== 9) GET /api/aiuibuilder/templates (catalog, user-scoped) ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/templates", headers={"X-User-Email": EMAIL})
        body = r.json() if r.status_code == 200 else []
        keys = [t.get("key") for t in body] if isinstance(body, list) else []
        print(f"  status={r.status_code} count={len(keys)} has_portfolio={'portfolio' in keys} "
              f"excludes_blank={'blank' not in keys}")

        print("\n=== 10) same WITHOUT X-User-Email should 401 ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/templates")
        print(f"  status={r.status_code} (expect 401)")


asyncio.run(main())
