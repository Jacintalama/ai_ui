import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_dashboard.tools import (
    dashboard_create_tool_spec,
    make_dashboard_create_handler,
)


# --- dashboard_create ---

@pytest.mark.asyncio
async def test_dashboard_create_calls_gateway(monkeypatch):
    client = AsyncMock()
    response_data = {
        "success": True,
        "filename": "dashboard_20260515_120000.html",
        "download_html": "<div>Download</div>",
        "message": "Created dashboard with 2 KPIs and 1 charts",
        "kpi_count": 2,
        "chart_count": 1,
    }
    client.post = AsyncMock(return_value=response_data)
    handler = make_dashboard_create_handler(client)
    result = await handler({
        "title": "Q1 Dashboard",
        "kpis": "Revenue:$1.2M:+15%:up|Users:45K:+8%:up",
        "chart_type": "bar",
        "chart_title": "Monthly Sales",
        "chart_labels": "Jan,Feb,Mar",
        "chart_data": "100,120,140",
    })
    client.post.assert_called_once_with(
        "/dashboard/create_simple_dashboard",
        json={
            "title": "Q1 Dashboard",
            "kpis": "Revenue:$1.2M:+15%:up|Users:45K:+8%:up",
            "chart_type": "bar",
            "chart_title": "Monthly Sales",
            "chart_labels": "Jan,Feb,Mar",
            "chart_data": "100,120,140",
        },
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["success"] is True
    assert body["data"]["kpi_count"] == 2


@pytest.mark.asyncio
async def test_dashboard_create_strips_download_html(monkeypatch):
    """download_html is omitted to avoid base64-heavy context blowout."""
    client = AsyncMock()
    client.post = AsyncMock(return_value={
        "success": True,
        "filename": "dashboard_20260515.html",
        "download_html": "data:text/html;base64,PGRpdj5MYXJnZSBIVE1MIGZPIE..." * 100,
        "message": "Created dashboard",
        "kpi_count": 1,
        "chart_count": 0,
    })
    handler = make_dashboard_create_handler(client)
    result = await handler({"title": "Q1"})
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert "download_html" not in body["data"]
    assert body["data"]["filename"] == "dashboard_20260515.html"


@pytest.mark.asyncio
async def test_dashboard_create_title_only(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "filename": "d.html", "kpi_count": 0, "chart_count": 0})
    handler = make_dashboard_create_handler(client)
    await handler({"title": "Empty"})
    client.post.assert_called_once_with(
        "/dashboard/create_simple_dashboard",
        json={"title": "Empty"},
    )


@pytest.mark.asyncio
async def test_dashboard_create_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_dashboard_create_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"title": "x"})
    assert ei.value.kind == "auth"


def test_dashboard_create_tool_spec_shape():
    t = dashboard_create_tool_spec()
    assert t.name == "dashboard_create"
    assert "title" in t.inputSchema["properties"]
    assert "title" in t.inputSchema["required"]
    assert "kpis" in t.inputSchema["properties"]
    assert "chart_type" in t.inputSchema["properties"]
