"""Duffel client tests using respx to mock HTTP."""
import pytest
import respx
from httpx import Response

from flights_mcp.duffel import DuffelClient, DuffelError
from flights_mcp.schemas import FlightOffer


@pytest.fixture
def fake_offer():
    """Minimal Duffel offer payload shape."""
    return {
        "id": "off_00009htYpSCXrwaB9DnUm0",
        "owner": {"name": "All Nippon Airways"},
        "total_amount": "1247.50",
        "total_currency": "USD",
        "slices": [{
            "origin": {"iata_code": "LAX"},
            "destination": {"iata_code": "NRT"},
            "duration": "PT11H45M",
            "segments": [{
                "departing_at": "2026-06-01T11:50:00",
                "arriving_at": "2026-06-02T16:35:00",
                "passengers": [{
                    "cabin_class": "economy",
                    "baggages": [{"type": "checked", "quantity": 1}]
                }],
            }],
        }],
    }


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_returns_offers(fake_offer):
    """POST /air/offer_requests?return_offers=true returns parsed offers."""
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": [fake_offer]}})
    )
    client = DuffelClient(api_key="duffel_test_xyz")
    offers = await client.search_flights(
        origin="LAX", destination="NRT",
        depart_date="2026-06-01", passengers=1,
    )
    assert len(offers) == 1
    o = offers[0]
    assert isinstance(o, FlightOffer)
    assert o.origin == "LAX"
    assert o.destination == "NRT"
    assert o.airline == "All Nippon Airways"
    assert o.price == 1247.5
    assert o.stops == 0
    assert o.duration == 11 * 60 + 45  # PT11H45M → 705 minutes
    assert o.departure_hour == 11
    assert o.departure_label == "11:50"
    assert o.cabin == "Economy"
    assert "checked" in o.baggage


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_rate_limit_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(429, headers={"Retry-After": "30"},
                              json={"errors": [{"message": "rate limited"}]})
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "rate_limit"
    assert exc.value.retry_after == 30


@pytest.mark.asyncio
@respx.mock
async def test_401_raises_auth_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(401, json={"errors": [{"message": "bad key"}]})
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "auth"


@pytest.mark.asyncio
@respx.mock
async def test_5xx_raises_upstream_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(503)
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "upstream"


@pytest.mark.asyncio
@respx.mock
async def test_iso_duration_parses_to_minutes():
    """PT8H45M → 525 minutes (regression guard for parse_duration)."""
    from flights_mcp.duffel import parse_iso8601_duration
    assert parse_iso8601_duration("PT8H45M") == 525
    assert parse_iso8601_duration("PT11H45M") == 705
    assert parse_iso8601_duration("PT0H30M") == 30
    assert parse_iso8601_duration("PT2H") == 120


@pytest.mark.asyncio
@respx.mock
async def test_results_sorted_by_price_ascending(fake_offer):
    expensive = dict(fake_offer, id="off_b", total_amount="1500.00")
    cheap = dict(fake_offer, id="off_a", total_amount="900.00")
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": [expensive, cheap]}})
    )
    client = DuffelClient(api_key="x")
    offers = await client.search_flights(
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert offers[0].id == "off_a"  # cheap first
    assert offers[1].id == "off_b"


@pytest.mark.asyncio
@respx.mock
async def test_caps_at_6_offers(fake_offer):
    """Even if Duffel returns 50, client takes top 6 by price."""
    many = [dict(fake_offer, id=f"off_{i}", total_amount=str(800 + i * 10))
            for i in range(50)]
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": many}})
    )
    client = DuffelClient(api_key="x")
    offers = await client.search_flights(
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert len(offers) == 6
