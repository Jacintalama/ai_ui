"""Install/refresh the "Schedules" tool via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... python3 scripts/insert_schedules_tool.py

Reads the tool source from open-webui-functions/schedules_tool.py, creates or
updates tool id `schedules`, then writes its valves. OWUI computes the
function specs from the content during create/update, and a tool without
generated specs is invisible to every model.

Note what is missing: there is no operator callback secret here. Every other
insert script in this directory passes one. This tool authenticates with the
caller's own email and must never hold the operator credential, so there is
nothing to pass and no valve to put it in.
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
                        "open-webui-functions", "schedules_tool.py"),
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


body = {"id": "schedules", "name": "Schedules", "content": src,
        "meta": {"description": "See and manage your own scheduled runs"},
        "access_control": None}
status, out = call("/api/v1/tools/create", body)
if status != 200:
    status, out = call("/api/v1/tools/id/schedules/update", body)
print("tool upsert:", status)
if status != 200:
    sys.exit(f"tool upsert failed: {out}")

valves = {"tasks_url": "http://tasks:8210", "timeout_seconds": 30}
status, out = call("/api/v1/tools/id/schedules/valves/update", valves)
print("valves:", status)
if status != 200:
    sys.exit(f"valves update failed: {out}")

print("installed. Every agent reaches it through _every_tool_for, which reads "
      "public.tool, so no per-agent change is needed.")
