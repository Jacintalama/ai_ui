"""Install the ask_colleague tool row in Open WebUI.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py         # show
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py --apply # write

A tool needs BOTH a public.tool row AND generated `specs`, or it is invisible
to every model. Open WebUI generates the specs from the source when the row
is created through its own endpoint, which is why this posts rather than
writing the table directly.
"""
import os
import pathlib
import sys

import requests

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

TOOL_ID = "colleague"
SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / "open-webui-functions" / "colleague_tool.py").read_text()

body = {
    "id": TOOL_ID,
    "name": "Colleague",
    "content": SOURCE,
    "meta": {"description": "Ask one of your colleagues something you "
                            "cannot answer yourself."},
}

head = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
existing = requests.get("%s/api/v1/tools/id/%s" % (BASE, TOOL_ID),
                        headers=head, timeout=30)
print("exists:", existing.status_code == 200)

if "--apply" not in sys.argv:
    print("dry run; pass --apply to write")
    sys.exit(0)

url = ("%s/api/v1/tools/id/%s/update" % (BASE, TOOL_ID)
       if existing.status_code == 200
       else "%s/api/v1/tools/create" % BASE)
r = requests.post(url, headers=head, json=body, timeout=30)
print("wrote:", r.status_code)
r.raise_for_status()

check = requests.get("%s/api/v1/tools/id/%s" % (BASE, TOOL_ID),
                     headers=head, timeout=30).json()
specs = (check.get("specs") or [])
names = [s.get("name") for s in specs]
print("specs:", names)
if "ask_colleague" not in names:
    sys.exit("the row was written but no ask_colleague spec was generated, "
             "so no model can see it")
print("ok")
