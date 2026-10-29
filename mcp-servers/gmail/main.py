"""Gmail MCP Server — search, read, and send emails from Gmail."""
import os
import base64
import html
import urllib.parse
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import crypto_utils  # encrypt OAuth tokens at rest (AIUI_FERNET_KEY)
import oauth_state  # verify signed OAuth state (owner identity)
import account_identity  # an account is keyed by its address, never its id
from draft_builder import build_draft_raw, build_draft_raw_with_attachment

app = FastAPI(
    title="Gmail MCP",
    description="""Search, read, and send emails from your Gmail.

IMPORTANT - Tool Usage Guidelines for AI:
- When user wants to READ an email: use gmail_read_email
- When user wants to LIST emails: use gmail_list_emails
- When user wants to SEARCH emails: use gmail_search_emails
- When user wants to COMPOSE A BRAND-NEW email (no existing message to reply to): use gmail_create_draft
- When user wants to draft a REPLY to an existing email: use gmail_create_draft_reply with the message_id from the email
- When user wants to SEND an email: use gmail_send_email
- When user wants to see their LABELS/FOLDERS: use gmail_list_labels

Always look for [Gmail Message ID: xxx] in attached files to get the message_id for draft/reply operations.
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
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8006/auth/google/callback")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MAX_CONTENT_SIZE = 2 * 1024 * 1024  # 2MB

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.compose"
# Unified "Connect Google": one consent granting Gmail + Calendar + Drive.
ALL_SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
])

# In-memory token store (dev); PostgreSQL for prod
_tokens: dict = {}


# --- Token Management (same pattern as gdrive) ---

async def get_token(user_email: str) -> Optional[dict]:
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    "SELECT access_token, refresh_token, token_expiry FROM gmail_tokens WHERE user_email = $1",
                    user_email
                )
                if row:
                    # Tokens are Fernet ciphertext at rest — decrypt on read.
                    return {
                        "access_token": crypto_utils.decrypt(row["access_token"]),
                        "refresh_token": crypto_utils.decrypt(row["refresh_token"]) if row["refresh_token"] else None,
                        "token_expiry": row["token_expiry"].isoformat() if row["token_expiry"] else None
                    }
            finally:
                await conn.close()
        except Exception:
            pass
    return _tokens.get(user_email)


async def save_token(user_email: str, token_data: dict):
    _tokens[user_email] = token_data  # in-memory cache stays plaintext (not at rest)
    if DATABASE_URL:
        try:
            import asyncpg
            # Encrypt at the DB boundary — tokens are at rest as Fernet ciphertext.
            enc_access = crypto_utils.encrypt(token_data["access_token"])
            enc_refresh = (
                crypto_utils.encrypt(token_data["refresh_token"])
                if token_data.get("refresh_token") else None
            )
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute("""
                    INSERT INTO gmail_tokens (user_email, access_token, refresh_token, token_expiry)
                    VALUES ($1, $2, $3, NOW() + INTERVAL '1 hour')
                    ON CONFLICT (user_email) DO UPDATE
                    SET access_token = $2, refresh_token = COALESCE($3, gmail_tokens.refresh_token),
                        token_expiry = NOW() + INTERVAL '1 hour', updated_at = NOW()
                """, user_email, enc_access, enc_refresh)
            finally:
                await conn.close()
        except Exception:
            pass


async def refresh_access_token(user_email: str) -> Optional[str]:
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
    token = await get_token(user_email)
    if not token:
        return None
    # Test token
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GMAIL_API}/users/me/profile",
            headers={"Authorization": f"Bearer {token['access_token']}"}
        )
        if resp.status_code == 200:
            return token["access_token"]
    # Try refresh
    new_token = await refresh_access_token(user_email)
    if not new_token:
        _tokens.pop(user_email, None)
        if DATABASE_URL:
            try:
                import asyncpg
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    await conn.execute("DELETE FROM gmail_tokens WHERE user_email = $1", user_email)
                finally:
                    await conn.close()
            except Exception:
                pass
    return new_token


async def _email_for_user_id(user_id: str) -> Optional[str]:
    """The address of the account with this Open WebUI user id, or None.

    Only reached when a client sent an id instead of an address, which is a
    bug in that client. Resolving it here keeps that client's requests working
    while it is being fixed, and keeps the id out of the token tables.
    """
    if not DATABASE_URL:
        return None
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # "user" is a reserved word, hence the quoting.
            row = await conn.fetchrow(
                'SELECT email FROM public."user" WHERE id = $1', user_id)
            return row["email"] if row else None
        finally:
            await conn.close()
    except Exception:
        return None


async def get_user_email(request: Request) -> str:
    """The address of the account making this request.

    Normalised through account_identity, because a client may send an Open
    WebUI user id instead of an address. See that module for how one did, for
    months, in silence.
    """
    raw = (
        request.headers.get("x-user-email")
        or request.headers.get("X-User-Email")
        or "default@local"
    )
    return await account_identity.canonical_email(raw, _email_for_user_id)


NOT_CONNECTED_MSG = (
    "Gmail is not connected. Please visit the following URL to connect:\n\n"
    "{base_url}/auth/google/link\n\n"
    "After connecting, try again."
)


async def _save_token_all_services(user_email: str, access_token: str, refresh_token):
    """Unified connect: populate gdrive_tokens (encrypted, like gmail) and
    calendar_tokens (plaintext, per that service's format) so one Google consent
    links Gmail + Calendar + Drive. gmail_tokens is already written by save_token."""
    if not DATABASE_URL:
        return
    try:
        import asyncpg
        enc_access = crypto_utils.encrypt(access_token)
        enc_refresh = crypto_utils.encrypt(refresh_token) if refresh_token else None
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # Drive: same encrypted-at-rest convention as gmail.
            await conn.execute("""
                INSERT INTO gdrive_tokens (user_email, access_token, refresh_token, token_expiry)
                VALUES ($1, $2, $3, NOW() + INTERVAL '1 hour')
                ON CONFLICT (user_email) DO UPDATE
                SET access_token = $2, refresh_token = COALESCE($3, gdrive_tokens.refresh_token),
                    token_expiry = NOW() + INTERVAL '1 hour', updated_at = NOW()
            """, user_email, enc_access, enc_refresh)
            # Calendar: plaintext (that service does not decrypt). Create table if
            # it does not exist yet (mirrors calendar's own save_token schema).
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
            """, user_email, access_token, refresh_token)
        finally:
            await conn.close()
        print(f"[unified-connect] linked gmail+drive+calendar for {user_email}", flush=True)
    except Exception as e:
        print(f"[unified-connect] failed for {user_email}: {e}", flush=True)


#: Marks a state asking for Gmail + Calendar + Drive in one consent. It is
#: signed together with the address, so neither the identity nor the scope can
#: be chosen by whoever opens the link.
UNIFIED_PREFIX = "all::"


def _google_url(scope: str, state: str) -> str:
    """The consent URL. One builder, so start and link cannot drift apart."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _bad_link_page() -> HTMLResponse:
    return HTMLResponse(_connect_failed_page(
        "This connect link is not valid, or it has expired. Open Connections "
        "and press Connect again."), status_code=400)


def _connect_failed_page(why: str) -> str:
    """Shown instead of silently connecting an account nobody can look up.

    The old behaviour was worse than an error: the consent succeeded, the row
    was written under a key no read ever asks for, and the person was told
    "Gmail Connected!".
    """
    return (
        '<html><body style="font-family: sans-serif; text-align: center; '
        'padding: 50px; background: #1e1e1e; color: #fff;">'
        '<h1 style="color: #ea4335;">Gmail was not connected</h1>'
        '<p>%s</p>'
        '</body></html>' % html.escape(why)
    )


# --- OAuth Endpoints ---

@app.get("/auth/google/start")
async def auth_start(state: str = "", connect: str = "gmail"):
    """Begin a connect from a state that was signed for its owner.

    The Discord and Slack flows sign one and send the person the link
    (clients/connectors.py). A browser cannot: it holds no secret. It goes to
    /auth/google/link instead, which signs for whoever is signed in.

    This used to accept `user_email` and believe it. Anyone could therefore
    open this URL naming somebody else, consent with a Google account of their
    own, and the callback would store those tokens under the named person's
    address, replacing their real connection: their agents would then be
    acting in a mailbox that was not theirs. The parameter is gone.
    """
    owner = oauth_state.verify_state(state) if state else None
    if not owner:
        return _bad_link_page()
    unified = owner.startswith(UNIFIED_PREFIX)
    return RedirectResponse(_google_url(
        ALL_SCOPES if (unified or connect == "all") else SCOPES, state))


@app.get("/auth/google/link")
async def auth_link(request: Request, connect: str = "all"):
    """Begin a connect for whoever is signed in, and sign the state here.

    The browser never says who it is. The api-gateway authenticates the
    session (bearer token, or the Open WebUI `token` cookie on a plain
    navigation) and injects X-User-Email, stripping whatever the client sent,
    so this is the identity worth signing. That is the whole point of the
    endpoint: the address is taken from the session rather than from the URL.
    """
    try:
        email = await account_identity.canonical_email(
            await get_user_email(request), _email_for_user_id,
            required=True, placeholders_ok=not DATABASE_URL)
    except account_identity.UnknownAccount:
        return HTMLResponse(_connect_failed_page(
            "Could not tell which account you are signed in as. Reload the "
            "page and try again."), status_code=400)
    try:
        state = oauth_state.sign_state(
            (UNIFIED_PREFIX + email) if connect == "all" else email)
    except RuntimeError:
        # No OAUTH_STATE_SECRET. Refusing beats falling back to an unsigned
        # state, which is the hole this endpoint exists to close.
        return HTMLResponse(_connect_failed_page(
            "This server cannot start a connect right now."), status_code=500)
    return RedirectResponse(_google_url(
        ALL_SCOPES if connect == "all" else SCOPES, state))


@app.get("/auth/google/callback")
async def auth_callback(code: str, state: str = ""):
    # The state must carry a signature this server made. It used to accept
    # `all::<address>` unsigned, and an unsigned address as a fallback, which
    # meant the person a consent was stored against was chosen by whoever
    # opened the link rather than by who signed in.
    owner = oauth_state.verify_state(state) if state else None
    if not owner:
        return _bad_link_page()
    unified = owner.startswith(UNIFIED_PREFIX)
    user_email = owner[len(UNIFIED_PREFIX):] if unified else owner
    # Every path converges here, including the signed state the Discord and
    # Slack flows build, so this is the one place that can promise no token
    # row is ever keyed by anything but an address.
    try:
        user_email = await account_identity.canonical_email(
            user_email, _email_for_user_id, required=True,
            placeholders_ok=not DATABASE_URL)
    except account_identity.UnknownAccount as err:
        return HTMLResponse(_connect_failed_page(str(err)), status_code=400)
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
    if unified:
        # One consent -> link Calendar + Drive too. gdrive uses the same
        # encrypted-at-rest format as gmail; calendar stores plaintext.
        await _save_token_all_services(
            user_email, data["access_token"], data.get("refresh_token"))
    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px; background: #1e1e1e; color: #fff;">
        <h1 style="color: #ea4335;">Gmail Connected!</h1>
        <p>Your Gmail is now connected for <strong>{user_email}</strong>.</p>
        <p>Returning you to the chat...</p>
        <script>
            (function() {{
                var back = null;
                try {{
                    back = localStorage.getItem('aiui-return-url');
                    localStorage.removeItem('aiui-return-url');
                }} catch (e) {{}}
                if (window.opener && !window.opener.closed) {{
                    // Opened as a popup: tell the app and close.
                    try {{
                        window.opener.postMessage({{
                            type: 'aiui-gmail-connected',
                            email: '{user_email}',
                            connected: true
                        }}, '*');
                    }} catch (e) {{}}
                    window.close();
                }} else {{
                    // Same-tab redirect: go back to the exact chat the user came from.
                    window.location.href = back || '/';
                }}
            }})();
        </script>
    </body></html>
    """)


@app.get("/auth/status")
async def auth_status_header(request: Request):
    """Header-based status (X-User-Email via api-gateway) for the connect-UX poll."""
    tok = await get_token(await get_user_email(request))
    return {"connected": tok is not None}


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
                await conn.execute("DELETE FROM gmail_tokens WHERE user_email = $1", user_email)
            finally:
                await conn.close()
        except Exception:
            pass
    return {"disconnected": True, "user_email": user_email}


# --- Gmail Helpers ---

async def gmail_request(access_token: str, path: str, params: dict = None, method: str = "GET", json_body: dict = None) -> dict:
    async with httpx.AsyncClient() as client:
        if method == "GET":
            # Build URL with params manually to handle repeated keys (metadataHeaders)
            url = f"{GMAIL_API}/{path}"
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params or {},
                timeout=30.0,
            )
        else:
            resp = await client.post(
                f"{GMAIL_API}/{path}",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json=json_body or {},
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


async def gmail_get_message_metadata(access_token: str, message_id: str) -> dict:
    """Get message with headers using the correct API format."""
    url = f"{GMAIL_API}/users/me/messages/{message_id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Date&metadataHeaders=Cc&metadataHeaders=Message-ID&metadataHeaders=References"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


def extract_header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def extract_body(payload: dict) -> str:
    """Extract text body from Gmail message payload. Handles all MIME structures."""
    import re

    def _decode_data(data: str) -> str:
        if not data:
            return ""
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _html_to_text(html: str) -> str:
        text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<div[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&#39;', "'").replace('&quot;', '"')
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_from_part(part: dict) -> tuple:
        """Returns (text, is_plain) tuple."""
        mime = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")

        if mime == "text/plain" and body_data:
            return (_decode_data(body_data), True)

        if mime == "text/html" and body_data:
            return (_html_to_text(_decode_data(body_data)), False)

        # Recurse into multipart
        sub_parts = part.get("parts", [])
        plain_text = ""
        html_text = ""
        for sub in sub_parts:
            text, is_plain = _extract_from_part(sub)
            if text:
                if is_plain:
                    plain_text = text
                else:
                    html_text = text

        # Prefer plain text over HTML
        return (plain_text or html_text, bool(plain_text))

    text, _ = _extract_from_part(payload)
    return text


# --- Tool Models ---

class ListEmailsInput(BaseModel):
    label: str = Field(default="INBOX", description="Gmail label (INBOX, SENT, STARRED, IMPORTANT, etc)")
    max_results: int = Field(default=20, description="Number of emails to return (max 50)")
    unread_only: bool = Field(default=False, description="Only show unread emails")

class SearchEmailsInput(BaseModel):
    query: str = Field(description="Gmail search query (e.g. 'from:alice subject:invoice after:2026/01/01')")
    max_results: int = Field(default=20, description="Number of results (max 50)")

class ReadEmailInput(BaseModel):
    message_id: str = Field(description="Gmail message ID")

class SendEmailInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body text")
    cc: Optional[str] = Field(default=None, description="CC recipients (comma-separated)")
    bcc: Optional[str] = Field(default=None, description="BCC recipients (comma-separated)")
    reply_to_message_id: Optional[str] = Field(default=None, description="Message ID to reply to (for threading)")

class CreateDraftReplyInput(BaseModel):
    message_id: str = Field(description="Gmail message ID to reply to")
    body: str = Field(description="Draft reply body text")
    cc: Optional[str] = Field(default=None, description="CC recipients (comma-separated)")


class CreateDraftInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Draft body text (plain text)")
    cc: Optional[str] = Field(default=None, description="CC recipients (comma-separated)")
    bcc: Optional[str] = Field(default=None, description="BCC recipients (comma-separated)")


class CreateDraftAttachmentInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Draft body text (plain text)")
    filename: str = Field(description="Attachment file name, e.g. report.pdf")
    content_b64: str = Field(description="Attachment bytes as standard base64")
    mime_type: str = Field(default="application/octet-stream",
                           description="Attachment MIME type")


# --- Tool Endpoints ---

@app.post("/gmail_list_emails", operation_id="gmail_list_emails", summary="List emails from Gmail inbox")
async def list_emails(input: ListEmailsInput, request: Request):
    """List recent emails from a Gmail label. Use this when the user asks to see their emails, inbox, or recent messages. Returns subjects, senders, dates, and snippets."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    max_results = min(input.max_results, 50)
    params = {"labelIds": input.label, "maxResults": max_results}
    if input.unread_only:
        params["q"] = "is:unread"

    data = await gmail_request(access_token, "users/me/messages", params)
    messages = data.get("messages", [])

    if not messages:
        return {"label": input.label, "email_count": 0, "emails": []}

    # Fetch metadata for each message
    emails = []
    for msg in messages[:max_results]:
        try:
            detail = await gmail_get_message_metadata(access_token, msg['id'])
            headers = detail.get("payload", {}).get("headers", [])
            emails.append({
                "id": msg["id"],
                "thread_id": detail.get("threadId", ""),
                "subject": extract_header(headers, "Subject") or "(no subject)",
                "from": extract_header(headers, "From"),
                "date": extract_header(headers, "Date"),
                "snippet": detail.get("snippet", ""),
                "unread": "UNREAD" in detail.get("labelIds", []),
            })
        except Exception:
            continue

    return {"label": input.label, "email_count": len(emails), "emails": emails}


@app.post("/gmail_search_emails", operation_id="gmail_search_emails", summary="Search emails in Gmail")
async def search_emails(input: SearchEmailsInput, request: Request):
    """Search emails across your entire Gmail. Use this when the user asks to find a specific email, search for messages from someone, or look for emails about a topic."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    max_results = min(input.max_results, 50)
    data = await gmail_request(access_token, "users/me/messages", {"q": input.query, "maxResults": max_results})
    messages = data.get("messages", [])

    if not messages:
        return {"query": input.query, "email_count": 0, "emails": []}

    emails = []
    for msg in messages[:max_results]:
        try:
            detail = await gmail_get_message_metadata(access_token, msg['id'])
            headers = detail.get("payload", {}).get("headers", [])
            emails.append({
                "id": msg["id"],
                "thread_id": detail.get("threadId", ""),
                "subject": extract_header(headers, "Subject") or "(no subject)",
                "from": extract_header(headers, "From"),
                "date": extract_header(headers, "Date"),
                # Gmail's own timestamp, in milliseconds. `date` above is the
                # Date HEADER, written by the sender, and is routinely wrong,
                # absent or in a format nobody agreed on, so it cannot carry
                # a cursor. The email trigger polls this endpoint and needs
                # to know how far it has got (tasks/email_trigger.py), and
                # format=metadata has always returned this; it was simply
                # never passed on. Additive, so nothing reading this today
                # notices.
                "internal_date": detail.get("internalDate", ""),
                "snippet": detail.get("snippet", ""),
            })
        except Exception:
            continue

    return {"query": input.query, "email_count": len(emails), "emails": emails}


@app.post("/gmail_read_email", operation_id="gmail_read_email", summary="Read full email content from Gmail")
async def read_email(input: ReadEmailInput, request: Request):
    """Read the full content of a Gmail email including body and attachment list. Use this when the user wants to read, view, or get the content of a specific email."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    detail = await gmail_request(access_token, f"users/me/messages/{input.message_id}", {"format": "full"})
    headers = detail.get("payload", {}).get("headers", [])
    body = extract_body(detail.get("payload", {}))

    # Truncate body
    if len(body) > MAX_CONTENT_SIZE:
        body = body[:MAX_CONTENT_SIZE]
        truncated = True
    else:
        truncated = False

    # Extract attachments
    attachments = []
    for part in detail.get("payload", {}).get("parts", []):
        if part.get("filename"):
            attachments.append({
                "filename": part["filename"],
                "mime_type": part.get("mimeType", ""),
                "size": int(part.get("body", {}).get("size", 0)),
                "attachment_id": part.get("body", {}).get("attachmentId", ""),
            })

    return {
        "id": detail["id"],
        "thread_id": detail.get("threadId", ""),
        "subject": extract_header(headers, "Subject") or "(no subject)",
        "from": extract_header(headers, "From"),
        "to": extract_header(headers, "To"),
        "cc": extract_header(headers, "Cc"),
        "date": extract_header(headers, "Date"),
        "body": body,
        "truncated": truncated,
        "attachments": attachments,
        "labels": detail.get("labelIds", []),
    }


@app.post("/gmail_send_email", operation_id="gmail_send_email", summary="Send an email via Gmail")
async def send_email(input: SendEmailInput, request: Request):
    """Send an email from your Gmail account. Use this when the user wants to send, write, or compose a new email to someone. Can also reply to existing threads using reply_to_message_id."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Build MIME message
    msg = MIMEText(input.body, "plain")
    msg["To"] = input.to
    msg["Subject"] = input.subject
    if input.cc:
        msg["Cc"] = input.cc
    if input.bcc:
        msg["Bcc"] = input.bcc

    # Handle reply threading
    thread_id = None
    if input.reply_to_message_id:
        try:
            original = await gmail_get_message_metadata(access_token, input.reply_to_message_id)
            orig_headers = original.get("payload", {}).get("headers", [])
            message_id_header = extract_header(orig_headers, "Message-ID")
            references = extract_header(orig_headers, "References")
            if message_id_header:
                msg["In-Reply-To"] = message_id_header
                msg["References"] = f"{references} {message_id_header}".strip()
            thread_id = original.get("threadId")
        except Exception:
            pass

    # Encode
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    result = await gmail_request(access_token, "users/me/messages/send", method="POST", json_body=body)

    return {
        "success": True,
        "message_id": result.get("id", ""),
        "thread_id": result.get("threadId", ""),
    }


@app.post("/gmail_create_draft_reply", operation_id="gmail_create_draft_reply", summary="Create a draft reply to an email in Gmail")
async def create_draft_reply(input: CreateDraftReplyInput, request: Request):
    """Create a draft reply to a specific email. ALWAYS use this when the user asks to draft a reply, create a draft, or respond to an email. The draft is saved in the user's actual Gmail Drafts folder. Requires the message_id of the email to reply to - look for [Gmail Message ID: xxx] in attached email files."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    # Get original email details for threading
    original = await gmail_get_message_metadata(access_token, input.message_id)
    orig_headers = original.get("payload", {}).get("headers", [])
    orig_subject = extract_header(orig_headers, "Subject")
    orig_from = extract_header(orig_headers, "From")
    orig_to = extract_header(orig_headers, "To")
    orig_message_id = extract_header(orig_headers, "Message-ID")
    orig_references = extract_header(orig_headers, "References")
    thread_id = original.get("threadId")

    # Reply goes to the original sender
    reply_to = orig_from

    # Build reply subject
    subject = orig_subject
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    # Build MIME message
    msg = MIMEText(input.body, "plain")
    msg["To"] = reply_to
    msg["Subject"] = subject
    if input.cc:
        msg["Cc"] = input.cc
    if orig_message_id:
        msg["In-Reply-To"] = orig_message_id
        msg["References"] = f"{orig_references} {orig_message_id}".strip()

    # Encode
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    # Create draft (not send)
    draft_body = {
        "message": {
            "raw": raw,
            "threadId": thread_id
        }
    }

    result = await gmail_request(access_token, "users/me/drafts", method="POST", json_body=draft_body)

    return {
        "success": True,
        "draft_id": result.get("id", ""),
        "message_id": result.get("message", {}).get("id", ""),
        "thread_id": result.get("message", {}).get("threadId", ""),
        "reply_to": reply_to,
        "subject": subject,
        "message": f"Draft reply created. Open Gmail to review and send it."
    }


@app.post("/gmail_create_draft", operation_id="gmail_create_draft", summary="Create a new draft email in Gmail")
async def create_draft(input: CreateDraftInput, request: Request):
    """Create a brand-new draft email (not a reply). Use this when the user asks to draft, compose, or write a new email to someone. The draft is saved in the user's Gmail Drafts folder and is NEVER sent; the user reviews and sends it themselves."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    try:
        raw = build_draft_raw(input.to, input.subject, input.body, input.cc, input.bcc)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    draft_body = {"message": {"raw": raw}}
    result = await gmail_request(access_token, "users/me/drafts", method="POST", json_body=draft_body)

    return {
        "success": True,
        "draft_id": result.get("id", ""),
        "to": input.to,
        "subject": input.subject,
        "message": "Draft created. Open Gmail to review and send it.",
    }


@app.post("/gmail_create_draft_with_attachment",
          operation_id="gmail_create_draft_with_attachment",
          summary="Create a Gmail draft with a file attached")
async def create_draft_with_attachment(input: CreateDraftAttachmentInput,
                                       request: Request):
    """Create a draft email carrying one binary attachment (used by the
    Documents tool's "email this file" flow). Same safety stance as
    gmail_create_draft: the draft is saved in the user's Drafts folder and is
    NEVER sent; the user reviews and sends it themselves."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    try:
        raw = build_draft_raw_with_attachment(
            input.to, input.subject, input.body,
            input.filename, input.content_b64, input.mime_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    draft_body = {"message": {"raw": raw}}
    result = await gmail_request(access_token, "users/me/drafts",
                                 method="POST", json_body=draft_body)

    return {
        "success": True,
        "draft_id": result.get("id", ""),
        "to": input.to,
        "subject": input.subject,
        "message": "Draft with attachment created. Open Gmail to review and send it.",
    }


@app.get("/gmail_download_attachment/{message_id}/{attachment_id}")
async def download_attachment(message_id: str, attachment_id: str, request: Request,
                              filename: str = "attachment"):
    """Download an email attachment by its attachment ID.

    Whose mailbox is read comes from the header the api-gateway injects, the
    same as every other endpoint here. It used to come from a `user_email`
    query parameter, which meant an unauthenticated caller could name any
    connected account and have this service call Gmail with that person's
    token: confirmed against production on 2026-10-29, where naming an
    address returned Google's own "Invalid attachment token" rather than
    "Not connected", which only happens once a real token has been used.
    Extraction still needed a valid message and attachment id, so nothing was
    enumerable, but the authorization check was missing all the same.

    The gateway strips any client-sent x-user-email and sets its own from the
    validated session, so the header is the only identity here worth trusting.
    A `user_email` parameter is now ignored rather than rejected, so an older
    cached page keeps working as its own account.
    """
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not connected")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GMAIL_API}/users/me/messages/{message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60.0,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        file_data = data.get("data", "")
        if not file_data:
            raise HTTPException(status_code=404, detail="No attachment data")

        # Gmail returns base64url encoded data
        import base64
        file_bytes = base64.urlsafe_b64decode(file_data)

        from fastapi.responses import Response
        return Response(
            content=file_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )


@app.post("/gmail_list_labels", operation_id="gmail_list_labels", summary="List Gmail labels and folders")
async def list_labels(request: Request):
    """List all Gmail labels and folders (Inbox, Sent, Starred, custom labels, etc). Use this when the user asks about their email folders or labels."""
    user_email = await get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    data = await gmail_request(access_token, "users/me/labels")
    labels = []
    for label in data.get("labels", []):
        labels.append({
            "id": label["id"],
            "name": label.get("name", ""),
            "type": label.get("type", ""),
        })

    return {"labels": labels}


# --- Health ---

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "gmail-mcp",
        "oauth_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
