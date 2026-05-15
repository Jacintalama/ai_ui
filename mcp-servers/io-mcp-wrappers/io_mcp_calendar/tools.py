"""io-calendar MCP wrapper — exposes Google Calendar list and create tools."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def calendar_list_events_tool_spec() -> Tool:
    return Tool(
        name="calendar_list_events",
        description=(
            "List upcoming events from your Google Calendar. "
            "Defaults to the next 7 days. Optionally filter by time range."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "time_min": {
                    "type": "string",
                    "description": "Start of time range in ISO 8601 (defaults to now)",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of time range in ISO 8601 (defaults to 7 days from now)",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                    "description": "Maximum number of events to return",
                },
            },
            "required": [],
        },
    )


def calendar_create_event_tool_spec() -> Tool:
    return Tool(
        name="calendar_create_event",
        description=(
            "Create a new event on your Google Calendar. "
            "Supports optional attendees, duration, and description."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title/summary"},
                "start_time": {
                    "type": "string",
                    "description": "Event start time in ISO 8601 format (e.g., 2026-03-31T14:00:00)",
                },
                "duration_minutes": {
                    "type": "integer",
                    "default": 60,
                    "description": "Event duration in minutes (default 60)",
                },
                "description": {
                    "type": "string",
                    "description": "Event description/notes",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                },
                "add_google_meet": {
                    "type": "boolean",
                    "description": "Add a Google Meet video conference link",
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone for the event (default Asia/Manila)",
                },
            },
            "required": ["title", "start_time"],
        },
    )


def make_calendar_list_events_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {"max_results": args.get("max_results", 25)}
        if "time_min" in args:
            payload["time_min"] = args["time_min"]
        if "time_max" in args:
            payload["time_max"] = args["time_max"]
        data = await client.post("/calendar/calendar_list_events", json=payload)
        return ok_response(data)
    return handler


def make_calendar_create_event_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {
            "title": args["title"],
            "start_time": args["start_time"],
        }
        # Only pass optional fields if provided
        for key in ("duration_minutes", "description", "attendees", "add_google_meet", "timezone"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        data = await client.post("/calendar/calendar_create_event", json=payload)
        return ok_response(data)
    return handler
