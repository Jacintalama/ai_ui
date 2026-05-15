"""Entry point: `python -m io_mcp_gdrive` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    gdrive_search_tool_spec,
    gdrive_read_file_tool_spec,
    gdrive_list_files_tool_spec,
    make_gdrive_search_handler,
    make_gdrive_read_file_handler,
    make_gdrive_list_files_handler,
)


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-gdrive",
        [
            (gdrive_search_tool_spec(), make_gdrive_search_handler(client)),
            (gdrive_read_file_tool_spec(), make_gdrive_read_file_handler(client)),
            (gdrive_list_files_tool_spec(), make_gdrive_list_files_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
