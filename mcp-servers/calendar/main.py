"""Google Calendar MCP Server — create events, send invites, list, update, and delete calendar events."""
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Google Calendar MCP",
    description="""Create events, send invites, and manage your Google Calendar.

IMPORTANT - Tool Usage Guidelines for AI:
- When user wants to CREATE an event: use calendar_create_event
- When user wants to SEND an invite / schedule a meeting: use calendar_send_invite
- When user wants to LIST or VIEW events: use calendar_list_events
- When user wants to UPDATE or RESCHEDULE an event: use calendar_update_event
- When user wants to DELETE or CANCEL an event: use calendar_delete_event

Always confirm event details (title, time, attendees) with the user before creating or sending invites.
""",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8007/auth/google/callback")
DATABASE_URL = os.getenv("DATABASE_URL", "")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"

# In-memory token store (dev); PostgreSQL for prod
_tokens: dict = {}


# --- Token Management (same pattern as Gmail) ---

async def get_token(user_email: str) -> Optional[dict]:
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    "SELECT access_token, refresh_token, token_expiry FROM calendar_tokens WHERE user_email = $1",
                    user_email
                )
                if row:
                    return {
                        "access_token": row["access_token"],
                        "refresh_token": row["refresh_token"],
                        "token_expiry": row["token_expiry"].isoformat() if row["token_expiry"] else None
                    }
            finally:
                await conn.close()
        except Exception:
            pass
    return _tokens.get(user_email)


async def save_token(user_email: str, token_data: dict):
    _tokens[user_email] = token_data
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS calendar_tokens (
                        user_email TEXT PRIMARY KEY,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT,
                        token_expiry TIMESTAMPTZ DEFAULT NOW() + INTERVAL '1 hour',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                await conn.execute("""
                    INSERT INTO calendar_tokens (user_email, access_token, refresh_token, token_expiry)
                    VALUES ($1, $2, $3, NOW() + INTERVAL '1 hour')
                    ON CONFLICT (user_email) DO UPDATE
                    SET access_token = $2, refresh_token = COALESCE($3, calendar_tokens.refresh_token),
                        token_expiry = NOW() + INTERVAL '1 hour', updated_at = NOW()
                """, user_email, token_data["access_token"], token_data.get("refresh_token"))
            finally:
                await conn.close()
        except Exception:
            pass


async def refresh_access_token(user_email: str) -> Optional[str]:
    token = await get_token(user_email)
    if not token or not token.get("refresh_token"):
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            })
            if resp.status_code == 200:
                data = resp.json()
                token["access_token"] = data["access_token"]
                await save_token(user_email, token)
                return data["access_token"]
    except Exception:
        pass
    return None


async def get_valid_token(user_email: str) -> Optional[str]:
    token = await get_token(user_email)
    if not token:
        return None
    # Test token
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CALENDAR_API}/calendars/primary",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return token["access_token"]
    except Exception:
        pass
    # Try refresh
    new_token = await refresh_access_token(user_email)
    if not new_token:
        _tokens.pop(user_email, None)
        if DATABASE_URL:
            try:
                import asyncpg
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    await conn.execute("DELETE FROM calendar_tokens WHERE user_email = $1", user_email)
                finally:
                    await conn.close()
            except Exception:
                pass
    return new_token


def get_user_email(request: Request) -> str:
    return (
        request.headers.get("x-user-email")
        or request.headers.get("X-User-Email")
        or "default@local"
    )


NOT_CONNECTED_MSG = (
    "Google Calendar is not connected. Please visit the following URL to connect:\n\n"
    "{base_url}/auth/google/start?user_email={email}\n\n"
    "After connecting, try again."
)


# --- OAuth Endpoints ---

@app.get("/auth/google/start")
async def auth_start(user_email: str = "default@local"):
    state = urllib.parse.quote(user_email)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/google/callback")
async def auth_callback(code: str, state: str = "default@local"):
    user_email = urllib.parse.unquote(state)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": OAUTH_REDIRECT_URI,
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token exchange request failed: {str(e)}")
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {resp.text}")
    data = resp.json()
    await save_token(user_email, {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
    })
    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px; background: #1e1e1e; color: #fff;">
        <h1 style="color: #4285f4;">Google Calendar Connected!</h1>
        <p>Your Google Calendar is now connected for <strong>{user_email}</strong>.</p>
        <p>This window will close automatically...</p>
        <script>
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'aiui-calendar-connected',
                    email: '{user_email}',
                    connected: true
                }}, '*');
            }}
            setTimeout(function() {{ window.close(); }}, 1500);
        </script>
    </body></html>
    """)


@app.get("/auth/google/status")
async def auth_status(user_email: str = "default@local"):
    token = await get_token(user_email)
    return {"connected": token is not None, "user_email": user_email}


@app.post("/auth/google/disconnect")
async def auth_disconnect(user_email: str = "default@local"):
    _tokens.pop(user_email, None)
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute("DELETE FROM calendar_tokens WHERE user_email = $1", user_email)
            finally:
                await conn.close()
        except Exception:
            pass
    return {"disconnected": True, "user_email": user_email}


# --- Calendar Helpers ---

async def calendar_request(
    access_token: str,
    path: str,
    params: dict = None,
    method: str = "GET",
    json_body: dict = None,
    timeout: float = 30.0,
) -> dict:
    """Make a request to the Google Calendar API."""
    url = f"{CALENDAR_API}/{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params or {}, timeout=timeout)
            elif method == "POST":
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, json=json_body or {}, timeout=timeout)
            elif method == "PUT":
                headers["Content-Type"] = "application/json"
                resp = await client.put(url, headers=headers, json=json_body or {}, timeout=timeout)
            elif method == "PATCH":
                headers["Content-Type"] = "application/json"
                resp = await client.patch(url, headers=headers, json=json_body or {}, timeout=timeout)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params or {}, timeout=timeout)
                # DELETE returns 204 No Content on success
                if resp.status_code == 204:
                    return {"deleted": True}
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported HTTP method: {method}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Google Calendar API request timed out")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Google Calendar API request failed: {str(e)}")

        if resp.status_code not in (200, 201, 204):
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        if resp.status_code == 204:
            return {"success": True}
        return resp.json()


def build_event_body(
    title: str,
    start_time: str,
    duration_minutes: int = 60,
    description: str = "",
    attendees: Optional[List[str]] = None,
    recurrence: Optional[str] = None,
    add_google_meet: bool = False,
    timezone: str = "Asia/Manila",
) -> dict:
    """Build a Google Calendar event body from parameters."""
    # Parse start_time as ISO 8601
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid start_time format: {start_time}. Use ISO 8601 (e.g., 2026-03-31T14:00:00).")

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event = {
        "summary": title,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone,
        },
    }

    if description:
        event["description"] = description

    if attendees:
        event["attendees"] = [{"email": email.strip()} for email in attendees]

    if recurrence:
        # Recurrence should be an RRULE string like "RRULE:FREQ=WEEKLY;COUNT=10"
        if not recurrence.startswith("RRULE:"):
            recurrence = f"RRULE:{recurrence}"
        event["recurrence"] = [recurrence]

    if add_google_meet:
        event["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet-{start_dt.timestamp():.0f}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    return event


def format_event(event: dict) -> dict:
    """Format a Google Calendar event for response."""
    start = event.get("start", {})
    end = event.get("end", {})

    attendees = []
    for a in event.get("attendees", []):
        attendees.append({
            "email": a.get("email", ""),
            "response_status": a.get("responseStatus", ""),
            "organizer": a.get("organizer", False),
        })

    # Extract Google Meet link
    google_meet_link = None
    conference_data = event.get("conferenceData", {})
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            google_meet_link = entry_point.get("uri")
            break

    return {
        "event_id": event.get("id", ""),
        "title": event.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "description": event.get("description", ""),
        "attendees": attendees,
        "google_meet_link": google_meet_link,
        "html_link": event.get("htmlLink", ""),
        "status": event.get("status", ""),
        "location": event.get("location", ""),
        "recurring_event_id": event.get("recurringEventId", ""),
    }


# --- Tool Models ---

class CreateEventInput(BaseModel):
    title: str = Field(description="Event title/summary")
    start_time: str = Field(description="Event start time in ISO 8601 format (e.g., 2026-03-31T14:00:00)")
    duration_minutes: int = Field(default=60, description="Event duration in minutes (default 60)")
    description: str = Field(default="", description="Event description/notes")
    attendees: Optional[List[str]] = Field(default=None, description="List of attendee email addresses")
    recurrence: Optional[str] = Field(default=None, description="Recurrence rule (RRULE string, e.g., FREQ=WEEKLY;COUNT=10)")
    add_google_meet: bool = Field(default=False, description="Add a Google Meet video conference link")
    timezone: str = Field(default="Asia/Manila", description="Timezone for the event (default Asia/Manila)")


class SendInviteInput(BaseModel):
    title: str = Field(description="Meeting title/summary")
    start_time: str = Field(description="Meeting start time in ISO 8601 format (e.g., 2026-03-31T14:00:00)")
    duration_minutes: int = Field(default=60, description="Meeting duration in minutes (default 60)")
    description: str = Field(default="", description="Meeting description/agenda")
    attendees: List[str] = Field(description="List of attendee email addresses (required for invites)")
    recurrence: Optional[str] = Field(default=None, description="Recurrence rule (RRULE string, e.g., FREQ=WEEKLY;COUNT=10)")
    timezone: str = Field(default="Asia/Manila", description="Timezone for the meeting (default Asia/Manila)")


class ListEventsInput(BaseModel):
    time_min: Optional[str] = Field(default=None, description="Start of time range in ISO 8601 (defaults to now)")
    time_max: Optional[str] = Field(default=None, description="End of time range in ISO 8601 (defaults to 7 days from now)")
    max_results: int = Field(default=25, description="Maximum number of events to return (max 100)")


class UpdateEventInput(BaseModel):
    event_id: str = Field(description="Google Calendar event ID to update")
    title: Optional[str] = Field(default=None, description="New event title")
    start_time: Optional[str] = Field(default=None, description="New start time in ISO 8601 format")
    duration_minutes: Optional[int] = Field(default=None, description="New duration in minutes")
    description: Optional[str] = Field(default=None, description="New event description")
    add_attendees: Optional[List[str]] = Field(default=None, description="Additional attendee emails to add")


class DeleteEventInput(BaseModel):
    event_id: str = Field(description="Google Calendar event ID to delete")
    notify_attendees: bool = Field(default=True, description="Send cancellation notifications to attendees")


# --- Tool Endpoints ---

@app.post("/calendar_create_event", operation_id="calendar_create_event", summary="Create a Google Calendar event")
async def create_event(input: CreateEventInput, request: Request):
    """Create a new event on your Google Calendar. Use this when the user asks to create an event, add something to their calendar, or schedule time for themselves. Supports optional attendees, recurrence, and Google Meet links."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    event_body = build_event_body(
        title=input.title,
        start_time=input.start_time,
        duration_minutes=input.duration_minutes,
        description=input.description,
        attendees=input.attendees,
        recurrence=input.recurrence,
        add_google_meet=input.add_google_meet,
        timezone=input.timezone,
    )

    # Use conferenceDataVersion=1 if adding Google Meet
    params = {}
    if input.add_google_meet:
        params["conferenceDataVersion"] = "1"

    path = "calendars/primary/events"
    if params:
        path += "?" + urllib.parse.urlencode(params)

    result = await calendar_request(access_token, path, method="POST", json_body=event_body)
    formatted = format_event(result)

    return {
        "success": True,
        "message": f"Event '{input.title}' created successfully.",
        "event": formatted,
    }


@app.post("/calendar_send_invite", operation_id="calendar_send_invite", summary="Create event and send meeting invites")
async def send_invite(input: SendInviteInput, request: Request):
    """Create a calendar event and send email invitations to all attendees. ALWAYS use this when the user wants to schedule a meeting, send invites, or set up a call with others. Always includes Google Meet link. Requires at least one attendee email."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    if not input.attendees:
        return {"error": "At least one attendee email is required to send an invite."}

    event_body = build_event_body(
        title=input.title,
        start_time=input.start_time,
        duration_minutes=input.duration_minutes,
        description=input.description,
        attendees=input.attendees,
        recurrence=input.recurrence,
        add_google_meet=True,  # Always add Google Meet for invites
        timezone=input.timezone,
    )

    # sendUpdates=all sends email notifications to all attendees
    # conferenceDataVersion=1 enables Google Meet creation
    params = {"sendUpdates": "all", "conferenceDataVersion": "1"}
    path = "calendars/primary/events?" + urllib.parse.urlencode(params)

    result = await calendar_request(access_token, path, method="POST", json_body=event_body)
    formatted = format_event(result)

    return {
        "success": True,
        "message": f"Meeting '{input.title}' created and invitations sent to {len(input.attendees)} attendee(s).",
        "event": formatted,
    }


@app.post("/calendar_list_events", operation_id="calendar_list_events", summary="List upcoming Google Calendar events")
async def list_events(input: ListEventsInput, request: Request):
    """List events from your Google Calendar within a time range. Use this when the user asks to see their schedule, upcoming events, calendar for a specific day/week, or what meetings they have. Defaults to showing the next 7 days."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    now = datetime.now(timezone.utc)

    # Default time range: now to 7 days from now
    time_min = input.time_min or now.isoformat()
    time_max = input.time_max or (now + timedelta(days=7)).isoformat()

    # Ensure Z suffix for UTC if no timezone info
    if not time_min.endswith("Z") and "+" not in time_min and "-" not in time_min[10:]:
        time_min += "Z"
    if not time_max.endswith("Z") and "+" not in time_max and "-" not in time_max[10:]:
        time_max += "Z"

    max_results = min(input.max_results, 100)

    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": max_results,
        "singleEvents": "true",
        "orderBy": "startTime",
    }

    result = await calendar_request(access_token, "calendars/primary/events", params=params)
    events = result.get("items", [])

    formatted_events = [format_event(e) for e in events]

    return {
        "time_range": {"from": time_min, "to": time_max},
        "event_count": len(formatted_events),
        "events": formatted_events,
    }


@app.post("/calendar_update_event", operation_id="calendar_update_event", summary="Update an existing Google Calendar event")
async def update_event(input: UpdateEventInput, request: Request):
    """Update an existing event on your Google Calendar. Use this when the user wants to reschedule, rename, change the description, or add attendees to an existing event. Requires the event_id (from calendar_list_events)."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Get current event first
    try:
        current_event = await calendar_request(access_token, f"calendars/primary/events/{input.event_id}")
    except HTTPException as e:
        if e.status_code == 404:
            return {"error": f"Event not found: {input.event_id}"}
        raise

    # Merge changes
    if input.title is not None:
        current_event["summary"] = input.title

    if input.description is not None:
        current_event["description"] = input.description

    if input.start_time is not None:
        try:
            start_dt = datetime.fromisoformat(input.start_time.replace("Z", "+00:00"))
        except ValueError:
            return {"error": f"Invalid start_time format: {input.start_time}. Use ISO 8601."}

        duration = input.duration_minutes or 60
        # Try to preserve original duration if not explicitly changed
        if input.duration_minutes is None:
            try:
                orig_start = datetime.fromisoformat(
                    current_event["start"].get("dateTime", "").replace("Z", "+00:00")
                )
                orig_end = datetime.fromisoformat(
                    current_event["end"].get("dateTime", "").replace("Z", "+00:00")
                )
                duration = int((orig_end - orig_start).total_seconds() / 60)
            except (ValueError, KeyError):
                duration = 60

        end_dt = start_dt + timedelta(minutes=duration)
        tz = current_event.get("start", {}).get("timeZone", "Asia/Manila")
        current_event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz}
        current_event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}
    elif input.duration_minutes is not None:
        # Only duration changed, keep same start time
        try:
            start_dt = datetime.fromisoformat(
                current_event["start"].get("dateTime", "").replace("Z", "+00:00")
            )
            end_dt = start_dt + timedelta(minutes=input.duration_minutes)
            tz = current_event.get("start", {}).get("timeZone", "Asia/Manila")
            current_event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}
        except (ValueError, KeyError):
            return {"error": "Could not update duration: unable to parse current event start time."}

    if input.add_attendees:
        existing_attendees = current_event.get("attendees", [])
        existing_emails = {a.get("email", "").lower() for a in existing_attendees}
        for email in input.add_attendees:
            if email.strip().lower() not in existing_emails:
                existing_attendees.append({"email": email.strip()})
        current_event["attendees"] = existing_attendees

    # Remove read-only fields that can't be sent in update
    for field in ["kind", "etag", "id", "status", "htmlLink", "created", "updated",
                   "creator", "organizer", "iCalUID", "sequence", "hangoutLink",
                   "recurringEventId", "originalStartTime"]:
        current_event.pop(field, None)

    # Send update with notifications
    params = {"sendUpdates": "all"}
    path = f"calendars/primary/events/{input.event_id}?" + urllib.parse.urlencode(params)

    result = await calendar_request(access_token, path, method="PUT", json_body=current_event)
    formatted = format_event(result)

    return {
        "success": True,
        "message": f"Event '{formatted['title']}' updated successfully.",
        "event": formatted,
    }


@app.post("/calendar_delete_event", operation_id="calendar_delete_event", summary="Delete a Google Calendar event")
async def delete_event(input: DeleteEventInput, request: Request):
    """Delete an event from your Google Calendar. Use this when the user wants to cancel, remove, or delete a calendar event. Requires the event_id (from calendar_list_events). Optionally sends cancellation notifications to attendees."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Get event details before deleting (for confirmation message)
    event_title = input.event_id
    try:
        current_event = await calendar_request(access_token, f"calendars/primary/events/{input.event_id}")
        event_title = current_event.get("summary", input.event_id)
    except HTTPException:
        pass  # Event might not be found, proceed with delete anyway

    params = {"sendUpdates": "all" if input.notify_attendees else "none"}
    path = f"calendars/primary/events/{input.event_id}?" + urllib.parse.urlencode(params)

    try:
        await calendar_request(access_token, path, method="DELETE")
    except HTTPException as e:
        if e.status_code == 404:
            return {"error": f"Event not found: {input.event_id}"}
        if e.status_code == 410:
            return {"error": f"Event already deleted: {input.event_id}"}
        raise

    return {
        "success": True,
        "message": f"Event '{event_title}' deleted successfully."
            + (" Cancellation notifications sent to attendees." if input.notify_attendees else ""),
        "event_id": input.event_id,
    }


# --- Health ---

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "calendar-mcp",
        "oauth_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
