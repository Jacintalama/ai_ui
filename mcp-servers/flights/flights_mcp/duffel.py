"""Async client for the Duffel sandbox API (https://duffel.com).

We use ?return_offers=true on POST /air/offer_requests to avoid the
two-call dance. If the sandbox tier rejects that, fall back to the
two-call form (POST then GET /air/offers).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from .schemas import FlightOffer


_DUFFEL_BASE = "https://api.duffel.com"
_TIMEOUT = httpx.Timeout(10.0)


@dataclass
class DuffelError(Exception):
    kind: str                       # auth | bad_request | rate_limit | upstream | timeout | bad_response
    detail: str = ""
    retry_after: int | None = None


_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_iso8601_duration(s: str) -> int:
    """Convert an ISO 8601 duration to total minutes.

    Handles: 'PT8H45M', 'PT1H30M00S', 'P1DT11H25M' (days component for
    flights that cross the dateline), 'PT45S', etc. Seconds are floored
    into minutes. The degenerate 'PT' form (no components) is bad input.
    """
    m = _ISO_DURATION.match(s)
    if not m:
        raise DuffelError(kind="bad_response", detail=f"bad duration: {s!r}")
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    if not (days or hours or minutes or seconds):
        raise DuffelError(kind="bad_response", detail=f"empty duration: {s!r}")
    return days * 24 * 60 + hours * 60 + minutes + seconds // 60


def _format_cabin(s: str) -> str:
    """Map Duffel cabin_class to the Literal values FlightOffer accepts.

    Unknown values (e.g. 'economy_plus') fall back to 'Economy' rather
    than title-casing — Literal validation would reject anything else
    and we want a DuffelError, not an uncaught ValidationError.
    """
    return {
        "economy": "Economy",
        "premium_economy": "Premium Economy",
        "business": "Business",
        "first": "First",
    }.get(s, "Economy")


def _format_baggage(baggages: list[dict[str, Any]]) -> str:
    if not baggages:
        return "Carry-on only"
    parts = []
    for b in baggages:
        qty = b.get("quantity", 1)
        kind = b.get("type", "checked")
        if kind == "checked":
            parts.append(f"{qty}× 23kg checked")
        else:
            parts.append(f"{qty}× {kind}")
    return ", ".join(parts)


def _hhmm(iso_ts: str) -> str:
    # "2026-06-01T11:50:00" → "11:50"
    return iso_ts[11:16]


def _hour(iso_ts: str) -> int:
    return int(iso_ts[11:13])


def _to_offer(d: dict[str, Any]) -> FlightOffer:
    try:
        sl = d["slices"][0]
        seg = sl["segments"][0]
        pax = seg["passengers"][0]
        return FlightOffer(
            id=d["id"],
            origin=sl["origin"]["iata_code"],
            destination=sl["destination"]["iata_code"],
            airline=d["owner"]["name"],
            price=float(d["total_amount"]),
            stops=max(0, len(sl["segments"]) - 1),
            duration=parse_iso8601_duration(sl["duration"]),
            departure_hour=_hour(seg["departing_at"]),
            departure_label=_hhmm(seg["departing_at"]),
            arrival_label=_hhmm(sl["segments"][-1]["arriving_at"]),
            cabin=_format_cabin(pax["cabin_class"]),
            baggage=_format_baggage(pax.get("baggages", [])),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # TypeError covers float(None) when total_amount is missing-typed;
        # ValueError covers float("abc") on malformed numerics.
        raise DuffelError(kind="bad_response", detail=str(exc)) from exc


class DuffelClient:
    def __init__(self, api_key: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str | None = None,
        passengers: int = 1,
        cabin: str = "economy",
    ) -> list[FlightOffer]:
        slices = [{"origin": origin, "destination": destination, "departure_date": depart_date}]
        if return_date:
            slices.append({"origin": destination, "destination": origin, "departure_date": return_date})
        body = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": cabin,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(
                    f"{_DUFFEL_BASE}/air/offer_requests?return_offers=true",
                    headers=self._headers,
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise DuffelError(kind="timeout", detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise DuffelError(kind="upstream", detail=str(exc)) from exc

        if r.status_code in (401, 403):
            raise DuffelError(kind="auth", detail="DUFFEL_API_KEY invalid")
        if r.status_code == 422:
            raise DuffelError(kind="bad_request", detail=_first_error(r))
        if r.status_code == 429:
            # Retry-After can be either delta-seconds or HTTP-date. We only
            # honor the seconds form; anything else falls back to 60.
            try:
                retry = int(r.headers.get("Retry-After", "60"))
            except ValueError:
                retry = 60
            raise DuffelError(kind="rate_limit", retry_after=retry)
        if r.status_code >= 500:
            raise DuffelError(kind="upstream", detail=f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise DuffelError(kind="bad_request", detail=_first_error(r))

        try:
            offers = r.json()["data"]["offers"]
        except (KeyError, ValueError) as exc:
            raise DuffelError(kind="bad_response", detail=str(exc)) from exc

        parsed = [_to_offer(o) for o in offers]
        parsed.sort(key=lambda o: o.price)
        return parsed[:6]


def _first_error(r: httpx.Response) -> str:
    try:
        errs = r.json().get("errors") or []
        return errs[0].get("message") if errs else ""
    except Exception:
        return ""
