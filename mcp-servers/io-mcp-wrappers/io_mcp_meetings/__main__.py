"""Entry point: `python -m io_mcp_meetings` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    meetings_list_tool_spec,
    meetings_get_tool_spec,
    make_meetings_list_handler,
    make_meetings_get_handler,
)


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-meetings",
        [
            (meetings_list_tool_spec(), make_meetings_list_handler(client)),
            (meetings_get_tool_spec(), make_meetings_get_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
