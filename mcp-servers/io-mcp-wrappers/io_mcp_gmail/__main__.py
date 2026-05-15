"""Entry point: `python -m io_mcp_gmail` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    gmail_search_tool_spec,
    gmail_read_tool_spec,
    gmail_send_tool_spec,
    make_gmail_search_handler,
    make_gmail_read_handler,
    make_gmail_send_handler,
)


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-gmail",
        [
            (gmail_search_tool_spec(), make_gmail_search_handler(client)),
            (gmail_read_tool_spec(), make_gmail_read_handler(client)),
            (gmail_send_tool_spec(), make_gmail_send_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
