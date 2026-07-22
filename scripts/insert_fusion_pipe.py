#!/usr/bin/env python3
"""Install the "Fusion" pipe (a selectable model) and retire the toggle filter.

The toggle filter could not read all selected models' answers (Open WebUI runs
outlet filters once per model, each seeing only one branch). This pipe queries a
panel itself, reads every answer, and streams one merged answer - which is what
was actually wanted. Deactivates fusion_filter so there is a single "Fusion".

Run from /root/proxy-server on the box:
    docker run --rm --network proxy-server_backend -v /root/proxy-server:/work \
      -w /work --env-file .env python:3.11-slim sh -c \
      'pip install -q psycopg2-binary && DATABASE_URL=postgresql://openwebui:$POSTGRES_PASSWORD@postgres:5432/openwebui \
       python scripts/insert_fusion_pipe.py'
"""
import json
import os
import pathlib
import sys
import time

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

FUNC_ID = "fusion_pipe"
FUNC_NAME = "Fusion"
OLD_FILTER_ID = "fusion_filter"

SOURCE = (pathlib.Path(__file__).resolve().parent.parent
          / "open-webui-functions" / "fusion_pipe.py")

META = {
    "description": "Queries several models and writes one merged, accurate answer.",
    "manifest": {
        "title": FUNC_NAME,
        "author": "Ralph Benitez",
        "version": "2.0.0",
        "description": "Queries several models, reads all their answers, and "
                       "writes one merged, well-structured answer.",
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
    # Retire the toggle filter so there is exactly one "Fusion".
    cur.execute("UPDATE function SET is_active = FALSE WHERE id = %s", (OLD_FILTER_ID,))
    retired = cur.rowcount
    conn.commit()

    cur.execute("SELECT id, name, type, is_active, is_global FROM function WHERE id = %s",
                (FUNC_ID,))
    got = cur.fetchone()
    cur.close()
    conn.close()
    print(f"Installed {got[1]} (id={got[0]}, type={got[2]}, active={got[3]}, "
          f"global={got[4]}, owner={owner_email}, {len(content)} bytes)")
    print(f"Deactivated toggle filter rows: {retired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
