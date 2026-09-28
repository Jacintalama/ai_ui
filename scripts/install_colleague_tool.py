"""Install the ask_colleague tool row in Open WebUI, and grant it.

Run on the server:
  OPENWEBUI_API_KEY=... DATABASE_URL=... \
      python3 scripts/install_colleague_tool.py         # show
  OPENWEBUI_API_KEY=... DATABASE_URL=... \
      python3 scripts/install_colleague_tool.py --apply # write

Three steps, not one, and the middle one is the one that was missing.

1. The ROW. A tool needs BOTH a public.tool row AND generated `specs`, or it
   is invisible to every model. Open WebUI generates the specs from the source
   when the row is created through its own endpoint, which is why this posts
   rather than writing the table directly.

2. The GRANT. This platform replaced Open WebUI's JSON `access_control` with a
   public.access_grant table, and scripts/grant_tools_public.py says what a
   tool with no grant is: "reachable by nobody". The row alone therefore
   installs a tool no model will ever offer, which looks exactly like a
   working install. Done here, the same way that script does it, and
   idempotently, so re-running is safe.

3. The ATTACH, which is a person's decision and not this script's: add
   `colleague` to an agent's meta.toolIds.

--skip-grant does step 1 only, for a box where this process cannot reach
Postgres directly. It prints the command to finish the job; it is not an
excuse to stop there.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

# The same default grant_tools_public.py carries, so both scripts talk to the
# same database when neither is told otherwise.
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://openwebui:localdev@postgres:5432/openwebui")

TOOL_ID = "colleague"
GRANT_BY_HAND = ("python3 scripts/grant_tools_public.py " + TOOL_ID)
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
    print("would POST", endpoint, "then give", TOOL_ID,
          "a public read grant in", DB_URL.rsplit("@", 1)[-1])
    sys.exit(0)

status, out = call(endpoint, {
    "id": TOOL_ID, "name": "Colleague", "content": SOURCE,
    "meta": {"description": "Ask one of your colleagues something you "
                            "cannot answer yourself."},
    # Explicitly null, the way scripts/insert_memory_tool.py sends it. Open
    # WebUI reads null as "not private to me"; who can actually reach it is
    # decided by the access_grant row below.
    "access_control": None,
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

if "--skip-grant" in sys.argv:
    print("public read grant: SKIPPED. Until it is granted the tool is "
          "reachable by nobody. Finish with: " + GRANT_BY_HAND)
    sys.exit(1)

# Public means what it already means for the 131 model rows and every other
# platform tool in this database: principal_type "user", principal_id "*",
# permission "read". These tools act as the calling user's own account, so a
# shared grant shares nobody's data.
try:
    import psycopg2
except ImportError:
    sys.exit("the row is installed but psycopg2 is not available here, so it "
             "has no grant and no model can reach it. Finish with: "
             + GRANT_BY_HAND)

try:
    conn = psycopg2.connect(DB_URL)
except Exception as exc:                                    # noqa: BLE001
    sys.exit("the row is installed but this database could not be reached "
             "(%s), so it has no grant and no model can reach it. Finish "
             "with: %s" % (exc.__class__.__name__, GRANT_BY_HAND))

with conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM public.access_grant
            WHERE resource_type = 'tool' AND resource_id = %s
              AND principal_type = 'user' AND principal_id = '*'
              AND permission = 'read'
            """,
            (TOOL_ID,))
        if cur.fetchone():
            print("public read grant: already there")
        else:
            cur.execute(
                """
                INSERT INTO public.access_grant
                    (id, resource_type, resource_id, principal_type,
                     principal_id, permission, created_at)
                VALUES (%s, 'tool', %s, 'user', '*', 'read', %s)
                """,
                (str(uuid.uuid4()), TOOL_ID, int(time.time())))
            print("public read grant: granted")
conn.close()

print("ok. Now add " + TOOL_ID + " to an agent's meta.toolIds so it can "
      "reach the tool.")
