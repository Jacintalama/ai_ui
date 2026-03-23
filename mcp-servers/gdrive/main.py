"""Google Drive MCP Server — browse and read files from Google Drive."""
import os
import json
import urllib.parse
from typing import Optional, List

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Google Drive MCP",
    description="Browse, search, and read files from your Google Drive.",
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
MAX_CONTENT_SIZE = 2 * 1024 * 1024  # 2MB limit

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = "https://www.googleapis.com/auth/drive.readonly"

# In-memory token store (for local dev; production would use PostgreSQL)
_tokens: dict = {}


# --- Token Management ---

async def get_token(user_email: str) -> Optional[dict]:
    """Get stored token for a user."""
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    "SELECT access_token, refresh_token, token_expiry FROM gdrive_tokens WHERE user_email = $1",
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
    """Save token for a user."""
    _tokens[user_email] = token_data
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute("""
                    INSERT INTO gdrive_tokens (user_email, access_token, refresh_token, token_expiry)
                    VALUES ($1, $2, $3, NOW() + INTERVAL '1 hour')
                    ON CONFLICT (user_email) DO UPDATE
                    SET access_token = $2, refresh_token = COALESCE($3, gdrive_tokens.refresh_token),
                        token_expiry = NOW() + INTERVAL '1 hour', updated_at = NOW()
                """, user_email, token_data["access_token"], token_data.get("refresh_token"))
            finally:
                await conn.close()
        except Exception:
            pass


async def refresh_access_token(user_email: str) -> Optional[str]:
    """Refresh an expired access token."""
    token = await get_token(user_email)
    if not token or not token.get("refresh_token"):
        return None

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
    return None


async def get_valid_token(user_email: str) -> Optional[str]:
    """Get a valid access token, refreshing if needed."""
    token = await get_token(user_email)
    if not token:
        return None

    # Try the current token first
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_DRIVE_API}/about?fields=user",
            headers={"Authorization": f"Bearer {token['access_token']}"}
        )
        if resp.status_code == 200:
            return token["access_token"]

    # Token expired, try refresh
    new_token = await refresh_access_token(user_email)

    # If refresh also failed, clear the token so UI shows "Connect"
    if not new_token:
        _tokens.pop(user_email, None)
        if DATABASE_URL:
            try:
                import asyncpg
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    await conn.execute("DELETE FROM gdrive_tokens WHERE user_email = $1", user_email)
                finally:
                    await conn.close()
            except Exception:
                pass

    return new_token


def get_user_email(request: Request) -> str:
    """Extract user email from request headers."""
    return (
        request.headers.get("x-user-email")
        or request.headers.get("X-User-Email")
        or "default@local"
    )


# --- OAuth Endpoints ---

@app.get("/auth/google/start")
async def auth_start(user_email: str = "default@local"):
    """Start Google OAuth flow."""
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
    """Handle Google OAuth callback."""
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
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px; background: #1e1e1e; color: #fff;">
        <h1 style="color: #00ac47;">Google Drive Connected!</h1>
        <p>Your Google Drive is now connected for <strong>{user_email}</strong>.</p>
        <p>This window will close automatically...</p>
        <script>
            // Notify parent window
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'aiui-gdrive-connected',
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
    """Check if a user has connected Google Drive."""
    token = await get_token(user_email)
    return {"connected": token is not None, "user_email": user_email}


@app.post("/auth/google/disconnect")
async def auth_disconnect(user_email: str = "default@local"):
    """Disconnect Google Drive for a user."""
    # Remove from in-memory store
    _tokens.pop(user_email, None)
    # Remove from database
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute("DELETE FROM gdrive_tokens WHERE user_email = $1", user_email)
            finally:
                await conn.close()
        except Exception:
            pass
    return {"disconnected": True, "user_email": user_email}


# --- Tool Models ---

class ListFilesInput(BaseModel):
    folder_id: Optional[str] = Field(default=None, description="Folder ID to list files from. Use 'root' for top-level or omit for root.")
    query: Optional[str] = Field(default=None, description="Search query to filter files (e.g. 'name contains report')")
    page_size: int = Field(default=20, description="Number of files to return (max 100)")

class SearchFilesInput(BaseModel):
    query: str = Field(description="Search query (e.g. 'quarterly report', 'budget 2024')")
    file_type: Optional[str] = Field(default=None, description="Filter by type: 'document', 'spreadsheet', 'presentation', 'pdf', 'folder'")
    page_size: int = Field(default=20, description="Number of results (max 100)")

class ReadFileInput(BaseModel):
    file_id: str = Field(description="The Google Drive file ID to read")

class FileInfoInput(BaseModel):
    file_id: str = Field(description="The Google Drive file ID to get info about")


# --- Helper ---

MIME_TYPE_MAP = {
    "document": "application/vnd.google-apps.document",
    "spreadsheet": "application/vnd.google-apps.spreadsheet",
    "presentation": "application/vnd.google-apps.presentation",
    "pdf": "application/pdf",
    "folder": "application/vnd.google-apps.folder",
}

EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", "txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "csv"),
    "application/vnd.google-apps.presentation": ("text/plain", "txt"),
}

NOT_CONNECTED_MSG = (
    "Google Drive is not connected. Please visit the following URL to connect:\n\n"
    "{base_url}/auth/google/start?user_email={email}\n\n"
    "After connecting, try again."
)


async def drive_request(access_token: str, path: str, params: dict = None) -> dict:
    """Make an authenticated request to Google Drive API."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_DRIVE_API}/{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


# --- Tool Endpoints ---

@app.post("/gdrive_list_files", operation_id="gdrive_list_files", summary="List files in Google Drive")
async def list_files(input: ListFilesInput, request: Request):
    """List files in a Google Drive folder. Returns file names, types, and IDs.
    Use folder_id='root' for top-level files, or provide a specific folder ID."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)

    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    folder_id = input.folder_id or "root"
    page_size = min(input.page_size, 100)

    q_parts = [f"'{folder_id}' in parents", "trashed = false"]
    if input.query:
        q_parts.append(input.query)

    data = await drive_request(access_token, "files", {
        "q": " and ".join(q_parts),
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
        "orderBy": "modifiedTime desc",
    })

    files = data.get("files", [])
    results = []
    for f in files:
        size = int(f.get("size", 0))
        size_str = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.1f} MB"
        results.append({
            "id": f["id"],
            "name": f["name"],
            "type": f["mimeType"].split(".")[-1] if "google-apps" in f["mimeType"] else f["mimeType"].split("/")[-1],
            "modified": f.get("modifiedTime", "")[:10],
            "size": size_str if size > 0 else "Google file",
            "link": f.get("webViewLink", ""),
        })

    return {
        "folder": folder_id,
        "file_count": len(results),
        "files": results,
    }


@app.post("/gdrive_search_files", operation_id="gdrive_search_files", summary="Search files in Google Drive")
async def search_files(input: SearchFilesInput, request: Request):
    """Search for files across your entire Google Drive by name or content."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)

    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    page_size = min(input.page_size, 100)
    q_parts = [f"fullText contains '{input.query}'", "trashed = false"]

    if input.file_type and input.file_type in MIME_TYPE_MAP:
        q_parts.append(f"mimeType = '{MIME_TYPE_MAP[input.file_type]}'")

    data = await drive_request(access_token, "files", {
        "q": " and ".join(q_parts),
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
        "orderBy": "modifiedTime desc",
    })

    files = data.get("files", [])
    results = []
    for f in files:
        results.append({
            "id": f["id"],
            "name": f["name"],
            "type": f["mimeType"].split(".")[-1] if "google-apps" in f["mimeType"] else f["mimeType"].split("/")[-1],
            "modified": f.get("modifiedTime", "")[:10],
            "link": f.get("webViewLink", ""),
        })

    return {
        "query": input.query,
        "result_count": len(results),
        "files": results,
    }


@app.post("/gdrive_read_file", operation_id="gdrive_read_file", summary="Read file content from Google Drive")
async def read_file(input: ReadFileInput, request: Request):
    """Read the content of a Google Drive file. Returns text content for documents,
    CSV for spreadsheets, and metadata for binary files. Max 2MB content."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)

    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Get file metadata first
    meta = await drive_request(access_token, f"files/{input.file_id}", {
        "fields": "id,name,mimeType,size,modifiedTime,webViewLink"
    })

    mime_type = meta.get("mimeType", "")
    file_name = meta.get("name", "unknown")
    file_size = int(meta.get("size", 0))

    # Google Workspace files — export as text
    if mime_type in EXPORT_MAP:
        export_mime, ext = EXPORT_MAP[mime_type]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files/{input.file_id}/export",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"mimeType": export_mime},
                timeout=30.0,
            )
            if resp.status_code == 200:
                content = resp.text[:MAX_CONTENT_SIZE]
                return {
                    "file_name": file_name,
                    "file_type": ext,
                    "content": content,
                    "truncated": len(resp.text) > MAX_CONTENT_SIZE,
                }
            return {"error": f"Export failed: {resp.status_code}", "file_name": file_name}

    # Text files — download directly
    if mime_type.startswith("text/") or mime_type in ("application/json", "application/xml"):
        if file_size > MAX_CONTENT_SIZE:
            return {
                "file_name": file_name,
                "file_type": mime_type,
                "content": f"[File too large: {file_size / (1024*1024):.1f} MB. Max is 2MB]",
                "size": file_size,
            }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files/{input.file_id}?alt=media",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return {
                    "file_name": file_name,
                    "file_type": mime_type,
                    "content": resp.text[:MAX_CONTENT_SIZE],
                    "truncated": len(resp.text) > MAX_CONTENT_SIZE,
                }

    # Binary files (PDF etc.) — download and return as base64
    if file_size > 10 * 1024 * 1024:  # 10MB limit for binary
        return {
            "file_name": file_name,
            "file_type": mime_type,
            "size": f"{file_size / (1024*1024):.1f} MB",
            "content": f"[File too large for attachment: {file_size / (1024*1024):.1f} MB]",
            "binary": False,
        }

    import base64
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_DRIVE_API}/files/{input.file_id}?alt=media",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60.0,
        )
        if resp.status_code == 200:
            b64 = base64.b64encode(resp.content).decode('ascii')
            return {
                "file_name": file_name,
                "file_type": mime_type,
                "size": f"{file_size / (1024*1024):.1f} MB" if file_size > 1024*1024 else f"{file_size / 1024:.0f} KB",
                "binary": True,
                "base64": b64,
            }

    return {
        "file_name": file_name,
        "file_type": mime_type,
        "content": "[Failed to download file]",
        "binary": False,
    }


@app.get("/gdrive_download/{file_id}")
async def download_file(file_id: str, user_email: str = "default@local"):
    """Download a file from Google Drive as binary (for PDFs and other binary files)."""
    access_token = await get_valid_token(user_email)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not connected")

    # Get file metadata
    meta = await drive_request(access_token, f"files/{file_id}", {
        "fields": "id,name,mimeType,size"
    })
    mime_type = meta.get("mimeType", "")
    file_name = meta.get("name", "download")

    # For Google Workspace files, export
    if mime_type in EXPORT_MAP:
        export_mime, ext = EXPORT_MAP[mime_type]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files/{file_id}/export",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"mimeType": export_mime},
                timeout=60.0,
            )
            if resp.status_code == 200:
                from fastapi.responses import Response
                return Response(
                    content=resp.content,
                    media_type=export_mime,
                    headers={"Content-Disposition": f'attachment; filename="{file_name}.{ext}"'}
                )

    # For regular files (PDF etc), download directly
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_DRIVE_API}/files/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60.0,
        )
        if resp.status_code == 200:
            from fastapi.responses import Response
            return Response(
                content=resp.content,
                media_type=mime_type,
                headers={"Content-Disposition": f'attachment; filename="{file_name}"'}
            )

    raise HTTPException(status_code=500, detail="Download failed")


class DirectUploadInput(BaseModel):
    file_id: str = Field(description="Google Drive file ID")
    webui_url: str = Field(default="http://open-webui:8080", description="Open WebUI URL")
    webui_token: str = Field(description="Open WebUI auth token")


@app.post("/gdrive_upload_to_webui")
async def upload_to_webui(input: DirectUploadInput, request: Request):
    """Download file from Google Drive and upload directly to Open WebUI (server-side)."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        return {"error": "Not connected"}

    # Get file metadata
    meta = await drive_request(access_token, f"files/{input.file_id}", {
        "fields": "id,name,mimeType,size"
    })
    mime_type = meta.get("mimeType", "")
    file_name = meta.get("name", "download")
    file_size = int(meta.get("size", 0))

    # Download from Google Drive
    if mime_type in EXPORT_MAP:
        export_mime, ext = EXPORT_MAP[mime_type]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files/{input.file_id}/export",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"mimeType": export_mime},
                timeout=60.0,
            )
            file_bytes = resp.content
            file_name = f"{file_name}.{ext}"
            mime_type = export_mime
    else:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files/{input.file_id}?alt=media",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=120.0,
            )
            file_bytes = resp.content

    if not file_bytes:
        return {"error": "Failed to download file"}

    # Upload directly to Open WebUI
    import io
    unique_name = f"{file_name.rsplit('.', 1)[0]}_{int(__import__('time').time())}.{file_name.rsplit('.', 1)[-1]}"

    async with httpx.AsyncClient() as client:
        upload_resp = await client.post(
            f"{input.webui_url}/api/v1/files/",
            headers={"Authorization": f"Bearer {input.webui_token}"},
            files={"file": (unique_name, io.BytesIO(file_bytes), mime_type)},
            timeout=120.0,
        )

    if upload_resp.status_code == 200:
        result = upload_resp.json()
        return {
            "success": True,
            "file_id": result.get("id"),
            "filename": result.get("filename", unique_name),
            "size": len(file_bytes),
        }
    else:
        return {"error": f"Upload failed: {upload_resp.status_code} {upload_resp.text[:200]}"}


@app.post("/gdrive_get_file_info", operation_id="gdrive_get_file_info", summary="Get file metadata from Google Drive")
async def get_file_info(input: FileInfoInput, request: Request):
    """Get detailed metadata about a Google Drive file (name, type, size, modified date, sharing info)."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)

    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    meta = await drive_request(access_token, f"files/{input.file_id}", {
        "fields": "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,owners,shared,permissions"
    })

    file_size = int(meta.get("size", 0))
    owners = [o.get("displayName", o.get("emailAddress", "unknown")) for o in meta.get("owners", [])]

    return {
        "id": meta["id"],
        "name": meta.get("name", "unknown"),
        "type": meta.get("mimeType", "unknown"),
        "size": f"{file_size / (1024*1024):.1f} MB" if file_size > 1024*1024 else f"{file_size / 1024:.0f} KB" if file_size > 0 else "Google file",
        "created": meta.get("createdTime", "")[:10],
        "modified": meta.get("modifiedTime", "")[:10],
        "owners": owners,
        "shared": meta.get("shared", False),
        "link": meta.get("webViewLink", ""),
    }


# --- Health ---

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "google-drive-mcp",
        "oauth_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
