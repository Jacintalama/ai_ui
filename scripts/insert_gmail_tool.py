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
def _maxr():
    return {"max_results": {"type": "integer", "description": "How many to return (max 50)."}}


specs = [
    {
        "name": "list_unread_emails",
        "description": "List the user's UNREAD emails. Use when they ask what's unread, new, or needs attention.",
        "parameters": {"type": "object", "properties": _maxr(), "required": []},
    },
    {
        "name": "list_important_emails",
        "description": "List emails Gmail flagged IMPORTANT. Use when they ask what's important or matters most.",
        "parameters": {"type": "object", "properties": _maxr(), "required": []},
    },
    {
        "name": "list_recent_emails",
        "description": "List the most recent inbox emails. Use when they ask to see their latest emails or inbox.",
        "parameters": {"type": "object", "properties": _maxr(), "required": []},
    },
    {
        "name": "search_emails",
        "description": "Search Gmail (supports from:, to:, subject:, after:, before:, has:attachment). Use to find specific emails.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query, e.g. 'from:alice subject:invoice'."},
                "max_results": {"type": "integer", "description": "How many results (max 50)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_email",
        "description": "Read the full content of one email by its id (from a list/search result). Use to read or summarize a message.",
        "parameters": {
            "type": "object",
            "properties": {"message_id": {"type": "string", "description": "The Gmail message id shown as `id:` in results."}},
            "required": ["message_id"],
        },
    },
    {
        "name": "draft_email",
        "description": "Create a brand-new DRAFT email in the user's Gmail Drafts (never sent). Use to draft/compose a new email.",
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
    {
        "name": "reply_to_email",
        "description": "Create a DRAFT reply to an existing email (recipient/subject auto-filled). Use to reply to a message shown to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The Gmail message id being replied to."},
                "body": {"type": "string", "description": "The reply text."},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "send_email",
        "description": ("SEND a new email immediately. IMPORTANT: only call this AFTER you have shown the user the "
                        "full email and they explicitly confirmed sending. If not confirmed, draft it or ask first."),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Plain-text body of the email."},
                "cc": {"type": "string", "description": "Optional CC (comma-separated)."},
                "bcc": {"type": "string", "description": "Optional BCC (comma-separated)."},
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

# This OWUI build's tool table has no access_control column; insert the 9
# columns it does have. Tool visibility/enable is handled in the workspace.
cursor.execute(
    '''INSERT INTO tool (id, user_id, name, content, specs, meta, created_at, updated_at, valves)
       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
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
    ),
)
conn.commit()

cursor.execute('SELECT id, name FROM tool ORDER BY id;')
print("Installed. Tools now in OWUI:")
for row in cursor.fetchall():
    print(f"  - {row[0]}: {row[1]}")

cursor.close()
conn.close()
