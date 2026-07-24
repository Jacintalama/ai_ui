#!/usr/bin/env python3
"""Install the native Calendar Tool (class Tools) into Open WebUI.

Mirrors insert_gmail_tool.py. Registers list/create/update/delete calendar
event tools so the model calls them directly and OWUI injects the signed-in
user via __user__ (per-user calendar). Reads content from
mcp-servers/calendar/openwebui_tool.py.
"""
import json
import os
import time

DB_URL = os.environ.get("DATABASE_URL", "postgresql://openwebui:localdev@postgres:5432/openwebui")

TOOL_ID = "calendar"
USER_ID = "8a2851d8-3aa9-4963-a987-a71df3bc40db"
NAME = "Calendar"

CONTENT_PATH = os.environ.get(
    "CALENDAR_TOOL_PATH", "/work/mcp-servers/calendar/openwebui_tool.py")
with open(CONTENT_PATH, "r", encoding="utf-8") as fh:
    content = fh.read()

specs = [
    {
        "name": "list_calendar_events",
        "description": "List upcoming Google Calendar events (defaults to next 7 days). Use for schedule/agenda questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start of range in ISO 8601 (optional)."},
                "time_max": {"type": "string", "description": "End of range in ISO 8601 (optional)."},
                "max_results": {"type": "integer", "description": "Max events (max 100)."},
            },
            "required": [],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a calendar event (optionally with attendees + Google Meet). Use for schedule/add-to-calendar/set-up-a-meeting.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title."},
                "start_time": {"type": "string", "description": "Start in ISO 8601, e.g. 2026-08-01T14:00:00."},
                "duration_minutes": {"type": "integer", "description": "Length in minutes (default 60)."},
                "description": {"type": "string", "description": "Notes/agenda (optional)."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails (optional; they get invited)."},
                "add_google_meet": {"type": "boolean", "description": "Attach a Google Meet link (optional)."},
                "timezone": {"type": "string", "description": "IANA timezone (optional)."},
            },
            "required": ["title", "start_time"],
        },
    },
    {
        "name": "update_calendar_event",
        "description": "Update an existing event by its id (from a list result). Pass only the fields to change.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event id."},
                "title": {"type": "string", "description": "New title (optional)."},
                "start_time": {"type": "string", "description": "New start ISO 8601 (optional)."},
                "duration_minutes": {"type": "integer", "description": "New duration (optional)."},
                "description": {"type": "string", "description": "New description (optional)."},
                "add_attendees": {"type": "array", "items": {"type": "string"}, "description": "Extra attendee emails (optional)."},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete/cancel an event by its id. Confirm with the user first, since it cancels the event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event id to delete."},
                "notify_attendees": {"type": "boolean", "description": "Notify attendees (default true)."},
            },
            "required": ["event_id"],
        },
    },
]

meta = {"description": "Google Calendar in chat: see your schedule, create/update/cancel events and meetings. Per-user."}
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
