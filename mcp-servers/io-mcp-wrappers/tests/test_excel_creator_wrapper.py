import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_excel_creator.tools import (
    excel_create_workbook_tool_spec,
    make_excel_create_workbook_handler,
)


# --- excel_create_workbook ---

@pytest.mark.asyncio
async def test_excel_create_workbook_calls_gateway(monkeypatch):
    client = AsyncMock()
    response_data = {
        "success": True,
        "filename": "Q1Sales.xlsx",
        "download_html": "<div>big base64 blob here</div>",
        "message": "Created Q1Sales.xlsx with 2 rows",
        "rows": 2,
        "columns": 4,
    }
    client.post = AsyncMock(return_value=response_data)
    handler = make_excel_create_workbook_handler(client)
    result = await handler({
        "title": "Q1Sales",
        "headers": "Product,Jan,Feb,Mar",
        "data": "Widget,100,150,200|Gadget,250,300,350",
        "include_totals": True,
    })
    client.post.assert_called_once_with(
        "/excel-creator/create_simple_excel",
        json={
            "title": "Q1Sales",
            "headers": "Product,Jan,Feb,Mar",
            "data": "Widget,100,150,200|Gadget,250,300,350",
            "include_totals": True,
        },
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    # download_html should be stripped from data
    assert "download_html" not in body["data"]
    assert body["data"]["filename"] == "Q1Sales.xlsx"
    assert body["data"]["rows"] == 2


@pytest.mark.asyncio
async def test_excel_create_workbook_strips_download_html(monkeypatch):
    """download_html is omitted to avoid base64-heavy context blowout."""
    client = AsyncMock()
    client.post = AsyncMock(return_value={
        "success": True,
        "filename": "Report.xlsx",
        "download_html": "data:application/vnd...base64,AAAA...",
        "message": "done",
        "rows": 1,
        "columns": 2,
    })
    handler = make_excel_create_workbook_handler(client)
    result = await handler({"title": "Report", "headers": "A,B", "data": "1,2"})
    body = json.loads(result[0].text)
    assert "download_html" not in body["data"]


@pytest.mark.asyncio
async def test_excel_create_workbook_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_excel_create_workbook_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"title": "x", "headers": "A", "data": "1"})
    assert ei.value.kind == "auth"


def test_excel_create_workbook_tool_spec_shape():
    t = excel_create_workbook_tool_spec()
    assert t.name == "excel_create_workbook"
    required = t.inputSchema["required"]
    assert "title" in required
    assert "headers" in required
    assert "data" in required
    assert "include_totals" in t.inputSchema["properties"]
