"""Per-user Vercel: connect an access token, deploy App Builder apps to it.

The user pastes a Vercel access token once (Connections/App Builder UI); we
verify it against the Vercel API, store it Fernet-encrypted per user, and any
app they are a project member of gets a one-click "Deploy" that pushes the
app's files to THEIR Vercel account and returns the live URL.

Security: the token is encrypted at rest (crypto_utils / AIUI_FERNET_KEY),
never logged, and never returned to the client after connect.
"""
import asyncio
import base64
import os
import re
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import crypto_utils
from auth import current_user, CurrentUser

router = APIRouter(prefix="/vercel")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
VERCEL_API = "https://api.vercel.com"

# --- OAuth integration (one-click Connect with Vercel) -----------------------
# Requires a "connectable account" Integration registered in the Vercel
# Integrations Console (dashboard -> Integrations -> Console -> Create).
# Until the three env vars below are set on the server, the UI automatically
# falls back to paste-an-access-token. Docs: vercel.com/docs/integrations.
VERCEL_CLIENT_ID = os.environ.get("VERCEL_CLIENT_ID", "")
VERCEL_CLIENT_SECRET = os.environ.get("VERCEL_CLIENT_SECRET", "")
VERCEL_INTEGRATION_SLUG = os.environ.get("VERCEL_INTEGRATION_SLUG", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://ai-ui.coolestdomain.win")
VERCEL_REDIRECT_URI = os.environ.get(
    "VERCEL_REDIRECT_URI", PUBLIC_BASE_URL + "/api/tasks/vercel/oauth/callback")
OAUTH_STATE_TTL_SEC = 1800  # matches Vercel's 30-minute code validity
_OAUTH_STATES = {}          # state -> (user_email, expires_at)


def oauth_configured() -> bool:
    return bool(VERCEL_CLIENT_ID and VERCEL_CLIENT_SECRET
                and VERCEL_INTEGRATION_SLUG)


def new_oauth_state(email: str, now: float = None) -> str:
    """Mint a CSRF state bound to the signed-in user (30 min TTL)."""
    now = time.time() if now is None else now
    for k in [k for k, (_, exp) in _OAUTH_STATES.items() if exp < now]:
        _OAUTH_STATES.pop(k, None)
    s = secrets.token_urlsafe(24)
    _OAUTH_STATES[s] = (email, now + OAUTH_STATE_TTL_SEC)
    return s


def pop_oauth_state(state: str, now: float = None):
    """Consume a state exactly once -> owning email, or None if bad/expired."""
    now = time.time() if now is None else now
    item = _OAUTH_STATES.pop(state or "", None)
    if not item:
        return None
    email, exp = item
    return email if exp >= now else None
APPS_ROOT = os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

# Deploy size guards: App Builder apps are static sites; anything beyond this
# is not a candidate for inline-file deployment.
SKIP_DIRS = {"node_modules", ".git", ".vercel", "__pycache__", ".next"}
MAX_FILES = 300
MAX_TOTAL_BYTES = 8_000_000


# --- pure helpers (unit tested, no I/O) --------------------------------------
def is_deployable(rel: str) -> bool:
    """Relative path filter: skip VCS/build junk and dot-directories."""
    parts = rel.replace("\\", "/").split("/")
    return bool(parts) and not any(
        p in SKIP_DIRS or p.startswith(".") for p in parts)


def collect_files(root: str, max_files: int = MAX_FILES,
                  max_bytes: int = MAX_TOTAL_BYTES) -> list:
    """Walk an app dir -> [(relpath, bytes)]. Raises ValueError when the app
    is empty or exceeds the inline-deploy caps."""
    out, total = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not is_deployable(rel):
                continue
            try:
                with open(full, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            total += len(data)
            out.append((rel, data))
            if len(out) > max_files or total > max_bytes:
                raise ValueError(
                    f"app too large to deploy inline ({len(out)}+ files, "
                    f"{total} bytes)")
    if not out:
        raise ValueError("no deployable files in this app")
    return out


def to_vercel_files(pairs: list) -> list:
    """[(rel, bytes)] -> Vercel inline-file payload entries."""
    return [{"file": rel,
             "data": base64.b64encode(data).decode("ascii"),
             "encoding": "base64"}
            for rel, data in pairs]


# --- storage -----------------------------------------------------------------
async def _connect_db():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


async def ensure_tables(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vercel_tokens (
            user_email  text PRIMARY KEY,
            token_enc   text NOT NULL,
            team_id     text,
            username    text,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """)
    await conn.execute(
        "ALTER TABLE vercel_tokens ADD COLUMN IF NOT EXISTS configuration_id text")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vercel_deployments (
            slug        text NOT NULL,
            user_email  text NOT NULL,
            url         text NOT NULL,
            deployed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (slug, user_email)
        )
        """)


async def _stored_token(conn, email: str):
    row = await conn.fetchrow(
        "SELECT token_enc, team_id, username FROM vercel_tokens "
        "WHERE user_email = $1", email)
    if not row:
        return None
    try:
        return {"token": crypto_utils.decrypt(row["token_enc"]),
                "team_id": row["team_id"], "username": row["username"]}
    except Exception:
        return None  # wrong key / tampered -> treat as not connected


# --- Vercel API --------------------------------------------------------------
async def _vercel_username(token: str) -> str:
    """Verify a token by asking Vercel who it belongs to. Raises ValueError."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{VERCEL_API}/v2/user",
                             headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise ValueError(f"Vercel rejected the token (HTTP {r.status_code})")
    user = (r.json() or {}).get("user") or {}
    return user.get("username") or user.get("email") or "connected"


# --- endpoints ---------------------------------------------------------------
class ConnectBody(BaseModel):
    token: str
    team_id: str | None = None


@router.get("/oauth/config")
async def oauth_config(user: CurrentUser = Depends(current_user)):
    """Tells the UI whether one-click OAuth is available on this server."""
    return {"oauth": oauth_configured()}


@router.get("/oauth/start")
async def oauth_start(user: CurrentUser = Depends(current_user)):
    """Mint a CSRF state and hand the UI the Vercel install URL to open."""
    if not oauth_configured():
        raise HTTPException(status_code=503,
                            detail="Vercel OAuth is not configured on this server yet.")
    state = new_oauth_state(user.email)
    return {"url": f"https://vercel.com/integrations/{VERCEL_INTEGRATION_SLUG}/new"
                   f"?state={state}"}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = "",
    state: str = "",
    teamId: str = "",
    configurationId: str = "",
    next_url: str = Query("", alias="next"),
    user: CurrentUser = Depends(current_user),
):
    """Vercel redirects the install popup here (cookie-authenticated through
    the gateway). Exchange the one-shot code for a long-lived token, store it
    encrypted, then send the popup back to Vercel's `next` URL to finish."""
    if not oauth_configured():
        raise HTTPException(status_code=503,
                            detail="Vercel OAuth is not configured on this server yet.")
    owner = pop_oauth_state(state)
    if not owner or owner != user.email:
        raise HTTPException(status_code=400,
                            detail="Connect session expired or mismatched. Please start again.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code from Vercel.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{VERCEL_API}/v2/oauth/access_token",
            data={"client_id": VERCEL_CLIENT_ID,
                  "client_secret": VERCEL_CLIENT_SECRET,
                  "code": code,
                  "redirect_uri": VERCEL_REDIRECT_URI})
    if r.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"Vercel token exchange failed (HTTP {r.status_code}).")
    data = r.json() or {}
    token = data.get("access_token") or ""
    if not token:
        raise HTTPException(status_code=502, detail="Vercel returned no access token.")
    team_id = data.get("team_id") or (teamId or None)
    try:
        username = await _vercel_username(token)
    except Exception:
        username = "connected"
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        await conn.execute(
            "INSERT INTO vercel_tokens (user_email, token_enc, team_id, username, configuration_id) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (user_email) DO UPDATE SET token_enc = $2, team_id = $3, "
            "username = $4, configuration_id = $5, created_at = now()",
            user.email, crypto_utils.encrypt(token), team_id, username,
            (configurationId or None))
    finally:
        await conn.close()
    print(f"[vercel] oauth connected {user.email} (team={bool(team_id)})", flush=True)
    # Vercel's popup flow: returning to `next` closes the install popup.
    # Only follow it when it points back at Vercel (no open redirects).
    if next_url.startswith("https://vercel.com/"):
        return RedirectResponse(next_url)
    return HTMLResponse(
        "<html><body style=\"font-family:sans-serif;background:#111;color:#eee;"
        "display:flex;align-items:center;justify-content:center;height:100vh;\">"
        "<div style=\"text-align:center;\"><h2>Vercel connected!</h2>"
        "<p>You can close this window and hit Deploy.</p>"
        "<script>setTimeout(function(){window.close();},1200);</script>"
        "</div></body></html>")


@router.get("/status")
async def vercel_status(user: CurrentUser = Depends(current_user)):
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        tok = await _stored_token(conn, user.email)
    finally:
        await conn.close()
    return {"connected": bool(tok),
            "username": tok["username"] if tok else None}


@router.post("/connect")
async def vercel_connect(body: ConnectBody,
                         user: CurrentUser = Depends(current_user)):
    token = (body.token or "").strip()
    if len(token) < 10:
        raise HTTPException(status_code=400, detail="That does not look like a Vercel token.")
    try:
        username = await _vercel_username(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach Vercel to verify the token.")
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        await conn.execute(
            "INSERT INTO vercel_tokens (user_email, token_enc, team_id, username) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_email) DO UPDATE SET token_enc = $2, "
            "team_id = $3, username = $4, created_at = now()",
            user.email, crypto_utils.encrypt(token),
            (body.team_id or None), username)
    finally:
        await conn.close()
    return {"connected": True, "username": username}


@router.delete("/connect")
async def vercel_disconnect(user: CurrentUser = Depends(current_user)):
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        await conn.execute("DELETE FROM vercel_tokens WHERE user_email = $1",
                           user.email)
    finally:
        await conn.close()
    return {"connected": False}


@router.get("/deployments")
async def my_deployments(user: CurrentUser = Depends(current_user)):
    """slug -> live URL map for this user (drives the card links)."""
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        rows = await conn.fetch(
            "SELECT slug, url FROM vercel_deployments WHERE user_email = $1",
            user.email)
    finally:
        await conn.close()
    return {r["slug"]: r["url"] for r in rows}


@router.post("/deploy/{slug}")
async def deploy_app(slug: str, user: CurrentUser = Depends(current_user)):
    """Deploy apps/<slug> to the signed-in user's own Vercel account."""
    if not SLUG_RE.match(slug or ""):
        raise HTTPException(status_code=400, detail="Invalid slug.")
    conn = await _connect_db()
    try:
        await ensure_tables(conn)
        member = await conn.fetchval(
            "SELECT 1 FROM tasks.project_members "
            "WHERE slug = $1 AND user_email = $2", slug, user.email)
        if not member:
            raise HTTPException(status_code=403, detail="Not a member of this project.")
        tok = await _stored_token(conn, user.email)
        if not tok:
            raise HTTPException(status_code=400, detail="Connect your Vercel account first.")

        app_dir = os.path.join(APPS_ROOT, slug)
        if not os.path.isdir(app_dir):
            raise HTTPException(status_code=404, detail="App files not found.")
        try:
            files = to_vercel_files(collect_files(app_dir))
        except ValueError as e:
            raise HTTPException(status_code=413, detail=str(e))

        params = {"teamId": tok["team_id"]} if tok.get("team_id") else {}
        headers = {"Authorization": f"Bearer {tok['token']}"}
        payload = {"name": slug, "files": files, "target": "production",
                   "projectSettings": {"framework": None}}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{VERCEL_API}/v13/deployments",
                                  json=payload, headers=headers, params=params)
            if r.status_code not in (200, 202):
                detail = ""
                try:
                    detail = (r.json().get("error") or {}).get("message") or ""
                except Exception:
                    pass
                raise HTTPException(status_code=502,
                                    detail=f"Vercel deploy failed (HTTP {r.status_code}). {detail[:160]}")
            dep = r.json()
            dep_id, url = dep.get("id"), dep.get("url")
            # Poll until the deployment settles (static builds are fast).
            state = dep.get("readyState") or "QUEUED"
            for _ in range(40):
                if state in ("READY", "ERROR", "CANCELED"):
                    break
                await asyncio.sleep(3)
                pr = await client.get(f"{VERCEL_API}/v13/deployments/{dep_id}",
                                      headers=headers, params=params)
                if pr.status_code == 200:
                    state = pr.json().get("readyState") or state
        if state != "READY":
            raise HTTPException(status_code=502,
                                detail=f"Deployment did not become ready (state: {state}).")
        live = f"https://{url}"
        await conn.execute(
            "INSERT INTO vercel_deployments (slug, user_email, url) "
            "VALUES ($1, $2, $3) ON CONFLICT (slug, user_email) "
            "DO UPDATE SET url = $3, deployed_at = now()",
            slug, user.email, live)
    finally:
        await conn.close()
    print(f"[vercel] deployed {slug} for {user.email} -> {live}", flush=True)
    return {"url": live, "state": state}
