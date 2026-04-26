"""SQL execution endpoint for project-owned Supabase databases.

`POST /api/projects/{slug}/db/sql` runs arbitrary SQL on the project's
Postgres connection. There are two execution paths:

1. **OAuth / Management API** — preferred. If the project row has an
   `oauth_access_token_encrypted` AND `linked_project_ref`, we POST the
   query to `https://api.supabase.com/v1/projects/{ref}/database/query`
   with a bearer token. On 401 we refresh the token once and retry.

2. **asyncpg + URI** — legacy / manual config fallback. If only
   `db_uri_encrypted` is set, we open a direct Postgres connection via
   asyncpg and run the SQL there.

Used by Claude during BUILD to create tables, set up RLS, etc.
autonomously. Owner-only.
"""
import asyncio
import time

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import crypto_utils
from auth import AdminUser, current_admin
from db import session
from models import ProjectSupabase
from routes_projects import _require_role, _validate_slug

router = APIRouter(prefix="/api/projects")

QUERY_TIMEOUT_SECONDS = 10
CONNECT_TIMEOUT_SECONDS = 5


class SqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)


class SqlResponse(BaseModel):
    rows: list[dict]
    rowcount: int
    executed_ms: int


@router.post("/{slug}/db/sql", response_model=SqlResponse)
async def execute_sql(
    slug: str,
    body: SqlRequest,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="No database connection is configured for this project — "
                       "connect Supabase via OAuth (recommended) or paste a Postgres "
                       "connection URI in the Database tab.",
            )

        # OAuth path takes precedence — uses Supabase Management API.
        if row.oauth_access_token_encrypted and row.linked_project_ref:
            return await _exec_via_management_api(s, row, body.sql)

        # Legacy / manual path — asyncpg direct connection via URI.
        if row.db_uri_encrypted:
            try:
                db_uri = crypto_utils.decrypt(row.db_uri_encrypted)
            except Exception:
                raise HTTPException(
                    status_code=500,
                    detail="Could not decrypt the stored DB URI — re-paste it in the Database tab.",
                )
            return await _exec_via_asyncpg(db_uri, body.sql)

        raise HTTPException(
            status_code=409,
            detail="No database connection is configured for this project — "
                   "connect Supabase via OAuth (recommended) or paste a Postgres "
                   "connection URI in the Database tab.",
        )


async def _exec_via_management_api(s, row, sql: str) -> SqlResponse:
    """Run SQL via Supabase Management API using the OAuth bearer token.

    On 401 we treat the cached access token as stale, force a refresh
    through `_ensure_fresh_token`, and retry the request once.
    """
    # Local import to avoid a circular import at module load time —
    # routes_supabase_oauth itself imports nothing from this module.
    from routes_supabase_oauth import _ensure_fresh_token

    started = time.perf_counter()
    access = await _ensure_fresh_token(s, row)
    project_ref = row.linked_project_ref
    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
    }
    payload = {"query": sql}

    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=QUERY_TIMEOUT_SECONDS + 5) as c:
        try:
            resp = await c.post(url, headers=headers, json=payload)
        except _httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail=f"Management API call exceeded {QUERY_TIMEOUT_SECONDS}s.",
            )
        # If the cached token is rejected, mark it stale, refresh, retry once.
        if resp.status_code == 401:
            row.oauth_expires_at = None
            access = await _ensure_fresh_token(s, row)
            headers["Authorization"] = f"Bearer {access}"
            try:
                resp = await c.post(url, headers=headers, json=payload)
            except _httpx.TimeoutException:
                raise HTTPException(
                    status_code=504,
                    detail=f"Management API call exceeded {QUERY_TIMEOUT_SECONDS}s.",
                )

    if resp.status_code == 400:
        # Surface the SQL error message from Postgres.
        try:
            err = resp.json().get("message") or resp.text
        except Exception:
            err = resp.text
        raise HTTPException(status_code=400, detail=f"SQL error: {err[:500]}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Management API returned HTTP {resp.status_code}: {resp.text[:300]}",
        )
    rows = resp.json() or []
    if not isinstance(rows, list):
        rows = []
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return SqlResponse(rows=rows, rowcount=len(rows), executed_ms=elapsed_ms)


async def _exec_via_asyncpg(db_uri: str, sql: str) -> SqlResponse:
    """Run SQL via a direct asyncpg connection parsed from a Postgres URI.

    This is the legacy / manual-config path. The URI parser uses a regex
    rather than urllib because Supabase URIs can contain unescaped
    special chars in passwords and stray brackets around the host that
    confuse urlparse.
    """
    # Parse the URI with a regex (NOT urllib) — Python's urlparse trips on
    # Supabase URIs that contain unescaped special chars in the password
    # AND on hostnames it mistakes for IPv6 (Supabase sometimes ships URIs
    # with stray `[...]` brackets around the host). Regex-only is robust.
    import re
    from urllib.parse import unquote
    db_uri_clean = db_uri.strip()
    m = re.match(
        r"^(?P<scheme>postgres(?:ql)?)://"
        r"(?:(?P<user>[^:@/]+)(?::(?P<password>[^@]+))?@)?"
        r"\[?(?P<host>[^:/\]]+)\]?"   # optional brackets around host
        r"(?::(?P<port>\d+))?"
        r"(?:/(?P<database>[^?]+))?"
        r"(?:\?.*)?$",
        db_uri_clean,
    )
    if not m:
        raise HTTPException(
            status_code=400,
            detail="DB URI didn't match expected shape postgresql://user:password@host:port/dbname",
        )
    user = unquote(m.group("user") or "postgres")
    password = unquote(m.group("password")) if m.group("password") else None
    host = m.group("host")
    port = int(m.group("port")) if m.group("port") else 5432
    database = m.group("database") or "postgres"
    if not host:
        raise HTTPException(status_code=400, detail="DB URI missing host — re-copy from Supabase.")

    # Common Supabase mistakes — surface a clear fix instead of an asyncpg error.
    if password and password.upper() in ("YOUR-PASSWORD", "[YOUR-PASSWORD]", "PASSWORD"):
        raise HTTPException(
            status_code=400,
            detail="Your DB URI still has the literal placeholder '[YOUR-PASSWORD]'. "
                   "Replace it with your actual database password from Supabase → "
                   "Project Settings → Database → Database password.",
        )
    if host.startswith("db.") and host.endswith(".supabase.co"):
        raise HTTPException(
            status_code=400,
            detail="That's the DIRECT connection (db.<ref>.supabase.co). It's IPv6-only "
                   "and our server can't reach it. Use the TRANSACTION POOLER URI instead "
                   "(port 6543, host aws-0-<region>.pooler.supabase.com). Find it in "
                   "Supabase → Project Settings → Database → Connection string → switch "
                   "the dropdown to 'Transaction pooler'.",
        )

    started = time.perf_counter()
    conn = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host, port=port, user=user, password=password,
                database=database, statement_cache_size=0,
            ),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        result = await asyncio.wait_for(
            conn.fetch(sql),
            timeout=QUERY_TIMEOUT_SECONDS,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        rows = [dict(r) for r in result]
        return SqlResponse(rows=rows, rowcount=len(rows), executed_ms=elapsed_ms)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Query exceeded {QUERY_TIMEOUT_SECONDS}s timeout.",
        )
    except asyncpg.PostgresError as exc:
        # SQL/syntax/permission errors → 400 with the Postgres message.
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}")
    except (OSError, asyncpg.InterfaceError) as exc:
        # Connection problems (host unreachable, auth failure, etc.).
        raise HTTPException(status_code=502, detail=f"Could not connect: {exc}")
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
