"""What a person has connected, over HTTP, for the assistant's tool.

Internal only and mounted once, like every other endpoint that acts for a
named user. Read only, so there is nothing here to confirm and nothing it
can break.
"""
import logging

from fastapi import APIRouter, Header

from account_summary import summarise
from routes_gateway import _require_internal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account")


@router.get("/summary")
async def summary(user_email: str,
                  x_internal_secret: str = Header(default="")) -> dict:
    """What this person has connected, and how to connect the rest."""
    _require_internal(x_internal_secret)
    return await summarise(user_email)
