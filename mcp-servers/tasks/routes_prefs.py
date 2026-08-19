"""Per-user preferences. Today that means: what time is it where you are.

The zone is detected in the browser (integrations-ui.js) and posted here on
load, so the user is never asked. The Open WebUI inlet filter reads it back and
puts the local time in front of every model.

The rules about what a valid zone is, and when a detected one may overwrite a
stored one, live in user_timezone.py and are not restated here.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import user_timezone
from auth import current_user, CurrentUser

logger = logging.getLogger("tasks.prefs")

router = APIRouter(prefix="/prefs")

DATABASE_URL = os.environ.get("DATABASE_URL", "")


async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


class TimezoneIn(BaseModel):
    timezone: str
    #: True when the user picked the zone themselves. A hand-picked zone is
    #: never overwritten by the browser on the next page load.
    manual: bool = False


async def read_timezone(email: str) -> tuple:
    """(timezone, source) for a user, or (None, None). Never raises."""
    try:
        conn = await _connect()
    except Exception as e:
        logger.warning("prefs: connect failed: %s", e)
        return None, None
    try:
        row = await conn.fetchrow(
            "SELECT timezone, tz_source FROM tasks.user_prefs WHERE email = $1",
            email)
    except Exception as e:
        logger.warning("prefs: read failed: %s", e)
        return None, None
    finally:
        await conn.close()
    if not row:
        return None, None
    return row["timezone"], row["tz_source"]


@router.get("/timezone")
async def get_timezone(user: CurrentUser = Depends(current_user)):
    """The signed-in user's zone. Reports the fallback rather than null, so a
    caller never has to know what the platform default is."""
    tz, source = await read_timezone(user.email)
    return {
        "timezone": tz or user_timezone.DEFAULT_TZ,
        "source": source or "default",
        "detected": bool(tz),
    }


@router.post("/timezone")
async def set_timezone(body: TimezoneIn,
                       user: CurrentUser = Depends(current_user)):
    """Store a zone for the signed-in user.

    Called unattended by the browser on page load, so an unrecognised name is
    refused outright: every value in the table is then known to resolve, and
    the filter that reads it never has to defend against the database.
    """
    tz = user_timezone.normalise_timezone(body.timezone)
    if tz is None:
        raise HTTPException(status_code=400,
                            detail="Not a recognised IANA timezone name.")

    _, stored_source = await read_timezone(user.email)
    if not user_timezone.should_store(stored_source, body.manual):
        return {"timezone": None, "stored": False, "reason": "manual-preserved"}

    source = "manual" if body.manual else "auto"
    try:
        conn = await _connect()
    except Exception as e:
        logger.warning("prefs: connect failed: %s", e)
        raise HTTPException(status_code=503, detail="Preferences unavailable.")
    try:
        await conn.execute(
            """
            INSERT INTO tasks.user_prefs (email, timezone, tz_source, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (email) DO UPDATE
                SET timezone = EXCLUDED.timezone,
                    tz_source = EXCLUDED.tz_source,
                    updated_at = now()
            """,
            user.email, tz, source)
    except Exception as e:
        logger.warning("prefs: write failed: %s", e)
        raise HTTPException(status_code=503, detail="Preferences unavailable.")
    finally:
        await conn.close()
    return {"timezone": tz, "source": source, "stored": True}


@router.get("/context")
async def timezone_context(user: CurrentUser = Depends(current_user)):
    """What the Open WebUI inlet filter injects.

    Returns the zone alongside the rendered line so the filter can cache the
    zone and compute the timestamp itself, instead of calling back here on
    every single chat turn.
    """
    tz, _ = await read_timezone(user.email)
    return {"timezone": tz, "line": user_timezone.context_line(tz)}
