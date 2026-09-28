"""Install the ask_colleague tool row in Open WebUI.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py         # show
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py --apply # write

A tool needs BOTH a public.tool row AND generated `specs`, or it is invisible
to every model. Open WebUI generates the specs from the source when the row
is created through its own endpoint, which is why this posts rather than
writing the table directly.
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

TOOL_ID = "colleague"
SOURCE = open(os.path.join(os.path.dirname(__file__), "..",
                           "open-webui-functions", "colleague_tool.py"),
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
existing_status, _ = call(f"/api/v1/tools/id/{TOOL_ID}", method="GET")
endpoint = (f"/api/v1/tools/id/{TOOL_ID}/update" if existing_status == 200
            else "/api/v1/tools/create")

if "--apply" not in sys.argv:
    print("dry run; pass --apply to write")
    sys.exit(0)

status, out = call(endpoint, {
    "id": TOOL_ID, "name": "Colleague", "content": SOURCE,
    "meta": {"description": "Ask one of your colleagues something you "
                            "cannot answer yourself."},
})
print(endpoint, "->", status)
if status != 200 or not out:
    print(json.dumps(out)[:600])
    sys.exit(1)

# The response model omits `specs`, so checking the response would report a
# healthy install as broken. Read the row back instead.
_, rows = call("/api/v1/tools/export", method="GET")
mine = next((r for r in rows if r.get("id") == TOOL_ID), None) if rows else None
specs = (mine or {}).get("specs") or []
names = [s.get("name") for s in specs]
print("functions offered to the model:",
      names or "NONE (the model cannot see it)")
if "ask_colleague" not in names:
    sys.exit("the row was written but no ask_colleague spec was generated, "
             "so no model can see it")
print("ok")
