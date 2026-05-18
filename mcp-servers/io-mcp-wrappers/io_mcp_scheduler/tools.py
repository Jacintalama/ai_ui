"""io-scheduler MCP tools — create / list / delete recurring schedules.

Auth model: the GatewayClient adds the user's JWT to every request. The
api-gateway validates it and injects X-User-Email, so the schedules service
scopes everything to that user automatically.
"""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response, error_response


_SCHEDULES_PATH = "/api/tasks/schedules"


def create_schedule_tool_spec() -> Tool:
    return Tool(
        name="create_schedule",
        description=(
            "Create a recurring scheduled task for the current user. Use this "
            "when the user asks to run something periodically (e.g. \"every day "
            "at 8pm watch my stocks\", \"every Friday digest my trello\", "
            "\"watch flights Davao to Cebu daily and alert me on cheap fares\"). "
            "You — the agent — convert the natural-language schedule into a "
            "standard 5-field cron expression and pick a sensible timezone "
            "(default Asia/Manila unless the user says otherwise). The schedule "
            "fires autonomously after creation; the agent runs with the given "
            "persona and the prompt as its task."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short, memorable label (e.g. 'morning-stocks'). Lowercase/hyphens preferred.",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Standard 5-field cron expression in the schedule's timezone (e.g. '0 8 * * *' = daily at 08:00).",
                },
                "tz": {
                    "type": "string",
                    "description": "IANA timezone name. Defaults to Asia/Manila.",
                    "default": "Asia/Manila",
                },
                "persona": {
                    "type": "string",
                    "description": "Short system-prompt prefix that gives the agent a role, e.g. 'You are my stockbroker.'",
                    "default": "",
                },
                "prompt": {
                    "type": "string",
                    "description": "What the agent should do at each firing — concrete instructions.",
                },
            },
            "required": ["name", "cron_expr", "prompt"],
        },
    )


def list_schedules_tool_spec() -> Tool:
    return Tool(
        name="list_my_schedules",
        description=(
            "List all schedules owned by the current user. Use this when the "
            "user asks 'what schedules do I have?' or 'show my reminders' or "
            "before deleting/modifying one (to find its id)."
        ),
        inputSchema={"type": "object", "properties": {}},
    )


def delete_schedule_tool_spec() -> Tool:
    return Tool(
        name="delete_schedule",
        description=(
            "Delete one of the user's schedules by id. Use this when the user "
            "asks 'stop watching my stocks' or 'cancel my Friday digest'. "
            "Run list_my_schedules first if you don't have the id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "UUID of the schedule to delete.",
                },
            },
            "required": ["schedule_id"],
        },
    )


def make_create_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        body = {
            "name": args["name"],
            "cron_expr": args["cron_expr"],
            "tz": args.get("tz", "Asia/Manila"),
            "persona": args.get("persona", ""),
            "prompt": args["prompt"],
            "enabled": True,
        }
        data = await client.post(_SCHEDULES_PATH, json=body)
        return ok_response({
            "id": data.get("id"),
            "summary": f"Schedule '{args['name']}' created: {args['cron_expr']} ({body['tz']}).",
        })
    return handler


def make_list_handler(client: GatewayClient):
    async def handler(_args: dict) -> list[TextContent]:
        data = await client.get(_SCHEDULES_PATH)
        # Return a trimmed view — the prompt + persona can be long.
        summary = [
            {
                "id": s["id"],
                "name": s["name"],
                "cron_expr": s["cron_expr"],
                "tz": s["tz"],
                "enabled": s["enabled"],
                "last_run_at": s["last_run_at"],
                "last_run_status": s["last_run_status"],
            }
            for s in data
        ]
        return ok_response({"schedules": summary, "count": len(summary)})
    return handler


def make_delete_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        sid = args["schedule_id"]
        # Path-validate to avoid trailing-slash quirks.
        await client.delete(f"{_SCHEDULES_PATH}/{sid}")
        return ok_response({"summary": f"Schedule {sid} deleted."})
    return handler
