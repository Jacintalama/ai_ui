#!/usr/bin/env python3
"""Auto-enable the native Gmail tool on the tool-capable OWUI models.

Adds tool id "gmail" to each target model's meta.toolIds so users get the
Gmail tool by default (no manual per-chat toggle). Idempotent: skips models
that already have it. Leaves any existing tool ids (e.g. "server:mcp-proxy")
in place.
"""
import json
import os

DB_URL = os.environ.get("DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")
TOOL_ID = "gmail"
TARGET_MODELS = os.environ.get("TARGET_MODELS", "gpt-5,gpt-3.5-turbo").split(",")

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

for model_id in [m.strip() for m in TARGET_MODELS if m.strip()]:
    cur.execute("SELECT meta FROM model WHERE id = %s", (model_id,))
    row = cur.fetchone()
    if not row:
        print(f"  {model_id}: not found, skipped")
        continue
    meta = json.loads(row[0]) if row[0] else {}
    tool_ids = meta.get("toolIds") or []
    if TOOL_ID in tool_ids:
        print(f"  {model_id}: already has '{TOOL_ID}' -> {tool_ids}")
        continue
    tool_ids.append(TOOL_ID)
    meta["toolIds"] = tool_ids
    cur.execute("UPDATE model SET meta = %s WHERE id = %s", (json.dumps(meta), model_id))
    print(f"  {model_id}: enabled '{TOOL_ID}' -> {tool_ids}")

conn.commit()
cur.close()
conn.close()
print("Done.")
