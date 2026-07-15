#!/usr/bin/env python3
"""
Install the Model Fusion pipe function into Open WebUI via PostgreSQL.

Run inside the Docker network (e.g. from webhook-handler or via docker exec):
    docker compose -f docker-compose.unified.yml exec webhook-handler \
        python /app/scripts/install_fusion_pipe.py

Or from the host with port-forwarded PostgreSQL:
    DATABASE_URL=postgresql://openwebui:localdev@localhost:5432/openwebui \
        python scripts/install_fusion_pipe.py
"""
import json
import os
import sys
import time

# ---------- Configuration ----------
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://openwebui:localdev@postgres:5432/openwebui",
)

FUNCTION_ID = "fusion_pipe"
FUNCTION_NAME = "Model Fusion"
FUNCTION_TYPE = "pipe"
# User ID of the admin user (first user created in Open WebUI)
USER_ID = os.environ.get("OWUI_ADMIN_USER_ID", "b794bbd5-151c-4d70-b2cb-8fd6b1be851d")

# Valves defaults (overridden via Open WebUI UI or API after install)
# Fusion pipe valves. INTERNAL_SECRET is auto-populated from the container's
# INTERNAL_CALLBACK_SECRET (the same secret /api/fusion checks) so the pipe can
# authenticate immediately after install with no manual valve editing.
DEFAULT_VALVES = {
    "TASKS_URL": os.environ.get("TASKS_URL", "http://tasks:8210"),
    "INTERNAL_SECRET": os.environ.get("INTERNAL_CALLBACK_SECRET", ""),
    "TIMEOUT_SECONDS": 150,
}

# ---------- Read the pipe function source ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PIPE_SOURCE_PATH = os.path.join(PROJECT_ROOT, "open-webui-functions", "fusion_pipe.py")

# Allow override via env or fallback to co-located copy in Docker
if not os.path.exists(PIPE_SOURCE_PATH):
    # Inside Docker the source may be mounted at /app/open-webui-functions
    PIPE_SOURCE_PATH = "/app/open-webui-functions/fusion_pipe.py"

if not os.path.exists(PIPE_SOURCE_PATH):
    print(f"ERROR: Cannot find fusion_pipe.py at {PIPE_SOURCE_PATH}")
    sys.exit(1)

with open(PIPE_SOURCE_PATH, "r", encoding="utf-8") as f:
    pipe_content = f.read()

print(f"Read pipe source: {len(pipe_content)} chars from {PIPE_SOURCE_PATH}")

# ---------- Connect to PostgreSQL ----------
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"], check=True)
    import psycopg2

print(f"Connecting to PostgreSQL...")
conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

# ---------- Look up admin user ID if not provided ----------
if USER_ID == "b794bbd5-151c-4d70-b2cb-8fd6b1be851d":
    cursor.execute("SELECT id FROM \"user\" ORDER BY created_at ASC LIMIT 1")
    row = cursor.fetchone()
    if row:
        USER_ID = row[0]
        print(f"Using admin user ID: {USER_ID}")
    else:
        print("WARNING: No users found in database, using default user ID")

# ---------- Upsert the function ----------
now = int(time.time())
meta = json.dumps({
    "description": "Model Fusion - fan a prompt out to a model panel, judge synthesizes one answer",
})
valves_json = json.dumps(DEFAULT_VALVES)

# Delete existing if present
cursor.execute("DELETE FROM function WHERE id = %s", (FUNCTION_ID,))
deleted = cursor.rowcount
if deleted:
    print(f"Removed existing '{FUNCTION_ID}' function")

# Insert
print(f"Inserting function '{FUNCTION_ID}' (type={FUNCTION_TYPE})...")
cursor.execute(
    """
    INSERT INTO function (id, user_id, name, type, content, meta, created_at, updated_at, valves, is_active, is_global)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
    (
        FUNCTION_ID,
        USER_ID,
        FUNCTION_NAME,
        FUNCTION_TYPE,
        pipe_content,
        meta,
        now,
        now,
        valves_json,
        True,
        True,
    ),
)

conn.commit()
print(f"Committed!")

# ---------- Verify ----------
cursor.execute(
    "SELECT id, name, type, is_active, is_global FROM function WHERE id = %s",
    (FUNCTION_ID,),
)
row = cursor.fetchone()
if row:
    print(f"Verified: id={row[0]}, name={row[1]}, type={row[2]}, active={row[3]}, global={row[4]}")
else:
    print("ERROR: Function not found after insert!")
    sys.exit(1)

# Show all functions
cursor.execute("SELECT id, name, type, is_active FROM function ORDER BY name")
rows = cursor.fetchall()
print(f"\nAll functions in database ({len(rows)}):")
for r in rows:
    print(f"  {r[0]:30s} | {r[1]:30s} | type={r[2]:6s} | active={r[3]}")

conn.close()
print(f"\nDone! The '{FUNCTION_NAME}' pipe is now available in Open WebUI.")
print(f"Model names in the dropdown: {FUNCTION_ID}.fusion-quality, {FUNCTION_ID}.fusion-budget")
