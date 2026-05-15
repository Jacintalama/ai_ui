"""Entry point: `python -m io_mcp_web_search` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import web_search_tool_spec, make_web_search_handler


def main() -> None:
    client = GatewayClient()  # raises if env missing — see io_mcp_base.client
    server = build_server(
        "io-web-search",
        [(web_search_tool_spec(), make_web_search_handler(client))],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
