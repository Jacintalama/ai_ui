#!/usr/bin/env python3
"""Enable the native Gmail draft tool on the tool-capable (paid) models.

Free/OpenRouter models can't do function-calling, so we only enable the tool
on the models that can actually use it. For each target model: if a model row
exists, merge tool id "gmail" into meta.toolIds; if not, create a minimal row
(base_model_id NULL, like the gpt-5 row) so the base model gains the tool by
default. Idempotent. The inline Connect button is separate and already works
on every model.
"""
import json
import os
import time

DB_URL = os.environ.get("DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")
TOOL_ID = "gmail"
# Known tool-capable paid models (from the Fusion registry). Extend as needed.
TARGET_MODELS = os.environ.get(
    "TARGET_MODELS",
    "gpt-5,gpt-5.5,gpt-4o,gpt-4.1,o3,gpt-4o-mini,gpt-3.5-turbo",
).split(",")

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# Owner for any new rows: reuse an existing model's owner, else an admin.
cur.execute("SELECT user_id FROM model ORDER BY created_at LIMIT 1")
row = cur.fetchone()
owner_id = row[0] if row else None
if not owner_id:
    cur.execute("SELECT id FROM public.\"user\" WHERE role='admin' ORDER BY created_at LIMIT 1")
    r2 = cur.fetchone()
    owner_id = r2[0] if r2 else "system"

now = int(time.time())

for model_id in [m.strip() for m in TARGET_MODELS if m.strip()]:
    cur.execute("SELECT meta FROM model WHERE id = %s", (model_id,))
    got = cur.fetchone()
    if got:
        meta = json.loads(got[0]) if got[0] else {}
        tool_ids = meta.get("toolIds") or []
        if TOOL_ID in tool_ids:
            print(f"  {model_id}: already enabled -> {tool_ids}")
            continue
        tool_ids.append(TOOL_ID)
        meta["toolIds"] = tool_ids
        cur.execute("UPDATE model SET meta = %s, updated_at = %s WHERE id = %s",
                    (json.dumps(meta), now, model_id))
        print(f"  {model_id}: merged '{TOOL_ID}' -> {tool_ids}")
    else:
        meta = {"toolIds": [TOOL_ID]}
        cur.execute(
            "INSERT INTO model (id, user_id, base_model_id, name, meta, params, "
            "created_at, updated_at, is_active) "
            "VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, TRUE)",
            (model_id, owner_id, model_id, json.dumps(meta), "{}", now, now),
        )
        print(f"  {model_id}: created row with '{TOOL_ID}'")

conn.commit()
cur.close()
conn.close()
print("Done.")
