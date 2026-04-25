"""Tasks service — admin task approval and AI execution."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import init_db
from routes_cron import router as cron_router
from routes_db import router as db_router
from routes_execution import router as execution_router
from routes_preview import router as preview_router
from routes_projects import router as projects_router
from routes_supabase import router as supabase_router
from routes_tasks import router as tasks_router
from routes_webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    yield


app = FastAPI(title="Tasks Service", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(tasks_router)
app.include_router(execution_router)
app.include_router(cron_router)
app.include_router(preview_router)
app.include_router(projects_router)
app.include_router(supabase_router)
app.include_router(db_router)
app.mount("/tasks/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}


@app.get("/tasks/app-builder", include_in_schema=False)
async def app_builder_page() -> FileResponse:
    """Pretty URL for the app-builder SPA. Serves static/projects.html."""
    return FileResponse("static/projects.html", media_type="text/html")


# ---------------------------------------------------------------------------
# Public hosting for published apps. Caddy rewrites
#   <slug>.ai-ui.coolestdomain.win/<path>  →  /__public/<slug>/<path>
# and proxies into this service. We serve files directly from the
# /workspace/ai_ui/apps/<slug>/ directory if (and only if) the slug has a
# row in tasks.published_apps. Strict path validation prevents traversal.
# ---------------------------------------------------------------------------
import os as _os
import re as _re
from urllib.parse import unquote
from fastapi import HTTPException, Request, Response
from sqlalchemy import select as _select

from db import session as _db_session
from models import PublishedApp as _PublishedApp

_APP_ROOT_FS = "/workspace/ai_ui/apps"
_SLUG_ROUTE_RE = _re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

_MIME_BY_EXT = {
    ".html": "text/html; charset=utf-8",
    ".htm":  "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "text/javascript; charset=utf-8",
    ".mjs":  "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".ico":  "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf":  "font/ttf",
    ".txt":  "text/plain; charset=utf-8",
    ".xml":  "application/xml; charset=utf-8",
}


def _parse_custom_host(host: str) -> tuple[str, str] | None:
    """Split a custom-domain host '<slug>.<parent>' into (slug, parent).
    Requires at least 3 labels (e.g. app.example.com). Lowercased + de-dotted."""
    parts = (host or "").lower().strip().rstrip(".").split(".")
    if len(parts) < 3:
        return None
    return parts[0], ".".join(parts[1:])


@app.get("/__caddy/check_ask", include_in_schema=False)
async def caddy_on_demand_ask(domain: str = ""):
    """Caddy on-demand TLS gatekeeper. Returns 200 only when domain matches
    <slug>.<parent> for a verified, published app. Blocks Let's Encrypt
    rate-limit abuse via random hostnames."""
    domain = (domain or "").strip().lower().rstrip(".")
    parsed = _parse_custom_host(domain)
    if not parsed:
        raise HTTPException(status_code=404, detail="not a published app subdomain")
    slug, parent = parsed
    async with _db_session() as s:
        row = (
            await s.execute(
                _select(_PublishedApp).where(
                    _PublishedApp.slug == slug,
                    _PublishedApp.custom_domain == parent,
                    _PublishedApp.custom_domain_verified_at.isnot(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="domain not allowed")
    return {"ok": True}


@app.get("/__public_by_host", include_in_schema=False)
@app.get("/__public_by_host/", include_in_schema=False)
@app.get("/__public_by_host/{file_path:path}", include_in_schema=False)
async def serve_published_app_by_host(
    file_path: str = "",
    request: Request = None,
):
    """Catch-all for custom domains. Caddy rewrites
       <slug>.<parent>/<path>  →  /__public_by_host/<path>
    with the original Host preserved via X-Forwarded-Host."""
    fwd = request.headers.get("x-forwarded-host") if request else None
    raw_host = (fwd or (request.headers.get("host") if request else "") or "").lower()
    host = raw_host.split(":")[0].strip()
    parsed = _parse_custom_host(host)
    if not parsed:
        raise HTTPException(status_code=404, detail="invalid host")
    slug, parent = parsed
    async with _db_session() as s:
        row = (
            await s.execute(
                _select(_PublishedApp).where(
                    _PublishedApp.slug == slug,
                    _PublishedApp.custom_domain == parent,
                    _PublishedApp.custom_domain_verified_at.isnot(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no app at this domain")
    return await serve_published_app(slug=row.slug, file_path=file_path, request=request)


async def _supabase_inject_for(slug: str) -> str:
    """Return the <script> snippet to inject for this slug, or '' if no config."""
    from models import ProjectSupabase as _ProjSb
    import crypto_utils as _crypto
    import json
    async with _db_session() as s:
        row = (await s.execute(
            _select(_ProjSb).where(_ProjSb.slug == slug)
        )).scalar_one_or_none()
    if row is None:
        return ""
    try:
        anon = _crypto.decrypt(row.anon_key_encrypted)
    except Exception:
        return ""  # corrupt token / wrong key — fail silently rather than 500
    url_js = json.dumps(row.supabase_url)
    key_js = json.dumps(anon)
    return (
        "<script>"
        f"window.SUPABASE_URL={url_js};"
        f"window.SUPABASE_ANON_KEY={key_js};"
        "</script>"
    )


@app.get("/__public/{slug}", include_in_schema=False)
@app.get("/__public/{slug}/", include_in_schema=False)
@app.get("/__public/{slug}/{file_path:path}", include_in_schema=False)
async def serve_published_app(
    slug: str,
    file_path: str = "",
    request: Request = None,
):
    if not _SLUG_ROUTE_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    # Decode + normalize path; reject traversal.
    rel = unquote(file_path or "").lstrip("/")
    if not rel:
        rel = "index.html"
    if ".." in rel.split("/") or rel.startswith("/") or "\x00" in rel:
        raise HTTPException(status_code=400, detail="Invalid path")

    async with _db_session() as s:
        row = (
            await s.execute(_select(_PublishedApp).where(_PublishedApp.slug == slug))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="App not published")

    base = _os.path.realpath(_os.path.join(_APP_ROOT_FS, slug))
    target = _os.path.realpath(_os.path.join(base, rel))
    # realpath sanity: must stay within base
    if not target.startswith(base + _os.sep) and target != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not _os.path.isfile(target):
        # SPA-style fallback: if a path with no extension doesn't exist, fall
        # back to index.html so client-side routers work.
        if "." not in _os.path.basename(rel):
            target = _os.path.join(base, "index.html")
            if not _os.path.isfile(target):
                raise HTTPException(status_code=404, detail="Not found")
        else:
            raise HTTPException(status_code=404, detail="Not found")

    ext = _os.path.splitext(target)[1].lower()
    media = _MIME_BY_EXT.get(ext, "application/octet-stream")

    if ext in (".html", ".htm"):
        with open(target, "rb") as f:
            body = f.read().decode("utf-8", errors="replace")
        snippet = await _supabase_inject_for(slug)
        if snippet:
            lower = body.lower()
            head_idx = lower.find("<head>")
            if head_idx >= 0:
                body = body[: head_idx + 6] + snippet + body[head_idx + 6 :]
            else:
                body = snippet + body
        return Response(content=body, media_type=media,
                        headers={"Cache-Control": "public, max-age=120"})

    return FileResponse(
        target,
        media_type=media,
        headers={"Cache-Control": "public, max-age=120"},
    )
