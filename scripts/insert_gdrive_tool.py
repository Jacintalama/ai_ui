#!/usr/bin/env python3
"""Install the native Google Drive Tool (class Tools) into Open WebUI.

Mirrors insert_gmail_tool.py. Read-only Drive: list/search/read files.
Reads content from mcp-servers/gdrive/openwebui_tool.py.
"""
import json
import os
import time

DB_URL = os.environ.get("DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

TOOL_ID = "gdrive"
USER_ID = "8a2851d8-3aa9-4963-a987-a71df3bc40db"
NAME = "Google Drive"

CONTENT_PATH = os.environ.get(
    "GDRIVE_TOOL_PATH", "/work/mcp-servers/gdrive/openwebui_tool.py")
with open(CONTENT_PATH, "r", encoding="utf-8") as fh:
    content = fh.read()

specs = [
    {
        "name": "list_drive_files",
        "description": "List files in the user's Google Drive (folder_id='root' for top level).",
        "parameters": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Folder to list ('root' for top level)."},
                "max_results": {"type": "integer", "description": "How many files (max 50)."},
            },
            "required": [],
        },
    },
    {
        "name": "search_drive",
        "description": "Search the user's Google Drive by name or content. Use to find a specific file.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, e.g. 'quarterly report'."},
                "max_results": {"type": "integer", "description": "How many results (max 50)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_drive_file",
        "description": "Read the text content of a Drive file by its id (from a list/search result). Use to read/summarize a doc.",
        "parameters": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "The Drive file id shown as file_id in results."}},
            "required": ["file_id"],
        },
    },
    {
        "name": "upload_drive_file",
        "description": "Create/upload a NEW file in the user's Google Drive with text content. Use to save/upload/store something as a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name, e.g. 'notes.txt'."},
                "content": {"type": "string", "description": "The text content to save."},
                "mime_type": {"type": "string", "description": "MIME type (default text/plain)."},
            },
            "required": ["name", "content"],
        },
    },
]

meta = {"description": "Browse, search, and read your Google Drive files from chat. Per-user. Read-only for now."}
now = int(time.time())

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()
cur.execute('DELETE FROM function WHERE id = %s', (TOOL_ID,))
cur.execute('DELETE FROM tool WHERE id = %s', (TOOL_ID,))
cur.execute(
    '''INSERT INTO tool (id, user_id, name, content, specs, meta, created_at, updated_at, valves)
       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
    (TOOL_ID, USER_ID, NAME, content, json.dumps(specs), json.dumps(meta), now, now, '{}'),
)
conn.commit()
cur.execute('SELECT id, name FROM tool ORDER BY id;')
print("Installed. Tools now in OWUI:")
for row in cur.fetchall():
    print(f"  - {row[0]}: {row[1]}")
cur.close()
conn.close()
