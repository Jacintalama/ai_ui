# Claude Desktop + Calendar + Transcripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable 4 team members to use all MCP tools from Claude Desktop, add Google Calendar for standup scheduling, and auto-process Fathom meeting transcripts.

**Architecture:** Hub-and-spoke. New Caddy route exposes MCP proxy externally with API key auth. New `mcp-calendar` container for Google Calendar. n8n workflow for Fathom transcript processing.

**Tech Stack:** FastAPI, asyncpg, httpx, Google Calendar API, Docker, Caddy, n8n

---

## Task 1: MCP Auth Middleware for Claude Desktop

**Files:**
- Create: `mcp-auth/main.py`
- Create: `mcp-auth/Dockerfile`
- Create: `mcp-auth/requirements.txt`
- Modify: `Caddyfile`
- Modify: `docker-compose.unified.yml`

### Step 1: Create requirements.txt

Create `mcp-auth/requirements.txt`:
```
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.25.0
asyncpg>=0.29.0
```

### Step 2: Create the auth middleware

Create `mcp-auth/main.py`:
```python
"""MCP Auth Middleware — API key validation for external MCP clients (Claude Desktop)."""
import os
import hashlib
import secrets
import asyncpg
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

app = FastAPI(title="MCP Auth Middleware")

DATABASE_URL = os.getenv("DATABASE_URL", "")
MCP_PROXY_URL = os.getenv("MCP_PROXY_URL", "http://mcp-proxy:8000")

_pool = None


async def get_pool():
    global _pool
    if _pool is None and DATABASE_URL:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


@app.on_event("startup")
async def startup():
    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mcp_api_keys (
                    api_key_hash TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    user_groups TEXT NOT NULL DEFAULT 'MCP-Admin',
                    label TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        print(f"[MCP Auth] Database ready, proxying to {MCP_PROXY_URL}")


async def validate_api_key(api_key: str) -> dict:
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    key_hash = hash_key(api_key)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_email, user_groups, label FROM mcp_api_keys WHERE api_key_hash = $1",
            key_hash,
        )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"email": row["user_email"], "groups": row["user_groups"], "label": row["label"]}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    # Extract API key from Authorization header
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <api-key>")
    api_key = auth[7:]

    # Validate key and get user info
    user = await validate_api_key(api_key)

    # Forward to MCP proxy with user headers
    body = await request.body()
    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
        "X-User-Email": user["email"],
        "X-User-Groups": user["groups"],
        "X-User-Admin": "true",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.request(
            method=request.method,
            url=f"{MCP_PROXY_URL}/{path}",
            content=body,
            headers=headers,
        )

    return JSONResponse(
        content=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text},
        status_code=resp.status_code,
        headers={"Content-Type": resp.headers.get("content-type", "application/json")},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-auth"}


# --- Admin: Generate API keys ---

@app.post("/admin/generate-key")
async def generate_key(request: Request):
    """Generate a new API key for a user. Call from server only."""
    data = await request.json()
    email = data.get("email", "")
    groups = data.get("groups", "MCP-Admin")
    label = data.get("label", "")
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    api_key = f"sk-{secrets.token_urlsafe(32)}"
    key_hash = hash_key(api_key)

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO mcp_api_keys (api_key_hash, user_email, user_groups, label)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (api_key_hash) DO NOTHING""",
            key_hash, email, groups, label,
        )

    return {"api_key": api_key, "email": email, "groups": groups}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Step 3: Create Dockerfile

Create `mcp-auth/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 4: Add to docker-compose.unified.yml

Add after the mcp-proxy service:
```yaml
  # ===========================================================================
  # MCP AUTH - API key auth for Claude Desktop
  # ===========================================================================
  mcp-auth:
    build: ./mcp-auth
    container_name: mcp-auth
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      - MCP_PROXY_URL=http://mcp-proxy:8000
    networks:
      - backend
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 128M
```

### Step 5: Add Caddy route

Add to `Caddyfile` before the catch-all:
```caddyfile
# ---------------------------------------------------------------------------
# MCP Remote — Claude Desktop external access (API key auth)
# ---------------------------------------------------------------------------
handle /mcp-remote/* {
    uri strip_prefix /mcp-remote
    reverse_proxy mcp-auth:8000
}
```

### Step 6: Deploy and generate API keys

```bash
# Deploy
scp -r mcp-auth root@46.224.193.25:/root/proxy-server/mcp-auth
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/
scp Caddyfile root@46.224.193.25:/root/proxy-server/

ssh root@46.224.193.25 "cd /root/proxy-server && \
  docker compose -f docker-compose.unified.yml up -d --build mcp-auth && \
  docker compose -f docker-compose.unified.yml restart caddy"

# Generate 4 API keys
ssh root@46.224.193.25 "docker exec mcp-auth python -c \"
import httpx, asyncio, json
async def gen():
    async with httpx.AsyncClient() as c:
        for email, label in [
            ('lukas@straightforwardllc.us', 'Lukas'),
            ('ralphbenitez30@gmail.com', 'Ralph'),
            ('alamajacintg04@gmail.com', 'Jacint'),
            ('clidebacalla@gmail.com', 'Clarenz'),
        ]:
            r = await c.post('http://localhost:8000/admin/generate-key',
                json={'email': email, 'groups': 'MCP-Admin', 'label': label})
            print(json.dumps(r.json()))
asyncio.run(gen())
\""
```

### Step 7: Test from local machine

```bash
curl -X POST https://ai-ui.coolestdomain.win/mcp-remote/health
# Expected: {"status":"ok","service":"mcp-auth"}

curl -X POST https://ai-ui.coolestdomain.win/mcp-remote/mcp \
  -H "Authorization: Bearer sk-jacint-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# Expected: JSON-RPC response with server capabilities
```

### Step 8: Commit

```bash
git add mcp-auth/ Caddyfile docker-compose.unified.yml
git commit -m "feat: add MCP auth middleware for Claude Desktop external access"
```

---

## Task 2: Google Calendar MCP Server

**Files:**
- Create: `mcp-servers/calendar/main.py`
- Create: `mcp-servers/calendar/Dockerfile`
- Create: `mcp-servers/calendar/requirements.txt`
- Modify: `docker-compose.unified.yml`
- Modify: `mcp-proxy/tenants.py`
- Modify: `Caddyfile`

### Step 1: Create requirements.txt

Create `mcp-servers/calendar/requirements.txt`:
```
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.25.0
pydantic>=2.0.0
asyncpg>=0.29.0
```

### Step 2: Create the Calendar MCP server

Create `mcp-servers/calendar/main.py`:
```python
"""Google Calendar MCP Server — Create events, send invites, manage calendar."""
import os
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field
import httpx

app = FastAPI(
    title="Calendar MCP",
    description="""Create and manage Google Calendar events.

Tool Usage Guidelines for AI:
- calendar_create_event: Create a new event (with optional attendees and Google Meet)
- calendar_list_events: List upcoming events for a date range
- calendar_send_invite: Create event AND send email invites to attendees
- calendar_update_event: Modify an existing event
- calendar_delete_event: Cancel an event and notify attendees
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
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
DATABASE_URL = os.getenv("DATABASE_URL", "")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"

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
                    user_email,
                )
                if row:
                    return {
                        "access_token": row["access_token"],
                        "refresh_token": row["refresh_token"],
                        "token_expiry": row["token_expiry"].isoformat() if row["token_expiry"] else None,
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
                        token_expiry TIMESTAMP,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
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
        except Exception as e:
            print(f"[Calendar] DB save error: {e}")


async def refresh_access_token(user_email: str, refresh_token: str) -> Optional[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    if resp.status_code != 200:
        return None
    data = resp.json()
    await save_token(user_email, {
        "access_token": data["access_token"],
        "refresh_token": refresh_token,
    })
    return data["access_token"]


async def get_valid_token(user_email: str) -> Optional[str]:
    token = await get_token(user_email)
    if not token:
        return None
    # Try the access token first
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CALENDAR_API}/calendars/primary",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
    if resp.status_code == 200:
        return token["access_token"]
    # Try refresh
    if token.get("refresh_token"):
        return await refresh_access_token(user_email, token["refresh_token"])
    return None


def get_user_email(request: Request) -> str:
    return (
        request.headers.get("x-user-email")
        or request.headers.get("X-User-Email")
        or "default@local"
    )


NOT_CONNECTED_MSG = (
    "Google Calendar is not connected. "
    "Please connect at: {base_url}/auth/google/start?user_email={email}"
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
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": OAUTH_REDIRECT_URI,
        })
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {resp.text}")
    data = resp.json()
    await save_token(user_email, {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
    })
    return HTMLResponse(f"""
    <html><body style="font-family:sans-serif;text-align:center;padding:50px;background:#1e1e1e;color:#fff;">
        <h1 style="color:#4285f4;">Google Calendar Connected!</h1>
        <p>Calendar is now connected for <strong>{user_email}</strong>.</p>
        <p>You can close this window.</p>
        <script>setTimeout(function(){{ window.close(); }}, 2000);</script>
    </body></html>
    """)


@app.get("/auth/google/status")
async def auth_status(user_email: str = "default@local"):
    token = await get_valid_token(user_email)
    return {"connected": token is not None, "user_email": user_email}


# --- Pydantic Models ---

class CreateEventInput(BaseModel):
    title: str = Field(description="Event title/summary")
    start_time: str = Field(description="Start time in ISO 8601 format (e.g. 2026-03-28T21:30:00+08:00)")
    duration_minutes: int = Field(default=30, description="Duration in minutes")
    description: str = Field(default="", description="Event description")
    attendees: list[str] = Field(default=[], description="List of email addresses to invite")
    recurrence: str = Field(default="", description="RRULE string (e.g. RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR)")
    add_google_meet: bool = Field(default=False, description="Add Google Meet video conference link")
    timezone: str = Field(default="Asia/Manila", description="Timezone for the event")


class ListEventsInput(BaseModel):
    time_min: str = Field(default="", description="Start of date range (ISO 8601). Defaults to now.")
    time_max: str = Field(default="", description="End of date range (ISO 8601). Defaults to 7 days from now.")
    max_results: int = Field(default=10, description="Maximum number of events to return")


class UpdateEventInput(BaseModel):
    event_id: str = Field(description="Google Calendar event ID")
    title: str = Field(default="", description="New title (leave empty to keep current)")
    start_time: str = Field(default="", description="New start time (ISO 8601)")
    duration_minutes: int = Field(default=0, description="New duration (0 to keep current)")
    description: str = Field(default="", description="New description")
    add_attendees: list[str] = Field(default=[], description="Additional attendees to add")


class DeleteEventInput(BaseModel):
    event_id: str = Field(description="Google Calendar event ID")
    notify_attendees: bool = Field(default=True, description="Send cancellation to attendees")


# --- Calendar Tool Endpoints ---

@app.post("/calendar_create_event", operation_id="calendar_create_event",
          summary="Create a Google Calendar event")
async def create_event(input: CreateEventInput, request: Request):
    """Create a calendar event. Use this when user wants to schedule a meeting, event, or reminder."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    start = datetime.fromisoformat(input.start_time)
    end = start + timedelta(minutes=input.duration_minutes)

    event_body = {
        "summary": input.title,
        "description": input.description,
        "start": {"dateTime": start.isoformat(), "timeZone": input.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": input.timezone},
    }

    if input.attendees:
        event_body["attendees"] = [{"email": e} for e in input.attendees]

    if input.recurrence:
        event_body["recurrence"] = [input.recurrence]

    if input.add_google_meet:
        event_body["conferenceData"] = {
            "createRequest": {"requestId": f"meet-{int(datetime.now().timestamp())}"}
        }

    params = {}
    if input.add_google_meet:
        params["conferenceDataVersion"] = 1

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event_body,
            params=params,
        )

    if resp.status_code not in (200, 201):
        return {"error": f"Failed to create event: {resp.text}"}

    data = resp.json()
    result = {
        "event_id": data["id"],
        "title": data.get("summary", ""),
        "link": data.get("htmlLink", ""),
        "start": data.get("start", {}).get("dateTime", ""),
        "end": data.get("end", {}).get("dateTime", ""),
    }

    meet_link = data.get("conferenceData", {}).get("entryPoints", [{}])
    if meet_link:
        for ep in meet_link:
            if ep.get("entryPointType") == "video":
                result["google_meet_link"] = ep.get("uri", "")

    if input.attendees:
        result["attendees_invited"] = input.attendees

    return result


@app.post("/calendar_send_invite", operation_id="calendar_send_invite",
          summary="Create event and send email invites")
async def send_invite(input: CreateEventInput, request: Request):
    """Create a calendar event AND send email invitations to all attendees.
    Same as calendar_create_event but always sends invite emails."""
    if not input.attendees:
        return {"error": "attendees list is required for sending invites"}
    input.add_google_meet = True  # Always add Meet link for invites

    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    start = datetime.fromisoformat(input.start_time)
    end = start + timedelta(minutes=input.duration_minutes)

    event_body = {
        "summary": input.title,
        "description": input.description,
        "start": {"dateTime": start.isoformat(), "timeZone": input.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": input.timezone},
        "attendees": [{"email": e} for e in input.attendees],
        "conferenceData": {
            "createRequest": {"requestId": f"meet-{int(datetime.now().timestamp())}"}
        },
    }

    if input.recurrence:
        event_body["recurrence"] = [input.recurrence]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event_body,
            params={"sendUpdates": "all", "conferenceDataVersion": 1},
        )

    if resp.status_code not in (200, 201):
        return {"error": f"Failed to create event: {resp.text}"}

    data = resp.json()
    result = {
        "event_id": data["id"],
        "title": data.get("summary", ""),
        "link": data.get("htmlLink", ""),
        "start": data.get("start", {}).get("dateTime", ""),
        "invites_sent_to": input.attendees,
    }

    for ep in data.get("conferenceData", {}).get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            result["google_meet_link"] = ep.get("uri", "")

    return result


@app.post("/calendar_list_events", operation_id="calendar_list_events",
          summary="List upcoming calendar events")
async def list_events(input: ListEventsInput, request: Request):
    """List upcoming events from Google Calendar. Shows title, time, attendees, and Meet links."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    now = datetime.utcnow().isoformat() + "Z"
    week_later = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

    params = {
        "timeMin": input.time_min or now,
        "timeMax": input.time_max or week_later,
        "maxResults": min(input.max_results, 50),
        "singleEvents": True,
        "orderBy": "startTime",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if resp.status_code != 200:
        return {"error": f"Failed to list events: {resp.text}"}

    events = []
    for item in resp.json().get("items", []):
        event = {
            "event_id": item["id"],
            "title": item.get("summary", "(no title)"),
            "start": item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "")),
            "end": item.get("end", {}).get("dateTime", item.get("end", {}).get("date", "")),
            "description": item.get("description", "")[:200],
            "attendees": [a.get("email", "") for a in item.get("attendees", [])],
            "link": item.get("htmlLink", ""),
        }
        for ep in item.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                event["google_meet_link"] = ep.get("uri", "")
        events.append(event)

    return {"event_count": len(events), "events": events}


@app.post("/calendar_update_event", operation_id="calendar_update_event",
          summary="Update an existing calendar event")
async def update_event(input: UpdateEventInput, request: Request):
    """Update an existing event — reschedule, rename, or add attendees."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Get current event
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CALENDAR_API}/calendars/primary/events/{input.event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        return {"error": f"Event not found: {resp.text}"}

    event_body = resp.json()

    if input.title:
        event_body["summary"] = input.title
    if input.description:
        event_body["description"] = input.description
    if input.start_time:
        start = datetime.fromisoformat(input.start_time)
        duration = input.duration_minutes or 30
        end = start + timedelta(minutes=duration)
        event_body["start"] = {"dateTime": start.isoformat(), "timeZone": "Asia/Manila"}
        event_body["end"] = {"dateTime": end.isoformat(), "timeZone": "Asia/Manila"}
    if input.add_attendees:
        existing = event_body.get("attendees", [])
        existing_emails = {a.get("email") for a in existing}
        for email in input.add_attendees:
            if email not in existing_emails:
                existing.append({"email": email})
        event_body["attendees"] = existing

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{CALENDAR_API}/calendars/primary/events/{input.event_id}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event_body,
            params={"sendUpdates": "all"},
        )

    if resp.status_code != 200:
        return {"error": f"Failed to update: {resp.text}"}

    data = resp.json()
    return {"event_id": data["id"], "title": data.get("summary", ""), "updated": True}


@app.post("/calendar_delete_event", operation_id="calendar_delete_event",
          summary="Delete a calendar event")
async def delete_event(input: DeleteEventInput, request: Request):
    """Cancel/delete a calendar event. Optionally notify attendees."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    params = {"sendUpdates": "all" if input.notify_attendees else "none"}

    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{CALENDAR_API}/calendars/primary/events/{input.event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if resp.status_code not in (200, 204):
        return {"error": f"Failed to delete: {resp.text}"}

    return {"event_id": input.event_id, "deleted": True, "attendees_notified": input.notify_attendees}


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
```

### Step 3: Create Dockerfile

Create `mcp-servers/calendar/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 4: Add to docker-compose.unified.yml

```yaml
  # ===========================================================================
  # MCP CALENDAR - Google Calendar Integration
  # ===========================================================================
  mcp-calendar:
    build: ./mcp-servers/calendar
    container_name: mcp-calendar
    restart: unless-stopped
    environment:
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - OAUTH_REDIRECT_URI=https://ai-ui.coolestdomain.win/calendar/auth/google/callback
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
    networks:
      - backend
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 256M
```

### Step 5: Add Caddy route

Add to `Caddyfile`:
```caddyfile
# ---------------------------------------------------------------------------
# Calendar MCP connector
# ---------------------------------------------------------------------------
handle /calendar/* {
    uri strip_prefix /calendar
    reverse_proxy mcp-calendar:8000
}
```

### Step 6: Register in tenants.py

Add to `mcp-proxy/tenants.py`:
```python
MCP_CALENDAR_URL = os.getenv("MCP_CALENDAR_URL", "http://mcp-calendar:8000")
```

And add to `LOCAL_SERVERS`:
```python
    "calendar": MCPServerConfig(
        server_id="calendar",
        display_name="Google Calendar",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_CALENDAR_URL,
        auth_type="none",
        api_key_env=None,
        description="Create events, send invites, manage Google Calendar (5 tools)",
        enabled=True,
    ),
```

### Step 7: Add Calendar scope to Google Cloud Console

**Manual step:** Go to Google Cloud Console → AIUI Project → APIs & Services → OAuth consent screen → Edit → Add scope: `https://www.googleapis.com/auth/calendar.events` and `https://www.googleapis.com/auth/calendar.readonly`

Also enable the **Google Calendar API** under APIs & Services → Library.

### Step 8: Deploy and test

```bash
scp -r mcp-servers/calendar root@46.224.193.25:/root/proxy-server/mcp-servers/calendar
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/
scp Caddyfile root@46.224.193.25:/root/proxy-server/
scp mcp-proxy/tenants.py root@46.224.193.25:/root/proxy-server/mcp-proxy/tenants.py

ssh root@46.224.193.25 "cd /root/proxy-server && \
  docker compose -f docker-compose.unified.yml up -d --build mcp-calendar && \
  docker compose -f docker-compose.unified.yml up -d --build mcp-proxy && \
  docker compose -f docker-compose.unified.yml restart caddy"

# Test health
curl https://ai-ui.coolestdomain.win/calendar/health
```

### Step 9: Connect shared Gmail account

Open browser: `https://ai-ui.coolestdomain.win/calendar/auth/google/start?user_email=aiui.teams@gmail.com`

Log in with `aiui.teams@gmail.com` → grant Calendar permissions.

### Step 10: Commit

```bash
git add mcp-servers/calendar/ mcp-proxy/tenants.py docker-compose.unified.yml Caddyfile
git commit -m "feat: add Google Calendar MCP server with event management"
```

---

## Task 3: Fathom Transcript Processing (n8n Workflow)

**Files:**
- Create: `n8n-workflows/fathom-transcript-processor.json`

### Step 1: Design the n8n workflow

Build this in the n8n UI (`https://ai-ui.coolestdomain.win/n8n`):

**Nodes:**
1. **Schedule Trigger** — every 15 minutes
2. **Gmail node** — search `aiui.teams@gmail.com` for unread emails from Fathom (query: `from:notifications@fathom.video is:unread`)
3. **IF node** — check if any emails found
4. **HTTP Request** — fetch transcript content from Fathom link in email body
5. **HTTP Request** — send transcript to Open WebUI chat API for summarization
6. **HTTP Request** — save full transcript + summary to Knowledge Base (`POST http://mcp-web-search:8000/web_save_to_kb` or direct KB API)
7. **Discord node** — post summary to #general channel
8. **Gmail node** — mark email as read

### Step 2: Create and publish in n8n

This is a manual step in the n8n UI. Export the workflow JSON after building.

### Step 3: Test with a real Fathom email

After next standup, verify:
- Email detected by workflow
- Transcript extracted
- Summary generated and saved to KB
- Discord notification sent

### Step 4: Commit workflow JSON

```bash
git add n8n-workflows/fathom-transcript-processor.json
git commit -m "feat: add Fathom transcript processing n8n workflow"
```

---

## Task 4: Claude Desktop Config Distribution

**Files:**
- Create: `docs/claude-desktop-setup.md`

### Step 1: Write setup guide

Create `docs/claude-desktop-setup.md` with instructions for each team member:

```markdown
# Claude Desktop Setup — AIUI MCP Tools

## Install Claude Desktop
Download from: https://claude.ai/download

## Configure MCP Connection
1. Open Claude Desktop → Settings → Developer → Edit Config
2. Add this to your `claude_desktop_config.json`:

\`\`\`json
{
  "mcpServers": {
    "aiui": {
      "type": "streamableHttp",
      "url": "https://ai-ui.coolestdomain.win/mcp-remote/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY_HERE"
      }
    }
  }
}
\`\`\`

3. Replace YOUR_API_KEY_HERE with your personal key (ask Jacint)
4. Restart Claude Desktop

## Available Tools
- **Gmail** — search, read, send emails (via aiui.teams@gmail.com)
- **Google Calendar** — create events, send invites, list schedule
- **GitHub** — repos, issues, PRs
- **Web Search** — search internet, save to Knowledge Base
- **Google Drive** — browse, search files
- **n8n Workflows** — trigger automations
- **30+ more tools**

## Example Commands
- "Create a standup meeting for tomorrow at 9:30 PM and invite the team"
- "Search my inbox for emails from Lukas"
- "What's on my calendar this week?"
- "Search for AI voice bot best practices and save to KB"
```

### Step 2: Commit

```bash
git add docs/claude-desktop-setup.md
git commit -m "docs: add Claude Desktop setup guide for team"
```

---

## Implementation Order

| # | Task | Depends On | Estimated Effort |
|---|------|------------|-----------------|
| 1 | MCP Auth Middleware | None | Medium |
| 2 | Google Calendar MCP Server | Google Cloud Console setup | Medium |
| 3 | Fathom Transcript Workflow | None (parallel) | Low |
| 4 | Claude Desktop Config | Task 1 (needs API keys) | Low |

Tasks 1 and 2 can be built in parallel. Task 3 is independent. Task 4 is last (needs Task 1 deployed).
