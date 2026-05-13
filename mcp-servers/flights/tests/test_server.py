"""Tests the search_flights tool registration + DuffelError→tool_error mapping."""
from unittest.mock import patch, AsyncMock
import pytest

from flights_mcp.server import call_search_flights
from flights_mcp.duffel import DuffelError
from flights_mcp.schemas import FlightOffer


@pytest.mark.asyncio
async def test_search_flights_returns_offer_list():
    fake_offer = FlightOffer(
        id="off_x", origin="LAX", destination="NRT",
        airline="ANA", price=1200.0, stops=0, duration=700,
        departure_hour=11, departure_label="11:00", arrival_label="15:30",
        cabin="Economy", baggage="1x 23kg checked",
    )
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(return_value=[fake_offer])
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert isinstance(result, list)
    assert result[0]["airline"] == "ANA"
    assert result[0]["origin"] == "LAX"


@pytest.mark.asyncio
async def test_rate_limit_returned_as_tool_error():
    """DuffelError -> structured dict, not raised."""
    err = DuffelError(kind="rate_limit", retry_after=30)
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(side_effect=err)
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert isinstance(result, dict)
    assert result["error"] == "rate_limit"
    assert result["retry_after"] == 30


@pytest.mark.asyncio
async def test_auth_returned_as_tool_error():
    err = DuffelError(kind="auth", detail="bad key")
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(side_effect=err)
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert result == {"error": "auth", "detail": "DUFFEL_API_KEY invalid"}


@pytest.mark.asyncio
async def test_missing_api_key_returned_as_tool_error():
    result = await call_search_flights(
        api_key="",
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert result == {"error": "auth", "detail": "DUFFEL_API_KEY not set"}
