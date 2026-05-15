"""Entry point: `python -m io_mcp_meeting_kb` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import (
    meeting_kb_search_tool_spec,
    meeting_kb_get_tool_spec,
    meeting_kb_list_tool_spec,
    make_meeting_kb_search_handler,
    make_meeting_kb_get_handler,
    make_meeting_kb_list_handler,
)


def main() -> None:
    client = GatewayClient()
    server = build_server(
        "io-meeting-kb",
        [
            (meeting_kb_search_tool_spec(), make_meeting_kb_search_handler(client)),
            (meeting_kb_get_tool_spec(), make_meeting_kb_get_handler(client)),
            (meeting_kb_list_tool_spec(), make_meeting_kb_list_handler(client)),
        ],
    )
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
