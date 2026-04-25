"""SQL execution endpoint for project-owned Supabase databases.

`POST /api/projects/{slug}/db/sql` runs arbitrary SQL on the project's
Postgres connection (URI stored encrypted in tasks.project_supabase). Used
by Claude during BUILD to create tables, set up RLS, etc. autonomously.
Owner-only.
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
        if row is None or not row.db_uri_encrypted:
            raise HTTPException(
                status_code=409,
                detail="No database connection URI configured for this project. "
                       "Add one in the Database tab → 'Database connection URI'.",
            )
        try:
            db_uri = crypto_utils.decrypt(row.db_uri_encrypted)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Could not decrypt the stored DB URI — re-paste it in the Database tab.",
            )

    started = time.perf_counter()
    conn = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(db_uri, statement_cache_size=0),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        result = await asyncio.wait_for(
            conn.fetch(body.sql),
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
