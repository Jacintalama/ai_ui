"""Give the platform tools a public read grant, so every user can reach them.

A tool with no grant is owner-only. Five of these have no owner either, which
made them reachable by nobody once BYPASS_ADMIN_ACCESS_CONTROL was turned off
and admins stopped skipping the check.

Public here means the same thing it already means for the 131 model rows in
this database: principal_type "user", principal_id "*", permission "read".
These tools act as the calling user's own account, so a shared grant does not
share anyone's data.

Idempotent: a tool that already has the grant is left alone.
"""
import os
import sys
import time
import uuid

import psycopg2

TOOL_IDS = [t for t in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if t]
if not TOOL_IDS:
    sys.exit("usage: grant_tools_public.py <tool-id>[,<tool-id>...]")

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://openwebui:localdev@postgres:5432/openwebui")

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

granted, already, missing = [], [], []
for tool_id in TOOL_IDS:
    cur.execute("SELECT 1 FROM public.tool WHERE id = %s", (tool_id,))
    if not cur.fetchone():
        missing.append(tool_id)
        continue

    cur.execute(
        """
        SELECT 1 FROM public.access_grant
        WHERE resource_type = 'tool' AND resource_id = %s
          AND principal_type = 'user' AND principal_id = '*'
          AND permission = 'read'
        """,
        (tool_id,))
    if cur.fetchone():
        already.append(tool_id)
        continue

    cur.execute(
        """
        INSERT INTO public.access_grant
            (id, resource_type, resource_id, principal_type, principal_id,
             permission, created_at)
        VALUES (%s, 'tool', %s, 'user', '*', 'read', %s)
        """,
        (str(uuid.uuid4()), tool_id, int(time.time())))
    granted.append(tool_id)

conn.commit()

print("granted:", granted or "none")
print("already public:", already or "none")
if missing:
    print("NOT FOUND (no such tool):", missing)

cur.execute(
    """
    SELECT resource_id FROM public.access_grant
    WHERE resource_type = 'tool' AND principal_id = '*'
    ORDER BY resource_id
    """)
print("all publicly readable tools now:", [r[0] for r in cur.fetchall()])

cur.close()
conn.close()
