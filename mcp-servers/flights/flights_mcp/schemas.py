"""Pydantic models for the search_flights tool I/O.

FlightOffer matches the existing flight-booking template's flight shape
(see template_apps/flight-booking/src/data.js) so the agent can drop the
result straight into src/data.js after camelCase-ing the field names.
"""
from typing import Literal
from pydantic import BaseModel


class FlightOffer(BaseModel):
    id: str
    origin: str
    destination: str
    airline: str
    price: float
    stops: int
    duration: int            # minutes
    departure_hour: int      # 0-23, local airport tz
    departure_label: str     # "HH:MM"
    arrival_label: str       # "HH:MM"
    cabin: Literal["Economy", "Premium Economy", "Business", "First"]
    baggage: str             # e.g. "1× 23kg checked"
