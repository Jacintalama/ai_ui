#!/usr/bin/env python3
"""Install (or re-install) the Fuse action in Open WebUI, and retire the old
Fusion tool.

The tool was the wrong shape: it ran its own private fan-out inside a tool call,
so the models the user actually picked were never the panel, and any model
without function-calling (gpt-5.6-sol) could not use it at all. The action runs
after the models answer and judges those answers, which is the point.

Mirrors the visualize_data action already installed here: type='action',
is_active, is_global, so the button shows under every response.

Run from /root/proxy-server on the box:
    docker run --rm --network proxy-server_backend -v /root/proxy-server:/work \
      -w /work --env-file .env python:3.11-slim sh -c \
      'pip install -q psycopg2-binary && DATABASE_URL=... python scripts/insert_fusion_action.py'
"""
import json
import os
import pathlib
import sys
import time

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

ACTION_ID = "fuse"
ACTION_NAME = "Fuse"
OLD_TOOL_ID = "fusion"

SOURCE = (pathlib.Path(__file__).resolve().parent.parent
          / "open-webui-functions" / "fusion_action.py")

META = {
    "description": "Cross-check the answers your models just gave and produce "
                   "one verified answer.",
    "manifest": {
        "title": ACTION_NAME,
        "author": "Ralph Benitez",
        "version": "1.0.0",
        "description": "Cross-check the answers your models just gave and "
                       "produce one verified answer.",
    },
}


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: action source not found: {SOURCE}", file=sys.stderr)
        return 1
    content = SOURCE.read_text(encoding="utf-8")

    try:
        import psycopg2
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "psycopg2-binary", "-q"])
        import psycopg2

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("SELECT id, email FROM public.\"user\" WHERE role = 'admin' "
                "ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: no admin user to own the action", file=sys.stderr)
        return 1
    user_id, owner_email = row

    # Retire the tool. It fanned out on its own, which is exactly the behaviour
    # being replaced, so leaving it installed would offer two Fusions that mean
    # different things.
    cur.execute("DELETE FROM tool WHERE id = %s", (OLD_TOOL_ID,))
    removed_tool = cur.rowcount

    now = int(time.time())
    cur.execute("DELETE FROM function WHERE id = %s", (ACTION_ID,))
    cur.execute(
        """
        INSERT INTO function (id, user_id, name, type, content, meta,
                              created_at, updated_at, valves, is_active, is_global)
        VALUES (%s, %s, %s, 'action', %s, %s, %s, %s, %s, TRUE, TRUE)
        """,
        (ACTION_ID, user_id, ACTION_NAME, content, json.dumps(META),
         now, now, "{}"),
    )
    conn.commit()

    cur.execute("SELECT id, name, type, is_active, is_global FROM function "
                "WHERE id = %s", (ACTION_ID,))
    got = cur.fetchone()
    cur.close()
    conn.close()
    print(f"Installed {got[1]} (id={got[0]}, type={got[2]}, active={got[3]}, "
          f"global={got[4]}, owner={owner_email}, {len(content)} bytes)")
    print(f"Removed old fusion tool rows: {removed_tool}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
