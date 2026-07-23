#!/usr/bin/env python3
"""Install the native Gmail Tool (class Tools) into Open WebUI.

Mirrors scripts/insert_tool.py (Excel Creator). Registers `connect_gmail` and
`draft_email` as native OWUI tools so the model calls them directly (no
meta-tools discovery) and Open WebUI injects the real signed-in user via
__user__ (correct per-user Gmail). The tool content is read from
mcp-servers/gmail/openwebui_tool.py so there is a single source of truth.
"""
import json
import os
import time

DB_URL = os.environ.get("DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

TOOL_ID = "gmail"
USER_ID = "8a2851d8-3aa9-4963-a987-a71df3bc40db"  # admin, same owner as excel_creator
NAME = "Gmail"

# Read the tool content from the source file (single source of truth).
CONTENT_PATH = os.environ.get(
    "GMAIL_TOOL_PATH", "/work/mcp-servers/gmail/openwebui_tool.py"
)
with open(CONTENT_PATH, "r", encoding="utf-8") as fh:
    content = fh.read()

# Function-calling specs (OpenAPI-style), one per public method.
# __user__ is injected by Open WebUI and is intentionally NOT in the schema.
specs = [
    {
        "name": "connect_gmail",
        "description": (
            "Get a one-click link to connect or reconnect the user's Gmail "
            "account. Use when the user asks to connect Gmail, set up email, or "
            "when a draft failed because Gmail is not connected."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "draft_email",
        "description": (
            "Create a brand-new draft email in the user's Gmail Drafts folder "
            "(never sent). Use when the user wants to draft, compose, or write a "
            "new email to someone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Plain-text body of the email."},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

meta = {"description": "Connect your Gmail and draft new emails from chat. Drafts only, nothing is sent automatically."}
now = int(time.time())

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

# Remove any prior copy in either table (tool vs function namespaces).
cursor.execute('DELETE FROM function WHERE id = %s', (TOOL_ID,))
cursor.execute('DELETE FROM tool WHERE id = %s', (TOOL_ID,))

cursor.execute(
    '''INSERT INTO tool (id, user_id, name, content, specs, meta, created_at, updated_at, valves, access_control)
       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
    (
        TOOL_ID,
        USER_ID,
        NAME,
        content,
        json.dumps(specs),
        json.dumps(meta),
        now,
        now,
        '{}',
        None,  # null access_control = public (available to all users)
    ),
)
conn.commit()

cursor.execute('SELECT id, name FROM tool ORDER BY id;')
print("Installed. Tools now in OWUI:")
for row in cursor.fetchall():
    print(f"  - {row[0]}: {row[1]}")

cursor.close()
conn.close()
