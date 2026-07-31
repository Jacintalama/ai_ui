"""Install/refresh the "Remember" tool via the OWUI API.

Run on the server:
  env $(grep -E "^OPENWEBUI_API_KEY=" .env | tr -d "\r") \
    OPENWEBUI_URL=http://127.0.0.1:3000 python3 scripts/insert_memory_tool.py
Reads the tool source from open-webui-functions/memory_tool.py, creates or
updates tool id `remember`, then writes its valves. OWUI computes the function
specs from the content during create/update.
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
                        "open-webui-functions", "memory_tool.py"),
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


body = {"id": "remember", "name": "Remember", "content": src,
        "meta": {"description": "Save lasting facts about the user to their personal memory"},
        "access_control": None}
status, out = call("/api/v1/tools/create", body)
if status != 200:
    status, out = call("/api/v1/tools/id/remember/update", body)
print("tool upsert:", status)
if status != 200:
    sys.exit(f"tool upsert failed: {out}")

status, out = call("/api/v1/tools/id/remember/valves/update",
                   {"tasks_url": "http://tasks:8210", "timeout_seconds": 20})
print("valves:", status)
if status != 200:
    sys.exit(f"valves update failed: {out}")
