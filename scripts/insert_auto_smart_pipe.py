#!/usr/bin/env python3
"""Install (or re-install) the "Auto (Smart)" router pipe in Open WebUI.

Sibling of the Auto (Free) installer. Registers a selectable model that routes
easy tasks to a free model and hard coding/reasoning to a paid one. Needs
OPENROUTER_API_KEY and OPENAI_API_KEY in the open-webui container environment.

Run from /root/proxy-server on the box:
    docker run --rm --network proxy-server_backend -v /root/proxy-server:/work \
      -w /work --env-file .env python:3.11-slim sh -c \
      'pip install -q psycopg2-binary && DATABASE_URL=postgresql://openwebui:$POSTGRES_PASSWORD@postgres:5432/openwebui \
       python scripts/insert_auto_smart_pipe.py'
"""
import json
import os
import pathlib
import sys
import time

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

FUNC_ID = "auto_smart"
FUNC_NAME = "Auto (Smart)"

SOURCE = (pathlib.Path(__file__).resolve().parent.parent
          / "open-webui-functions" / "auto_smart_pipe.py")

META = {
    "description": "Picks the best model per task: free for everyday, paid for hard.",
    "manifest": {
        "title": FUNC_NAME,
        "author": "Ralph Benitez",
        "version": "1.0.0",
        "description": "Routes easy tasks to a free model and hard coding or "
                       "reasoning to a strong paid model.",
    },
}


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: pipe source not found: {SOURCE}", file=sys.stderr)
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
    cur.execute("SELECT id, email FROM public.\"user\" WHERE role = 'admin' "
                "ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: no admin user to own the pipe", file=sys.stderr)
        return 1
    user_id, owner_email = row

    now = int(time.time())
    cur.execute("DELETE FROM function WHERE id = %s", (FUNC_ID,))
    cur.execute(
        "INSERT INTO function (id, user_id, name, type, content, meta, "
        "created_at, updated_at, valves, is_active, is_global) "
        "VALUES (%s, %s, %s, 'pipe', %s, %s, %s, %s, %s, TRUE, TRUE)",
        (FUNC_ID, user_id, FUNC_NAME, content, json.dumps(META), now, now, "{}"),
    )
    conn.commit()
    cur.execute("SELECT id, name, type, is_active, is_global FROM function WHERE id = %s",
                (FUNC_ID,))
    got = cur.fetchone()
    cur.close()
    conn.close()
    print(f"Installed {got[1]} (id={got[0]}, type={got[2]}, active={got[3]}, "
          f"global={got[4]}, owner={owner_email}, {len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
