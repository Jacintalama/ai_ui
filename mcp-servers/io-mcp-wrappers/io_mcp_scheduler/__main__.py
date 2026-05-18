"""Entry point: `python -m io_mcp_scheduler` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    create_schedule_tool_spec,
    list_schedules_tool_spec,
    delete_schedule_tool_spec,
    make_create_handler,
    make_list_handler,
    make_delete_handler,
)


def main() -> None:
    client = GatewayClient()  # raises if env missing — see io_mcp_base.client
    server = build_server(
        "io-scheduler",
        [
            (create_schedule_tool_spec(), make_create_handler(client)),
            (list_schedules_tool_spec(), make_list_handler(client)),
            (delete_schedule_tool_spec(), make_delete_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
