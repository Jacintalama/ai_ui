"""Entry point: `python -m io_mcp_dashboard` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import dashboard_create_tool_spec, make_dashboard_create_handler


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-dashboard",
        [(dashboard_create_tool_spec(), make_dashboard_create_handler(client))],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
