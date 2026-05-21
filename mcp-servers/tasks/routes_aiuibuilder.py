"""User-scoped one-shot App Builder build entry point (for Discord).

`current_user` (X-User-Email) auth — NOT admin. Mirrors what the web
create+execute flow does, but ownership-scoped to the caller, reusing the
existing _run_execution agent pipeline. No new tables.
"""
import asyncio
import logging
import os
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from auth import CurrentUser, current_user
from db import session
from models import ProjectMember, PublishedApp, TaskExecution, TaskItem
from templates import is_valid_key
from routes_projects import _publish_slug, _unpublish_slug, _validate_slug, PublishStatus

logger = logging.getLogger("tasks.aiuibuilder")

router = APIRouter(prefix="/api/aiuibuilder")

# Route-slug regex (hyphen-only). Defined locally to avoid a circular import
# from main.py (which imports this router); mirrors main._SLUG_ROUTE_RE.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

# Internal TaskItem.status values where the agent subprocess is ACTIVELY
# running (and thus occupying the single agent / RAM). NOT awaiting_input:
# when a build is awaiting_input the agent has already exited (it asked a
# question and _run_execution returned), so it isn't using the agent and must
# NOT block new builds — otherwise one ambiguous Discord build would 429-lock
# the whole platform until someone resolves it in the web UI.
_LIVE_BUILD_STATES = ("running", "planning")

# Same default as routes_projects.PUBLIC_DOMAIN.
PUBLIC_DOMAIN = os.environ.get("AIUI_PUBLIC_DOMAIN", "ai-ui.coolestdomain.win")


class BuildRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    name: str | None = Field(default=None, max_length=80)
    template_key: str | None = Field(default=None, max_length=64)


class BuildResponse(BaseModel):
    task_id: str
    slug: str
    status: str


class BuildStatusResponse(BaseModel):
    status: str
    slug: str
    preview_url: str | None = None
    error: str | None = None


# Catalog keys equivalent to a template-less Discord build (`custom` has no
# rules; `blank` asks clarifying questions that can't be answered over Discord).
# Excluded so the bot treats `build blank …`/`build custom …` as template-less.
_CATALOG_EXCLUDED_KEYS = frozenset({"blank", "custom"})


class TemplateBrief(BaseModel):
    key: str
    label: str
    emoji: str
    description: str
    has_app: bool
    note: str


def _template_note(key: str, storage: str) -> str:
    """Discord-facing storage hint. `auth` is the only template with no
    localStorage fallback (flagged web-only); other db-backed templates degrade
    to browser storage; frontend-only templates need no note."""
    if key == "auth":
        return "needs Supabase — use the web App Builder"
    if storage == "supabase":
        return "saves in your browser"
    return ""


def _normalize_template_key(template_key: str | None) -> str | None:
    """Normalize an inbound build template key.

    Catalog-excluded keys (`blank`/`custom`) map to None — they're equivalent to
    a template-less build, and `blank`'s clarify-first rules would dead-end a
    Discord build in `awaiting_input`. The bot never sends them (they're absent
    from the catalog it reads); this is defense-in-depth for any direct caller.
    An otherwise-unknown key is a 422."""
    if template_key is None or template_key in _CATALOG_EXCLUDED_KEYS:
        return None
    if not is_valid_key(template_key):
        raise HTTPException(status_code=422, detail="Unknown template")
    return template_key


def _slugify(seed: str) -> str:
    """Lowercase + hyphenate the first ~5 words; cap length. Pure (no DB)."""
    s = re.sub(r"[^a-z0-9]+", "-", (seed or "").strip().lower())
    words = [w for w in s.split("-") if w][:5]
    base = "-".join(words)[:40].strip("-")
    return base or "app"


def _make_slug(seed: str) -> str:
    """Slugify + a 4-hex suffix for uniqueness (collision-checked elsewhere)."""
    return f"{_slugify(seed)}-{secrets.token_hex(2)}"


def _public_build_status(task_status: str) -> str:
    """Map an internal TaskItem.status to the small public build status.

    Only `running`/`planning` mean the agent is still working. `awaiting_input`
    is terminal for a Discord-origin build — the agent exited asking a question
    and there is no Discord answer path — so it surfaces as `needs_input`.
    Anything else a build could land in (`pending` after an exception,
    `claimed_manual`) is a dead end for Discord and surfaces as `failed`. This
    keeps the watcher from polling forever on a build that already settled.
    """
    if task_status == "completed":
        return "completed"
    if task_status == "awaiting_input":
        return "needs_input"
    if task_status in ("running", "planning"):
        return "running"
    return "failed"


def _preview_url(slug: str) -> str:
    return f"https://{PUBLIC_DOMAIN}/tasks/preview-app/{slug}/"


def _bind_slug_description(slug: str, description: str) -> str:
    """Prefix the user's request with an explicit slug directive so the agent
    builds at apps/<slug>/ (the uniqueness-checked slug we allocated) instead
    of inventing its own folder name from the prompt text.

    Without this the agent picks its own slug, which (a) orphans the scaffolded
    dir, (b) makes the 'Building <slug>' ack disagree with the final app, and
    (c) — the real hazard — defeats `_unique_slug`'s collision check, so a build
    whose content happens to map to an existing project's name would overwrite
    that project's files. Mirrors the slug directive the web template-build path
    injects in routes_tasks.create_task. Capped at 20k like the web path."""
    directive = (
        f'PROJECT NAME: "{slug}". Create the app at apps/{slug}/ and use this '
        f'exact slug throughout — do NOT invent a different folder name.\n\n'
        f'USER REQUEST:\n'
    )
    return (directive + (description or "").strip())[:20_000]


def _compose_build_description(slug: str, template_key: str | None, description: str) -> str:
    """Compose the agent build description.

    Template-less keeps the shipped slug-bound form byte-for-byte. With a
    template, inject that template's curated rules (storage forced 'none' —
    no Supabase gate from Discord) between the slug directive and the user
    request, mirroring routes_tasks.create_task. Capped at 20k like the web."""
    if not template_key:
        return _bind_slug_description(slug, description)
    from templates import build_rules_for
    directive = (
        f'PROJECT NAME: "{slug}". Create the app at apps/{slug}/ and use this '
        f'exact slug throughout — do NOT invent a different folder name.'
    )
    rules = build_rules_for(template_key, "none").strip()
    user_req = "USER REQUEST:\n" + (description or "").strip()
    parts = [directive] + ([rules] if rules else []) + [user_req]
    return "\n\n".join(parts)[:20_000]


async def _slug_taken(s, slug: str) -> bool:
    """True if `slug` collides in items / published_apps / project_members.
    Mirrors the rename collision check in routes_projects.py."""
    if (await s.execute(
        select(TaskItem.id).where(TaskItem.built_app_slug == slug).limit(1)
    )).scalar_one_or_none():
        return True
    if (await s.execute(
        select(PublishedApp.slug).where(PublishedApp.slug == slug).limit(1)
    )).scalar_one_or_none():
        return True
    return bool((await s.execute(
        select(ProjectMember.slug).where(ProjectMember.slug == slug).limit(1)
    )).scalar_one_or_none())


async def _unique_slug(s, seed: str) -> str:
    """A route-valid slug not already used. Regenerates the suffix on clash.

    Must be called under the 'aiuibuilder:build' advisory lock so the
    check-then-use is race-free. Every candidate (including the high-entropy
    exhaustion fallback) is DB-checked before being returned — we never return
    an unchecked slug. Raises 503 if we somehow can't allocate one."""
    for _ in range(8):
        slug = _make_slug(seed)
        if _SLUG_RE.match(slug) and not await _slug_taken(s, slug):
            return slug
    # Exhausted the readable-name attempts — try a few high-entropy fallbacks,
    # still DB-checked so we never write a duplicate built_app_slug.
    for _ in range(4):
        slug = f"app-{secrets.token_hex(4)}"
        if not await _slug_taken(s, slug):
            return slug
    raise HTTPException(status_code=503, detail="Could not allocate a unique slug, try again")


async def _create_and_spawn_build(
    email: str, seed: str, description: str, template_key: str | None = None,
) -> tuple[str, str]:
    """Create a BUILD task owned by `email` and spawn the agent run.

    One build platform-wide at a time: raises HTTPException(429) if any BUILD
    task is already in a live state. With `template_key`, the template's rules
    are injected (storage forced 'none') and its prebuilt base app is copied in.
    Returns (task_id, slug).
    """
    from claude_executor import build_prompt
    from routes_execution import _RUNNING, _run_execution
    from routes_tasks import _copy_template_app, _ensure_app_skeleton, _humanize_slug
    from templates import _has_template_app

    template_key = _normalize_template_key(template_key)

    meeting_id = uuid.uuid4()
    async with session() as s:
        # Serialize the guard so two near-simultaneous builds can't both pass.
        await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('aiuibuilder:build'))"))
        in_flight = (await s.execute(
            select(TaskItem.id).where(
                TaskItem.action_type == "BUILD",
                TaskItem.status.in_(_LIVE_BUILD_STATES),
            ).limit(1)
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(status_code=429, detail="A build is already running")

        slug = await _unique_slug(s, seed)
        bound_description = _compose_build_description(slug, template_key, description)
        item = TaskItem(
            meeting_id=meeting_id,
            action_type="BUILD",
            assignee_name=email.split("@")[0],
            assignee_email=email,
            description=bound_description,
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=3,
            built_app_slug=slug,
        )
        s.add(item)
        # Flush (not commit) to assign item.id, then add the execution so both
        # rows land in ONE commit — no window where a running task exists with
        # no execution row if the process dies mid-create.
        await s.flush()
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)
        task_id, exec_id = item.id, execution.id

    # Scaffold: copy the prebuilt base app when the template has one, else the
    # empty skeleton. Best-effort — the agent recreates the dir if this fails.
    try:
        if template_key and _has_template_app(template_key):
            _copy_template_app(template_key, slug, app_name=_humanize_slug(slug))
        else:
            _ensure_app_skeleton(slug, None)
    except Exception:
        pass

    prompt = build_prompt(
        description=bound_description,
        action_type="BUILD",
        priority="NICE_TO_HAVE",
        meeting_title=str(meeting_id),
        meeting_date="",
        supabase_url=None,
        has_db_uri=False,
        slug=slug,
        user_email=email,
    )
    _RUNNING[task_id] = {"task": None}
    bg = asyncio.create_task(_run_execution(task_id, exec_id, prompt))
    _RUNNING[task_id]["task"] = bg
    return str(task_id), slug


@router.get("/templates", response_model=list[TemplateBrief])
async def list_build_templates(user: CurrentUser = Depends(current_user)):
    """User-scoped template catalog for the Discord bot. No `rules` (same
    prompt-injection guard as the admin /api/templates). Excludes blank/custom."""
    from templates import TEMPLATES, _has_template_app
    return [
        TemplateBrief(
            key=t.key,
            label=t.label,
            emoji=t.emoji,
            description=t.description,
            has_app=_has_template_app(t.key),
            note=_template_note(t.key, t.storage),
        )
        for t in TEMPLATES
        if t.key not in _CATALOG_EXCLUDED_KEYS
    ]


@router.post("/build", response_model=BuildResponse, status_code=201)
async def start_build(body: BuildRequest, user: CurrentUser = Depends(current_user)):
    """Fire a one-shot frontend-only build (optionally from a template)."""
    seed = body.name or body.description
    task_id, slug = await _create_and_spawn_build(
        user.email, seed, body.description, template_key=body.template_key,
    )
    return BuildResponse(task_id=task_id, slug=slug, status="running")


async def _load_owned_build(email: str, task_id: uuid.UUID) -> TaskItem | None:
    """Return the task iff it exists AND is owned by `email`, else None.
    None -> the route answers 404 (not 403) so existence isn't leaked."""
    async with session() as s:
        item = (await s.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )).scalar_one_or_none()
    if item is None or item.assignee_email != email:
        return None
    return item


@router.get("/build/{task_id}", response_model=BuildStatusResponse)
async def get_build_status(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item = await _load_owned_build(user.email, task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    status = _public_build_status(item.status)
    slug = item.built_app_slug or ""
    # For `failed`, error carries the failure reason; for `needs_input` it
    # carries the agent's clarifying question (both live in TaskItem.result).
    return BuildStatusResponse(
        status=status,
        slug=slug,
        preview_url=_preview_url(slug) if status == "completed" and slug else None,
        error=(item.result or "")[:500] if status in ("failed", "needs_input") else None,
    )


@router.post("/{slug}/publish", response_model=PublishStatus)
async def publish_built_app(slug: str, user: CurrentUser = Depends(current_user)):
    """User-scoped publish for a Discord-built app. Ownership-enforced (the
    builder is auto-added as owner on completion, and _require_role also treats
    the original build assignee as an implicit owner), so a normal user — not an
    admin — can publish their own app. Reuses the shared _publish_slug core."""
    async with session() as s:
        return await _publish_slug(s, slug, user.email, is_admin=False)


@router.delete("/{slug}/publish", status_code=204)
async def unpublish_built_app(slug: str, user: CurrentUser = Depends(current_user)):
    """User-scoped unpublish for a Discord-built app (owner-only). Mirrors
    publish_built_app; reuses the shared _unpublish_slug core."""
    _validate_slug(slug)  # fast-fail before touching the DB pool
    async with session() as s:
        await _unpublish_slug(s, slug, user.email, is_admin=False)
    return None
