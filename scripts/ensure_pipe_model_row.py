#!/usr/bin/env python3
"""Give a pipe's model the public.model row its chat path needs.

Run on the server:
  python3 scripts/ensure_pipe_model_row.py io.io IO

A pipe installed by script alone is listed in /api/models and then refuses
every message with 400 "Model not found". Two rows back a pipe, not one: the
function row holds the code, and public.model is what the chat path resolves
against. Installing through the admin UI writes both; the insert_*_pipe.py
scripts write only the first.

That gap was invisible while BYPASS_ADMIN_ACCESS_CONTROL was on, because an
admin skipped the lookup that needs the row. It surfaced the day that flag
was turned off.

A pipe's model id is "{function_id}.{pipe_id}" -- io.io, auto_router.auto.
Idempotent, and mirrors the rows Open WebUI writes for its own pipes: no base
model, empty meta and params, active.
"""
import json
import os
import sys
import time

import psycopg2

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://openwebui:localdev@postgres:5432/openwebui")

if len(sys.argv) != 3:
    sys.exit("usage: ensure_pipe_model_row.py <model-id> <display-name>")
model_id, display_name = sys.argv[1], sys.argv[2]

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# Reuse an existing model's owner so the row is owned the way the rest are,
# falling back to an admin on an empty table.
cur.execute("SELECT user_id FROM public.model ORDER BY created_at LIMIT 1")
row = cur.fetchone()
owner_id = row[0] if row else None
if not owner_id:
    cur.execute('SELECT id FROM public."user" WHERE role = %s'
                " ORDER BY created_at LIMIT 1", ("admin",))
    row = cur.fetchone()
    owner_id = row[0] if row else None
if not owner_id:
    sys.exit("no user to own the model row")

now = int(time.time())
cur.execute(
    """
    INSERT INTO public.model
        (id, user_id, base_model_id, name, meta, params,
         created_at, updated_at, is_active)
    VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, TRUE)
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        is_active = TRUE,
        updated_at = EXCLUDED.updated_at
    """,
    (model_id, owner_id, display_name, json.dumps({}), json.dumps({}),
     now, now))
conn.commit()

cur.execute("SELECT id, name, is_active, base_model_id"
            " FROM public.model WHERE id = %s", (model_id,))
print("model row:", cur.fetchone())
cur.close()
conn.close()
