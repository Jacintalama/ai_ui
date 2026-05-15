"""Entry point: `python -m io_mcp_calendar` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    calendar_list_events_tool_spec,
    calendar_create_event_tool_spec,
    make_calendar_list_events_handler,
    make_calendar_create_event_handler,
)


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-calendar",
        [
            (calendar_list_events_tool_spec(), make_calendar_list_events_handler(client)),
            (calendar_create_event_tool_spec(), make_calendar_create_event_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
