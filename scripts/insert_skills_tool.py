"""Install/refresh the "Skills" tool via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... python3 scripts/insert_skills_tool.py

Reads the tool source from open-webui-functions/skills_tool.py, creates or
updates tool id `skills`, then writes its valves. OWUI computes the function
specs from the content during create/update, and a tool without generated
specs is invisible to every model.

Why this tool exists, measured on 2026-09-10: 64 skills, 37,990 characters of
instructions between them, and an agent's brief can carry about 8,000. So an
agent holds roughly 13 and the other 51 are unreachable unless somebody
predicted in advance which would be needed. This makes all 64 reachable for
the cost of one sentence in the brief.

No operator secret here, as with the schedules tool: it authenticates with
the caller's own email and must never hold the operator credential.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

src = open(os.path.join(os.path.dirname(__file__), "..",
                        "open-webui-functions", "skills_tool.py"),
           encoding="utf-8").read()


def call(path, payload=None, method="POST"):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


# /api/v1/tools/create returns 200 with a null body when the id is taken, so
# pick the endpoint from what is already there rather than from the response.
# Keying on the status alone made every re-install a silent no-op once.
existing_status, _ = call("/api/v1/tools/id/skills", method="GET")
endpoint = ("/api/v1/tools/id/skills/update" if existing_status == 200
            else "/api/v1/tools/create")

body = {"id": "skills", "name": "Skills", "content": src,
        "meta": {"description": "Find the right ready-made procedure for a "
                                "job and follow it"},
        "access_control": None}
status, out = call(endpoint, body)
print("tool", "update" if endpoint.endswith("update") else "create", "->", status)
if status != 200 or not out:
    sys.exit(f"tool upsert failed: {out}")

valves = {"tasks_url": "http://tasks:8210", "timeout_seconds": 20}
status, out = call("/api/v1/tools/id/skills/valves/update", valves)
print("valves:", status)
if status != 200:
    sys.exit(f"valves update failed: {out}")

print("installed. Every agent reaches it through _every_tool_for, which reads "
      "public.tool, so no per-agent change is needed.")
