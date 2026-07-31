"""Install/refresh the "Documents" tool via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... INTERNAL_CALLBACK_SECRET=... \
    python3 scripts/insert_documents_tool.py
Reads the tool source from open-webui-functions/documents_tool.py, creates or
updates tool id `documents`, then writes its valves (internal secret comes
from the environment, never from this file). OWUI computes the function specs
from the content during create/update.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

src = open(os.path.join(os.path.dirname(__file__), "..",
                        "open-webui-functions", "documents_tool.py"),
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


body = {"id": "documents", "name": "Documents", "content": src,
        "meta": {"description": "Create Word/PDF files from chat, save to Drive"},
        "access_control": None}
status, out = call("/api/v1/tools/create", body)
if status != 200:
    status, out = call("/api/v1/tools/id/documents/update", body)
print("tool upsert:", status)
if status != 200:
    sys.exit(f"tool upsert failed: {out}")

valves = {"tasks_url": "http://tasks:8210",
          "gdrive_url": "http://mcp-gdrive:8000",
          "internal_secret": SECRET, "timeout_seconds": 60}
status, out = call("/api/v1/tools/id/documents/valves/update", valves)
print("valves:", status)
if status != 200:
    sys.exit(f"valves update failed: {out}")
