"""Tasks service — admin task approval and AI execution."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import init_db
from routes_chat_history import router as chat_history_router
from routes_cron import router as cron_router
from routes_db import router as db_router
from routes_execution import router as execution_router
from routes_graph import router as graph_router
from routes_preview import router as preview_router
from routes_projects import router as projects_router
from routes_schedules import router as schedules_router
from routes_supabase import router as supabase_router
from routes_supabase_oauth import router as supabase_oauth_router
from routes_tasks import router as tasks_router
from routes_templates import router as templates_router
from routes_upload import router as upload_router
from routes_webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    # Reap orphan tasks: anything in `running` status at startup belongs to
    # a dead worker process (this process can't have started one yet). If we
    # don't reap, the UI shows "Building…" forever for a build whose claude
    # subprocess died silently — exactly the symptom users hit after the OOM
    # cascade on 2026-04-27.
    try:
        from db import session as _sess
        from sqlalchemy import text as _txt
        async with _sess() as s:
            r = await s.execute(_txt(
                "UPDATE tasks.items SET status='failed', completed_at=now(), "
                "result=COALESCE(result,'') || E'\\n\\nBuild orphaned at restart — subprocess died silently. Click Retry or delete this project.' "
                "WHERE status='running' RETURNING id"
            ))
            reaped = list(r.fetchall())
            await s.execute(_txt(
                "UPDATE tasks.executions SET status='failed', finished_at=now(), "
                "error=COALESCE(error,'') || ' [reaped at restart]' "
                "WHERE status IN ('running','pending') AND finished_at IS NULL"
            ))
            await s.commit()
        if reaped:
            logger.warning("Reaped %d orphan running task(s) at startup", len(reaped))
    except Exception as exc:
        logger.error("Orphan reap failed at startup: %s", exc)

    # Heartbeat scheduler — wakes once per minute, fires due schedules.
    # Inside lifespan so it definitely runs (FastAPI's @app.on_event hooks
    # are deprecated and may not execute reliably when `lifespan=` is set).
    # Inline import keeps scheduler optional if croniter isn't installed —
    # uvicorn won't fail to boot.
    try:
        from scheduler import schedule_tick_loop
        asyncio.create_task(schedule_tick_loop())
        logger.info("schedule_tick_loop scheduled")
    except Exception as exc:
        logger.warning("schedule_tick_loop NOT started: %s", exc)

    yield


app = FastAPI(title="Tasks Service", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(tasks_router)
app.include_router(execution_router)
app.include_router(cron_router)
app.include_router(preview_router)
app.include_router(projects_router)
app.include_router(schedules_router)
app.include_router(upload_router)
app.include_router(graph_router)
app.include_router(supabase_router)
app.include_router(supabase_oauth_router)
app.include_router(db_router)
app.include_router(chat_history_router)
app.include_router(templates_router)


@app.get("/healthz")
def healthz():
    """Liveness probe — no DB roundtrip. Used by deploy_orchestrator.sh."""
    return {"status": "ok"}


@app.on_event("startup")
async def _start_idle_sweep():
    """Spawn the per-slug auto-stop sweep so previews don't hold ports
    after the last user leaves. See app_runner._idle_sweep_loop."""
    import app_runner as _ar
    from routes_projects import is_slug_presence_empty
    asyncio.create_task(_ar._idle_sweep_loop(is_slug_presence_empty))


app.mount("/tasks/static", StaticFiles(directory="static"), name="static")
# Read-only public mount of the bundled template reference apps. The
# /tasks/template-apps path is intercepted by Open WebUI's service worker
# (which claims the /tasks/ scope) and returns a stale 404. The
# /api/template-preview path is NOT under any SW scope (the gallery's
# /api/templates JSON call already proves /api/* bypasses the SW), so we
# expose the same files there for use as live iframe previews.
app.mount("/tasks/template-apps", StaticFiles(directory="template_apps", html=True), name="template-apps")
app.mount("/api/template-preview", StaticFiles(directory="template_apps", html=True), name="template-preview")


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

# Bumped when picker.js itself changes — busts the iframe browser cache for
# preview HTML served with ?picker=1. Module-level so tests and routes share it.
PICKER_JS_VERSION = "3"

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


# AIUI parent host derived from AIUI_PUBLIC_BASE_URL (e.g. "ai-ui.coolestdomain.win").
# Subdomains under this host (e.g. "<slug>.ai-ui.coolestdomain.win") are auto-allowed
# for on-demand TLS provided the slug's app directory exists on disk.
def _aiui_parent_host() -> str:
    raw = _os.environ.get("AIUI_PUBLIC_BASE_URL", "").strip().rstrip("/")
    # strip scheme
    for prefix in ("https://", "http://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
            break
    # drop any path component — only the host part is the parent
    return raw.split("/")[0].lower()


def _parse_custom_host(host: str) -> tuple[str, str] | None:
    """Split a custom-domain host '<slug>.<parent>' into (slug, parent).
    Requires at least 3 labels (e.g. app.example.com). Lowercased + de-dotted."""
    parts = (host or "").lower().strip().rstrip(".").split(".")
    if len(parts) < 3:
        return None
    return parts[0], ".".join(parts[1:])


@app.get("/__caddy/check_ask", include_in_schema=False)
async def caddy_on_demand_ask(domain: str = ""):
    """Caddy on-demand TLS gatekeeper. Returns 200 in two cases:

    1. <slug>.<AIUI_PUBLIC_HOST> where the slug has an app directory on
       disk under apps/. This makes the AIUI managed parent permissive
       (any app a user has built is reachable at its subdomain) while
       still blocking arbitrary domain-name attacks.

    2. <slug>.<custom_domain> where (slug, custom_domain) matches a
       verified row in published_apps. This is the user-provided custom
       domain path (e.g. myapp.example.com) and stays gated.

    Anything else returns 404 to deny TLS cert issuance.
    """
    domain = (domain or "").strip().lower().rstrip(".")
    parsed = _parse_custom_host(domain)
    if not parsed:
        raise HTTPException(status_code=404, detail="not a recognized subdomain")
    slug, parent = parsed

    if not _SLUG_ROUTE_RE.match(slug):
        raise HTTPException(status_code=404, detail="invalid slug")

    # Path 1: AIUI parent host (e.g. "ai-ui.coolestdomain.win"). Allow if
    # the slug has a real app directory on disk.
    aiui_parent = _aiui_parent_host()
    if aiui_parent and parent == aiui_parent:
        app_dir = _os.path.join(_APP_ROOT_FS, slug)
        if _os.path.isdir(app_dir):
            return {"ok": True, "reason": "aiui-subdomain"}
        raise HTTPException(status_code=404, detail="app not found on disk")

    # Path 2: User-provided custom domain. Must be verified in published_apps.
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
    return {"ok": True, "reason": "verified-custom-domain"}


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

    if not _SLUG_ROUTE_RE.match(slug):
        raise HTTPException(status_code=404, detail="invalid slug")

    # Path 1: AIUI managed parent (e.g. "<slug>.ai-ui.coolestdomain.win").
    # Allow if the slug's app dir exists on disk — same model as
    # caddy_on_demand_ask. The published_apps row is no longer required
    # at the access layer; it's now a "draft / published" flag only.
    aiui_parent = _aiui_parent_host()
    if aiui_parent and parent == aiui_parent:
        if _os.path.isdir(_os.path.join(_APP_ROOT_FS, slug)):
            return await serve_published_app(slug=slug, file_path=file_path, request=request)
        raise HTTPException(status_code=404, detail="no app at this domain")

    # Path 2: User-provided custom domain. Must be verified in published_apps.
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


@app.get("/__preview_config.js", include_in_schema=False)
async def preview_config_js() -> Response:
    """Return JS that sets window.SUPABASE_URL/KEY for the currently-running
    preview app. Caddy routes /tasks/preview-app/aiui-config.js → here BEFORE
    the dev-server proxy (more-specific path wins)."""
    import json
    import app_runner as _ar
    from models import ProjectSupabase as _ProjSb
    import crypto_utils as _crypto

    cur = getattr(_ar, "_current", None)
    if not cur or not cur.get("slug"):
        return Response("// No preview running.\n", media_type="text/javascript")

    slug = cur["slug"]
    async with _db_session() as s:
        row = (await s.execute(
            _select(_ProjSb).where(_ProjSb.slug == slug)
        )).scalar_one_or_none()
    if row is None:
        return Response(
            f"// Slug {slug!r} has no Supabase config.\n",
            media_type="text/javascript",
        )
    try:
        anon = _crypto.decrypt(row.anon_key_encrypted)
    except Exception:
        return Response("// Could not decrypt anon key.\n", media_type="text/javascript")
    body = (
        f"window.SUPABASE_URL={json.dumps(row.supabase_url)};"
        f"window.SUPABASE_ANON_KEY={json.dumps(anon)};"
        f"window.AIUI_SLUG={json.dumps(slug)};\n"
    )
    return Response(
        content=body,
        media_type="text/javascript",
        headers={"Cache-Control": "no-store"},
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

    # Access gate: <slug>.ai-ui.<domain>/ is the *published* URL. Drafts
    # remain reachable only via /tasks/preview-app/<slug>/. A short-lived
    # 2026-04-30 change relaxed this so any app on disk was reachable, but
    # that broke the Publish/Unpublish UI — toggling no longer affected
    # public access. Restore the gate: no published_apps row → 404 (and
    # no Supabase config leak via aiui-config.js below).
    async with _db_session() as s:
        published_row = (await s.execute(
            _select(_PublishedApp).where(_PublishedApp.slug == slug).limit(1)
        )).scalar_one_or_none()
    if published_row is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Synthesize aiui-config.js for the published path so the same agent code
    # works both in preview and published contexts.
    if rel == "aiui-config.js":
        import json as _json
        from models import ProjectSupabase as _ProjSb2
        import crypto_utils as _crypto2
        async with _db_session() as s:
            row = (await s.execute(
                _select(_ProjSb2).where(_ProjSb2.slug == slug)
            )).scalar_one_or_none()
        if row is None:
            return Response("// No Supabase config.\n", media_type="text/javascript")
        try:
            anon = _crypto2.decrypt(row.anon_key_encrypted)
        except Exception:
            return Response("// Could not decrypt anon key.\n", media_type="text/javascript")
        js_body = (
            f"window.SUPABASE_URL={_json.dumps(row.supabase_url)};"
            f"window.SUPABASE_ANON_KEY={_json.dumps(anon)};"
            f"window.AIUI_SLUG={_json.dumps(slug)};\n"
        )
        return Response(content=js_body, media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})

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


# ---------------------------------------------------------------------------
# Per-slug preview hosting. Caddy proxies /tasks/preview-app/* into this
# service. We support two flavors of preview:
#
#   1. Static apps (the common case — vanilla HTML/CSS/JS + Alpine + Tailwind)
#      have NO spawned server. We just serve files from
#      /workspace/ai_ui/apps/<slug>/<path> directly. Two users on different
#      apps means two independent file-server responses — zero conflict.
#
#   2. Dynamic apps (Node/Python servers) are registered in app_runner with
#      a per-slug port from a 9100-9119 pool. We reverse-proxy GET requests
#      to localhost:<port> from inside this same container.
#
# This replaces the old single-slot model where one running preview would
# kill any other user's preview.
# ---------------------------------------------------------------------------
import app_runner as _app_runner


@app.get("/tasks/preview-app/{slug}", include_in_schema=False)
@app.get("/tasks/preview-app/{slug}/", include_in_schema=False)
@app.get("/tasks/preview-app/{slug}/{file_path:path}", include_in_schema=False)
async def serve_preview_app(
    slug: str,
    file_path: str = "",
    request: Request = None,
):
    if not _SLUG_ROUTE_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    rel = unquote(file_path or "").lstrip("/")
    if not rel:
        rel = "index.html"
    if ".." in rel.split("/") or rel.startswith("/") or "\x00" in rel:
        raise HTTPException(status_code=400, detail="Invalid path")

    # Dynamic preview: reverse-proxy to the slug's spawned port.
    info = _app_runner._running.get(slug)
    if info is not None and info.get("port") and info.get("kind") != "static":
        import httpx as _httpx
        port = info["port"]
        upstream = f"http://localhost:{port}/{rel}"
        try:
            async with _httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    upstream,
                    params=request.query_params if request else None,
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Preview server unreachable: {exc}")
        # Strip hop-by-hop headers
        skip = {"transfer-encoding", "content-encoding", "connection", "content-length"}
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
        return Response(content=resp.content, status_code=resp.status_code,
                        headers=out_headers, media_type=resp.headers.get("content-type"))

    # Static preview: serve the file from disk (mirrors serve_published_app).
    base = _os.path.realpath(_os.path.join(_APP_ROOT_FS, slug))
    target = _os.path.realpath(_os.path.join(base, rel))
    if not target.startswith(base + _os.sep) and target != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not _os.path.isfile(target):
        # SPA-style fallback: dirless paths fall back to index.html.
        if "." not in _os.path.basename(rel):
            target = _os.path.join(base, "index.html")
        # Single-HTML uploads: a project may ship one .html that isn't named
        # index.html (e.g. user dropped 'aiui-design.html'). When the request
        # resolves to a missing index.html, fall back to the first top-level
        # .html file so the preview iframe just works without us writing a
        # duplicate alias file to disk.
        if _os.path.basename(target) == "index.html" and not _os.path.isfile(target):
            try:
                top_html = sorted(
                    f for f in _os.listdir(base)
                    if f.lower().endswith(".html")
                    and _os.path.isfile(_os.path.join(base, f))
                )
            except OSError:
                top_html = []
            if top_html:
                target = _os.path.join(base, top_html[0])
        if not _os.path.isfile(target):
            raise HTTPException(status_code=404, detail="Not found")

    ext = _os.path.splitext(target)[1].lower()
    media = _MIME_BY_EXT.get(ext, "application/octet-stream")

    # Picker injection: when serving HTML from the preview, splice
    # <script src="/tasks/static/picker.js?v=N"></script> before </head>.
    # The script is inert by default — it only listens for activate/deactivate
    # messages from the parent — so the cost is one tiny extra fetch per
    # preview load. Always-on injection means clicking the parent's "Select"
    # toggle does NOT need to reload the iframe, which preserves any in-app
    # state the user is testing (form values, route, scroll position, etc.).
    # Any failure (binary file, missing </head>, decode error) falls through
    # to the standard FileResponse path — the picker is never load-bearing.
    if ext in (".html", ".htm"):
        try:
            with open(target, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8")
            head_close_idx = text.lower().find("</head>")
            if head_close_idx >= 0:
                tag = (
                    f'<script src="/tasks/static/picker.js?v={PICKER_JS_VERSION}"></script>'
                )
                rewritten = text[:head_close_idx] + tag + text[head_close_idx:]
                return Response(
                    content=rewritten,
                    media_type=media,
                    headers={"Cache-Control": "no-store"},
                )
            else:
                logger.warning(
                    "picker injection skipped: no </head> in %s/%s",
                    slug,
                    rel,
                )
        except Exception as exc:
            logger.warning(
                "picker injection failed for %s/%s: %s", slug, rel, exc
            )

    return FileResponse(
        target,
        media_type=media,
        headers={"Cache-Control": "no-store"},
    )
