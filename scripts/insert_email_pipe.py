#!/usr/bin/env python3
"""Install the "Email" pipe (a selectable model) and retire the connect filter.

Why a pipe: OWUI outlet filters persist injected content to the DB but the
frontend does not re-render it live, so a filter can't show a Connect button in
the open chat. A pipe fully owns the reply and renders live (styled HTML too).
Not connected -> Connect card; connected -> extract fields + create a draft.
Deactivates connect_card_filter so there is a single, reliable Email surface.

Run from /root/proxy-server on the box:
    docker run --rm --network proxy-server_backend -v /root/proxy-server:/work \
      -w /work --env-file .env python:3.11-slim sh -c \
      'pip install -q psycopg2-binary && DATABASE_URL=postgresql://openwebui:$POSTGRES_PASSWORD@postgres:5432/openwebui \
       python scripts/insert_email_pipe.py'
"""
import json
import os
import pathlib
import sys
import time

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

FUNC_ID = "email_pipe"
FUNC_NAME = "Email"
OLD_FILTER_ID = "connect_card_filter"

SOURCE = (pathlib.Path(__file__).resolve().parent.parent
          / "open-webui-functions" / "email_pipe.py")

META = {
    "description": "Draft emails from chat. Connect Gmail with one click, then "
                   "say who to email and what to say. Drafts only, never sent.",
    "manifest": {
        "title": FUNC_NAME,
        "author": "Ralph Benitez",
        "version": "0.1.0",
        "description": "Selectable Email model: one-click Gmail connect + draft "
                       "creation from natural language. Draft-only.",
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
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "psycopg2-binary", "-q"])
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
    # Retire the outlet filter (it can't render live).
    cur.execute("UPDATE function SET is_active = FALSE WHERE id = %s", (OLD_FILTER_ID,))
    conn.commit()

    cur.execute("SELECT id, name, type, is_active, is_global FROM function WHERE id = %s",
                (FUNC_ID,))
    got = cur.fetchone()
    print(f"Installed {got[1]} (id={got[0]}, type={got[2]}, active={got[3]}, "
          f"global={got[4]}); owner={owner_email}")
    cur.execute("SELECT id, is_active FROM function WHERE id = %s", (OLD_FILTER_ID,))
    old = cur.fetchone()
    if old:
        print(f"Retired {old[0]} (is_active={old[1]})")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
