#!/usr/bin/env python3
"""Install/refresh any OWUI tool from open-webui-functions/, via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... python3 scripts/insert_owui_tool.py \
      agents agents_tool.py "Ask Your Agents" "Reach your agents by name."

The per-tool scripts beside this one (insert_documents_tool.py,
insert_gmail_tool.py, ...) are the same twenty lines with three strings
changed. This is those strings as arguments, for tools that need no valve
writing of their own.

Why the API and not an INSERT: creating the row is the smallest part of what
/api/v1/tools/create does. It also rewrites imports, loads the module to read
its frontmatter, records whether it has UserValves, makes the tool's cache
directory, and generates `specs` -- the JSON description of the tool's
functions. `specs` is the only part of the row a model ever sees, so a
hand-written INSERT yields a tool that exists and is invisible.
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
if len(sys.argv) != 5:
    sys.exit("usage: insert_owui_tool.py <id> <source-filename> <name> "
             "<description>")

tool_id, filename, name, description = sys.argv[1:5]

src = open(os.path.join(os.path.dirname(__file__), "..",
                        "open-webui-functions", filename),
           encoding="utf-8").read()


def call(path, payload=None, method="POST"):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or "{}")


# /create returns null rather than failing when the id is taken, so pick the
# endpoint by what is already there instead of by the response.
existing_status, _ = call(f"/api/v1/tools/id/{tool_id}", method="GET")
endpoint = (f"/api/v1/tools/id/{tool_id}/update" if existing_status == 200
            else "/api/v1/tools/create")

status, out = call(endpoint, {
    "id": tool_id, "name": name, "content": src,
    "meta": {"description": description},
})
print(endpoint, "->", status)
if status != 200 or not out:
    print(json.dumps(out)[:600])
    sys.exit(1)

# The response model omits `specs`, so checking the response would report a
# healthy install as broken. Read the row back instead.
_, rows = call("/api/v1/tools/export", method="GET")
mine = next((r for r in rows if r.get("id") == tool_id), None) if rows else None
specs = (mine or {}).get("specs") or []
print("functions offered to the model:",
      [s.get("name") for s in specs] or "NONE (the model cannot see it)")
sys.exit(0 if specs else 1)
