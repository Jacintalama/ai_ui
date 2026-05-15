"""Entry point: `python -m io_mcp_excel_creator` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import excel_create_workbook_tool_spec, make_excel_create_workbook_handler


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-excel-creator",
        [(excel_create_workbook_tool_spec(), make_excel_create_workbook_handler(client))],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
