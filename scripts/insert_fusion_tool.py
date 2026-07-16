#!/usr/bin/env python3
"""Install (or re-install) Fusion as an Open WebUI Tool.

Reads the tool source from open-webui-functions/fusion_tool.py rather than
inlining it, so the file in git is the one that runs. Re-running is safe: the
row is replaced, and per-user settings live in a separate table so nobody's
model choices are lost on an upgrade.

Run inside the tasks container (it has the DB on its network):
    docker exec tasks python /app/scripts/insert_fusion_tool.py
"""
import json
import os
import pathlib
import sys
import time

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

TOOL_ID = "fusion"
TOOL_NAME = "Fusion"

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "open-webui-functions" / "fusion_tool.py"

# The signature the chat model sees. Only `question` is a parameter: the panel
# and the judge come from the user's own tool settings, never from the model.
SPECS = [
    {
        "name": "fuse",
        "description": (
            "Ask several AI models the same question and return one combined "
            "answer. Use this whenever the user wants a second opinion, a "
            "consensus, a cross-check, or explicitly asks for Fusion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to put to the panel, in full.",
                },
            },
            "required": ["question"],
        },
    }
]

META = {
    "description": "Ask a panel of models one question, get one combined answer. "
                   "Pick the panel in this tool's settings.",
    "manifest": {
        "title": TOOL_NAME,
        "author": "Ralph Benitez",
        "version": "1.0.0",
    },
}


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: tool source not found: {SOURCE}", file=sys.stderr)
        return 1
    content = SOURCE.read_text(encoding="utf-8")

    try:
        import psycopg2
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Own the tool as an admin, the way the other tools are owned.
    cur.execute("SELECT id, email FROM public.\"user\" WHERE role = 'admin' "
                "ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: no admin user to own the tool", file=sys.stderr)
        return 1
    user_id, owner_email = row

    now = int(time.time())
    # A stale `function` row of the same id would shadow the tool.
    cur.execute("DELETE FROM function WHERE id = %s", (TOOL_ID,))
    cur.execute("DELETE FROM tool WHERE id = %s", (TOOL_ID,))
    cur.execute(
        """
        INSERT INTO tool (id, user_id, name, content, specs, meta,
                          created_at, updated_at, valves, access_control)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            TOOL_ID, user_id, TOOL_NAME, content,
            json.dumps(SPECS), json.dumps(META), now, now, "{}",
            # NULL access_control is public in Open WebUI: every signed-in user
            # sees Fusion in the Tools dropdown, which is the point.
            None,
        ),
    )
    conn.commit()

    cur.execute("SELECT id, name, access_control IS NULL FROM tool WHERE id = %s",
                (TOOL_ID,))
    got = cur.fetchone()
    cur.close()
    conn.close()
    print(f"Installed {got[1]} (id={got[0]}, owner={owner_email}, "
          f"public={got[2]}, {len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
