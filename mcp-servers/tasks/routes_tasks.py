"""Task CRUD + state transitions (manual mode)."""
import logging
import re as _re
from datetime import datetime
from pathlib import PurePath as _PurePath
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_, select, text

import uuid

from assignee_map import TEAM_EMAIL as TEAM_EMAIL_CONST, AssigneeMap
from auth import AdminUser, current_admin
from db import session
from models import ChatMessage, ProjectSupabase, TaskItem
from schemas import AnswerRequest, ChatRequest, ChatResponse, CompleteRequest, CreateTaskRequest, TaskOut
from templates import _has_template_app, build_rules_for, is_valid_key, requires_supabase

_FILENAME_SAFE_RE = _re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    """Strip path components and dangerous characters from an uploaded filename.

    Returns 'unnamed' (or 'unnamed.<ext>') when nothing usable remains.
    Never raises.
    """
    if not name:
        return "unnamed"
    base = _PurePath(name.replace("\\", "/")).name
    if not base or set(base) <= {"."}:
        return "unnamed"
    # Collapse runs of unsafe chars to a single underscore
    cleaned = _FILENAME_SAFE_RE.sub("_", base).strip("._")
    if not cleaned:
        # Salvage extension if any
        if "." in base:
            ext = base.rsplit(".", 1)[-1]
            ext = _FILENAME_SAFE_RE.sub("", ext)
            return ("unnamed." + ext) if ext else "unnamed"
        return "unnamed"
    return cleaned


_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff",      "image/jpeg"),
    (b"GIF87a",            "image/gif"),
    (b"GIF89a",            "image/gif"),
)


def _sniff_image_mime(head: bytes) -> str | None:
    """Return canonical MIME for the first 12 bytes of an image, or None.

    Recognises PNG, JPEG, GIF, WebP. Used as a server-side defence against
    a client that lies about Content-Type.
    """
    for sig, mime in _IMAGE_SIGNATURES:
        if head.startswith(sig):
            return mime
    # WebP: RIFF....WEBP
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None

ALLOWED_MIME: set[str] = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 5


SUPABASE_CONNECT_PROMPT = (
    "[ACTION:supabase_connect]\n"
    "This app needs a database to work properly. Connect your Supabase "
    "account so I can create the tables and APIs for you.\n\n"
    "Click \"Connect Supabase\" below — takes ~30 seconds. Or skip to "
    "build a frontend-only version (data only saved in your browser)."
)

logger = logging.getLogger("tasks.routes")

router = APIRouter(prefix="/api/tasks")

TEAM_EMAIL = "team@aiui.local"

STATUS_BY_TAB: dict[str, list[str]] = {
    "pending": ["pending", "awaiting_input", "planning", "awaiting_plan_review"],
    "progress": ["running", "claimed_manual"],
    "done": ["completed", "failed"],
}


async def _get_owned_task(s, task_id: UUID, email: str) -> TaskItem:
    res = await s.execute(select(TaskItem).where(TaskItem.id == task_id))
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if item.assignee_email != email and item.assignee_email != TEAM_EMAIL:
        raise HTTPException(status_code=403, detail="Not your task")
    return item


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: str = "pending",
    slug: str | None = None,
    has_built_app: bool = False,
    is_project: bool = False,
    limit: int = 50,
    user: AdminUser = Depends(current_admin),
):
    """List tasks with flexible filters.

    - `is_project=true`: returns every BUILD task plus every task with a
      built_app_slug (any status) that the current user owns or is a
      member of. Team-bucket tasks are NOT included — projects are
      strictly private to their owner + explicitly-invited members.
    - `has_built_app=true`: legacy filter for projects with a completed
      slug; now also excludes the team bucket.
    - Default (neither flag): the admin task-panel view — all tasks for
      this user plus the shared team bucket.
    """
    if status not in STATUS_BY_TAB and not is_project:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    from models import ProjectMember
    member_slugs_subq = (
        select(ProjectMember.slug)
        .where(ProjectMember.user_email == user.email)
        .scalar_subquery()
    )

    async with session() as s:
        if is_project:
            # Strict per-project access: owners and invited members only.
            # No team bucket. Only BUILD tasks show up on the app-builder
            # page — research, integrate, ask-user, and other non-app
            # tasks stay in the admin task panel instead.
            access_clause = or_(
                TaskItem.assignee_email == user.email,
                TaskItem.built_app_slug.in_(member_slugs_subq),
            )
            q = (
                select(TaskItem)
                .where(access_clause, TaskItem.action_type == "BUILD")
                .order_by(TaskItem.created_at.desc())
                .limit(limit)
            )
        elif has_built_app:
            # Legacy: built-only projects, still strict per-user.
            access_clause = or_(
                TaskItem.assignee_email == user.email,
                TaskItem.built_app_slug.in_(member_slugs_subq),
            )
            q = (
                select(TaskItem)
                .where(
                    access_clause,
                    TaskItem.built_app_slug.isnot(None),
                    TaskItem.status.in_(STATUS_BY_TAB[status]),
                )
                .order_by(TaskItem.created_at.desc())
                .limit(limit)
            )
        else:
            # Default: admin task panel — includes team bucket.
            access_clause = TaskItem.assignee_email.in_([user.email, TEAM_EMAIL])
            q = (
                select(TaskItem)
                .where(
                    access_clause,
                    TaskItem.status.in_(STATUS_BY_TAB[status]),
                )
                .order_by(TaskItem.created_at.desc())
                .limit(limit)
            )
        if slug:
            q = q.where(TaskItem.built_app_slug == slug)
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.get("/{task_id}/executions")
async def list_executions(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Return execution history for a task — used by the panel to show what AI did."""
    from models import TaskExecution
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        rows = (await s.execute(
            select(TaskExecution)
            .where(TaskExecution.task_id == item.id)
            .order_by(TaskExecution.started_at.desc())
        )).scalars().all()
        return [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "log": r.log or "",
                "error": r.error,
            }
            for r in rows
        ]


@router.get("/history", response_model=list[TaskOut])
async def history(
    limit: int = 50,
    offset: int = 0,
    user: AdminUser = Depends(current_admin),
):
    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, TEAM_EMAIL]),
                TaskItem.status.in_(["completed", "failed"]),
            )
            .order_by(TaskItem.completed_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Return a single task. Used by preview.html to watch build status.

    Read access extends beyond assignee — project members (people invited
    via the 👥 Members modal) can also view tasks for projects they're
    part of. Writes stay restricted to the assignee / team bucket.
    """
    from models import ProjectMember
    async with session() as s:
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.assignee_email in (user.email, TEAM_EMAIL):
            return item
        # Not the assignee — check project membership.
        if item.built_app_slug:
            member = (
                await s.execute(
                    select(ProjectMember).where(
                        ProjectMember.slug == item.built_app_slug,
                        ProjectMember.user_email == user.email,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if member is not None:
                return item
        raise HTTPException(status_code=403, detail="Not your task")


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: CreateTaskRequest, user: AdminUser = Depends(current_admin)):
    """Admin-created task from the panel. Not tied to a real meeting —
    uses a synthetic meeting_id so it shows up as normal in the panel."""
    amap = AssigneeMap.from_env()
    assignee_raw = (body.assignee or "self").strip()
    if assignee_raw.lower() == "self":
        assignee_name = user.email.split("@")[0]
        assignee_email = user.email
    elif assignee_raw.lower() == "team":
        assignee_name = "team"
        assignee_email = TEAM_EMAIL_CONST
    else:
        assignee_name = assignee_raw
        assignee_email = amap.resolve(assignee_raw)

    # Legacy `rules` / `template_rules` fields are accepted but ignored —
    # rules now come from the server-side template lookup (Phase D).
    if (body.rules and body.rules.strip()) or (body.template_rules and body.template_rules.strip()):
        logger.info(
            "Ignoring legacy `rules` field — using server-side template `%s` instead.",
            body.template_key or "<none>",
        )

    description = (body.description or "").strip()
    slug = (body.slug or "").strip()
    if body.action_type == "BUILD" and body.template_key:
        if not is_valid_key(body.template_key):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown template_key: {body.template_key!r}",
            )
        prefix = build_rules_for(body.template_key, body.storage)
        slug_instr = (
            f'PROJECT NAME: "{slug}". Create the app at apps/{slug}/ and use this exact slug throughout.\n\n'
            if slug
            else ""
        )
        description = f"{slug_instr}{prefix}\n\nUSER REQUEST:\n{description}"

    needs_supabase_gate_candidate = (
        body.action_type == "BUILD"
        and body.template_key
        and slug
        and requires_supabase(body.template_key, body.storage)
    )

    async with session() as s:
        needs_supabase_gate = False
        if needs_supabase_gate_candidate:
            existing = (await s.execute(
                select(ProjectSupabase).where(ProjectSupabase.slug == slug)
            )).scalar_one_or_none()
            already_linked = bool(
                existing
                and (existing.linked_project_ref or existing.supabase_url)
            )
            needs_supabase_gate = not already_linked

        # When gating on Supabase we set `built_app_slug` up-front so the chat
        # message and the resume endpoint can find this task by slug; the
        # regular build flow leaves it unset (Claude populates it after the
        # build runs).
        item = TaskItem(
            meeting_id=uuid.uuid4(),  # synthetic — no real meeting
            action_type=body.action_type,
            assignee_name=assignee_name,
            assignee_email=assignee_email,
            description=description[:20_000],
            priority=body.priority,
            status="awaiting_supabase" if needs_supabase_gate else "pending",
            max_attempts=body.max_attempts,
            built_app_slug=slug if needs_supabase_gate else None,
        )
        s.add(item)
        if needs_supabase_gate:
            s.add(ChatMessage(
                slug=slug,
                user_email=user.email,
                role="assistant",
                content=SUPABASE_CONNECT_PROMPT,
            ))
        await s.commit()
        await s.refresh(item)

    # Pre-create the canonical folder skeleton on disk so the Structure tab
    # has something to render before the agent runs, and so the agent always
    # finds the layout it's told to use. Only for BUILD with a slug. Idempotent.
    #
    # When a pre-built base app exists for the chosen template_key, copy it
    # into apps/<slug>/ instead of creating an empty skeleton — this is the
    # "customize, don't regenerate" path. The 13 templates without a base
    # app folder still go through the original empty-skeleton path.
    template_app_used = False
    if body.action_type == "BUILD" and slug:
        try:
            if body.template_key and _has_template_app(body.template_key):
                _copy_template_app(
                    body.template_key, slug, app_name=_humanize_slug(slug)
                )
                template_app_used = True
            else:
                _ensure_app_skeleton(slug, body.storage)
        except Exception:
            # Disk failures shouldn't block the task creation. The agent will
            # mkdir as needed during build.
            pass

    # INSTANT BUILD: when a working base app is already on disk AND the user's
    # description is generic ("build me an X"), skip the agent entirely. The
    # base app is already a polished, working app — running the agent just to
    # personalize copy is overkill when the user hasn't asked for anything
    # specific. They can always refine later via chat.
    if (
        template_app_used
        and not needs_supabase_gate
        and _is_generic_description(body.description or "")
    ):
        async with session() as s:
            row = (await s.execute(
                select(TaskItem).where(TaskItem.id == item.id)
            )).scalar_one()
            row.status = "completed"
            row.built_app_slug = slug
            row.completed_at = datetime.utcnow()
            row.result = (
                f"Used the {body.template_key} template as-is — no agent run needed. "
                "Refine the app via the Chat tab when you're ready."
            )
            await s.commit()
            await s.refresh(row)
            item = row

    return item


# Heuristic: is the user's description generic enough that the base template
# is already a complete answer? If yes, skip the agent run. Real descriptions
# (with brand, copy, features, specific colors, etc.) bypass this and trigger
# the personalize agent. The bar is intentionally low — we'd rather run the
# agent on a borderline case than skip it incorrectly.
def _is_generic_description(desc: str) -> bool:
    s = (desc or "").strip().lower()
    if not s:
        return True
    # Anything under 30 chars is too short to encode real intent.
    if len(s) <= 30:
        return True
    # Strip leading "build/make/create me a/an ..." — what's left tells us if
    # the user actually said something substantive.
    import re as _re
    stripped = _re.sub(
        r"^(please\s+)?(can you\s+)?(make|build|create|generate|give me|i want|i need|i'd like)\s+(me\s+)?(an?\s+)?",
        "",
        s,
    ).strip()
    # If after stripping the boilerplate, the remainder is short and nondescript
    # (e.g. "crud app", "invoice app", "todo list"), still generic.
    if len(stripped) <= 14:
        return True
    return False


def _ensure_app_skeleton(slug: str, storage: str | None) -> None:
    """Create the empty folder layout matching the BUILD prompt's spec."""
    import os
    workspace = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
    base = os.path.join(workspace, "apps", slug)
    subdirs = ["styles", "src", "src/components", "src/lib", "public"]
    for sub in [""] + subdirs:
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    # Drop a placeholder README so the folder isn't empty when the build
    # hasn't started yet.
    readme = os.path.join(base, "README.md")
    if not os.path.exists(readme):
        storage_label = "Supabase backend" if storage == "supabase" else "frontend-only (no backend)"
        with open(readme, "w", encoding="utf-8") as f:
            f.write(f"# {slug}\n\nApp scaffolded by AIUI App Builder. Storage: {storage_label}.\n")


def _humanize_slug(slug: str) -> str:
    """Turn a kebab-case slug into a Title Case display name.

    e.g. "my-todo-list" -> "My Todo List". Empty input returns "".
    """
    if not slug:
        return ""
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    return " ".join(p[:1].upper() + p[1:] for p in parts)


# Files we never want to copy out of a template_apps/<key>/ source tree.
_TEMPLATE_COPY_IGNORE: frozenset[str] = frozenset({".DS_Store", "Thumbs.db"})

# Extensions that get placeholder substitution. Anything else is treated as
# a binary blob and copied verbatim with shutil.copy2.
_TEMPLATE_TEXT_EXTS: frozenset[str] = frozenset({".html", ".js", ".css", ".md", ".sql"})


def _copy_template_app(key: str, slug: str, app_name: str) -> None:
    """Copy template_apps/<key>/ into apps/<slug>/, substituting placeholders.

    On every text file (.html, .js, .css, .md, .sql), replaces:
      • <%= APP_NAME %> with `app_name` (falls back to humanized slug if blank)
      • <%= APP_SLUG %> with `slug`

    Binary files are copied verbatim via shutil.copy2. Files matching
    _TEMPLATE_COPY_IGNORE (.DS_Store, Thumbs.db) are skipped. Idempotent —
    overwrites destination files if they already exist.
    """
    import os
    import shutil

    here = os.path.dirname(os.path.abspath(__file__))
    src_root = os.path.join(here, "template_apps", key)
    workspace = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
    dst_root = os.path.join(workspace, "apps", slug)

    name = app_name or _humanize_slug(slug) or slug

    for src_dir, _dirs, files in os.walk(src_root):
        rel_dir = os.path.relpath(src_dir, src_root)
        dst_dir = dst_root if rel_dir == "." else os.path.join(dst_root, rel_dir)
        os.makedirs(dst_dir, exist_ok=True)
        for fname in files:
            if fname in _TEMPLATE_COPY_IGNORE:
                continue
            src_file = os.path.join(src_dir, fname)
            dst_file = os.path.join(dst_dir, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in _TEMPLATE_TEXT_EXTS:
                try:
                    text_content = open(src_file, "r", encoding="utf-8").read()
                except UnicodeDecodeError:
                    # Mislabelled binary — fall back to verbatim copy.
                    shutil.copy2(src_file, dst_file)
                    continue
                text_content = text_content.replace("<%= APP_NAME %>", name)
                text_content = text_content.replace("<%= APP_SLUG %>", slug)
                with open(dst_file, "w", encoding="utf-8", newline="") as f:
                    f.write(text_content)
            else:
                shutil.copy2(src_file, dst_file)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id, user: AdminUser = Depends(current_admin)):
    """Delete a task — only allowed from 'pending' status and for tasks
    owned by the current admin (or in the shared team bucket)."""
    from uuid import UUID
    try:
        tid = UUID(str(task_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")
    async with session() as s:
        item = await _get_owned_task(s, tid, user.email)
        if item.status != "pending":
            raise HTTPException(status_code=409, detail=f"Can only delete pending tasks (this is {item.status})")
        await s.delete(item)
        await s.commit()
    return None


@router.post("/{task_id}/manual", response_model=TaskOut)
async def claim_manual(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Claim a task for manual handling.

    Allowed from 'pending' (fresh task) or 'failed' (admin taking over after
    an AI execution failure). 'failed -> claimed_manual' preserves the
    execution log for audit and lets the admin finish the work.
    """
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status not in ("pending", "failed"):
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")
        item.status = "claimed_manual"
        item.mode = "manual"
        item.completed_at = None  # reset in case we're reviving a failed task
        await s.commit()
        await s.refresh(item)
    return item


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete(
    task_id: UUID,
    body: CompleteRequest,
    user: AdminUser = Depends(current_admin),
):
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status not in ("claimed_manual", "awaiting_input"):
            raise HTTPException(status_code=409, detail=f"Cannot complete from {item.status}")
        item.status = "completed"
        item.result = body.result
        item.completed_at = datetime.utcnow()
        await s.commit()
        await s.refresh(item)
    return item


@router.post("/{task_id}/answer", response_model=TaskOut)
async def answer(
    task_id: UUID,
    body: AnswerRequest,
    user: AdminUser = Depends(current_admin),
):
    """For ASK_USER tasks, completes immediately. For awaiting_input AI tasks, resumes execution."""
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)

        if item.action_type == "ASK_USER" and item.status == "pending":
            item.status = "completed"
            item.mode = "manual"
            item.result = body.answer
            item.completed_at = datetime.utcnow()
            await s.commit()
            await s.refresh(item)
            return item

        if item.status == "awaiting_input":
            import asyncio
            from claude_executor import build_prompt, build_tdd_execute_prompt, build_enhance_prompt
            from models import TaskExecution
            from routes_execution import _run_execution, _RUNNING, _lookup_supabase_config

            history = list(item.conversation_history or [])
            history.append({"role": "admin", "content": body.answer})
            item.conversation_history = history
            item.status = "running"
            new_exec = TaskExecution(task_id=item.id, status="running", log="")
            s.add(new_exec)
            await s.commit()
            await s.refresh(item)
            await s.refresh(new_exec)
            supabase_url, has_db_uri = await _lookup_supabase_config(s, item.built_app_slug)
            item_slug = item.built_app_slug or ""
            item_email = item.assignee_email or ""

            # Enhance tasks need `build_enhance_prompt` so Claude stays in the
            # app's existing stack/dir and follows the enhance rules. Using the
            # generic `build_prompt` here would make Claude start a NEW app
            # instead of modifying `apps/<slug>/`.
            is_enhance = (
                item.action_type == "BUILD"
                and item.built_app_slug
                and (item.description or "").startswith("Enhance apps/")
            )

            if is_enhance:
                convo_block_lines = []
                for entry in history:
                    role = entry.get("role", "")
                    content = entry.get("content", "")
                    if role == "ai":
                        convo_block_lines.append(f"AI asked: {content}")
                    elif role == "admin":
                        convo_block_lines.append(f"ADMIN answered: {content}")
                convo_block = "\n".join(convo_block_lines)
                # Strip the "Enhance apps/<slug>/: " prefix to get the raw ask,
                # then append the clarifying round so Claude has full context.
                raw_ask = (item.description or "").split(":", 1)[-1].strip()
                user_request = (
                    raw_ask
                    + "\n\nCONVERSATION WITH ADMIN:\n"
                    + convo_block
                )
                prompt = build_enhance_prompt(
                    slug=item.built_app_slug,
                    user_request=user_request,
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                    supabase_url=supabase_url,
                    has_db_uri=has_db_uri,
                    user_email=item_email,
                )
            elif item.max_attempts > 1 and item.plan:
                prompt = build_tdd_execute_prompt(
                    description=item.description,
                    action_type=item.action_type,
                    priority=item.priority,
                    meeting_title=str(item.meeting_id),
                    meeting_date="",
                    plan=item.plan,
                    conversation_history=history,
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                    error_context="",
                    supabase_url=supabase_url,
                    has_db_uri=has_db_uri,
                    slug=item_slug,
                    user_email=item_email,
                )
            else:
                prompt = (
                    build_prompt(
                        description=item.description,
                        action_type=item.action_type,
                        priority=item.priority,
                        meeting_title=str(item.meeting_id),
                        meeting_date="",
                        supabase_url=supabase_url,
                        has_db_uri=has_db_uri,
                        slug=item_slug,
                        user_email=item_email,
                    )
                    + f"\n\nADMIN PROVIDED THIS ANSWER: {body.answer}"
                )

            _RUNNING[item.id] = {"task": None, "proc": None}
            bg = asyncio.create_task(_run_execution(item.id, new_exec.id, prompt))
            _RUNNING[item.id]["task"] = bg
            return item

        raise HTTPException(status_code=409, detail="Answer not applicable in current state")


@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(
    source_task_id: UUID = Form(...),
    prompt: str = Form(..., min_length=1, max_length=2000),
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
):
    """Create a new BUILD task that modifies an existing app, optionally with image attachments.

    Skips CLARIFY/PLAN (plan_status='approved' set up front) and goes straight
    to TDD EXECUTE with ENHANCE_PROMPT_TEMPLATE so the user gets a fast
    iteration loop — type change -> AI edits existing files -> preview reloads.

    Image attachments (PNG/JPEG/WebP/GIF, ≤5MB each, ≤5 files) are saved to
    apps/<slug>/.attachments/<task_id>/<safe_name> and surfaced to the agent
    via the prompt (Task 8 wires the prompt-side reference list).
    """
    import asyncio
    import inspect
    from claude_executor import build_enhance_prompt
    from models import TaskExecution
    from routes_execution import _run_execution, _RUNNING, _lookup_supabase_config

    # Reject too many files BEFORE touching the DB
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Too many attachments (max {MAX_FILES})")

    # Read+validate each file fully into memory (≤ 5 MB × 5 = 25 MB worst case)
    validated: list[tuple[str, bytes]] = []  # [(safe_name, body)]
    for f in files:
        body = await f.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            raise HTTPException(400, f"{f.filename}: file too large (max 5 MB)")
        if f.content_type not in ALLOWED_MIME:
            raise HTTPException(
                400,
                f"Unsupported file type: {f.content_type}. Images only (PNG, JPEG, WebP, GIF).",
            )
        if _sniff_image_mime(body[:12]) is None:
            raise HTTPException(
                400,
                f"{f.filename}: file contents do not match a supported image format.",
            )
        # Length-cap the safe filename (helper does NOT cap length — caller's responsibility).
        safe = _safe_filename(f.filename or "image")[:200]
        validated.append((safe, body))

    async with session() as s:
        # 1. Validate source
        source = (await s.execute(
            select(TaskItem).where(TaskItem.id == source_task_id)
        )).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="Source task not found")
        if source.action_type != "BUILD":
            raise HTTPException(status_code=400, detail="Can only enhance BUILD tasks")
        if not source.built_app_slug:
            raise HTTPException(
                status_code=400,
                detail="Source task has no built_app_slug — nothing to enhance",
            )

        # Editors and owners on the project may enhance shared apps.
        from routes_projects import _require_role
        await _require_role(s, source.built_app_slug, user.email, "editor",
                            is_admin=user.is_admin)

        # Serialize the check+insert per slug via a transaction-scoped
        # advisory lock so two parallel /enhance calls cannot both see
        # "no in-flight" and proceed. The lock auto-releases on commit.
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"build:{source.built_app_slug}"},
        )

        # 2. Reject concurrent enhancements on same app
        in_flight = (await s.execute(
            select(TaskItem).where(
                TaskItem.built_app_slug == source.built_app_slug,
                TaskItem.status.in_(["running", "planning", "awaiting_input"]),
            )
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(
                status_code=409,
                detail=f"Another enhancement is already in progress for apps/{source.built_app_slug}/",
            )

        # 3. Create new enhancement task
        new_task = TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name=user.email.split("@")[0],
            assignee_email=user.email,
            description=f"Enhance apps/{source.built_app_slug}/: {prompt.strip()[:400]}",
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=max(source.max_attempts or 1, 1),
            built_app_slug=source.built_app_slug,
            plan_status="approved",
        )
        s.add(new_task)
        await s.commit()
        await s.refresh(new_task)

        execution = TaskExecution(task_id=new_task.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(execution)
        supabase_url, has_db_uri = await _lookup_supabase_config(s, source.built_app_slug)

    # Persist attachments to disk now that we have new_task.id
    attachment_rel_paths: list[str] = []
    if validated:
        from pathlib import Path
        import os
        apps_dir = Path(os.environ.get("APPS_DIR", "apps"))
        att_dir = apps_dir / source.built_app_slug / ".attachments" / str(new_task.id)
        att_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        for original_safe, body in validated:
            name = original_safe
            i = 1
            while name in used_names or (att_dir / name).exists():
                stem, _, ext = original_safe.rpartition(".")
                stem = stem or original_safe
                name = (
                    f"{stem}_{i}.{ext}" if ext and ext != original_safe else f"{original_safe}_{i}"
                )
                i += 1
            (att_dir / name).write_bytes(body)
            used_names.add(name)
            attachment_rel_paths.append(f".attachments/{new_task.id}/{name}")

    # 4. Fire background execution with ENHANCE prompt.
    # Task 8 adds an `attachments` kwarg to build_enhance_prompt; until then we
    # pass it only when the function actually accepts it. This `inspect` check
    # is removable once Task 8 lands.
    _enhance_kwargs = dict(
        slug=source.built_app_slug,
        user_request=prompt.strip(),
        attempt_count=0,
        max_attempts=new_task.max_attempts,
        supabase_url=supabase_url,
        has_db_uri=has_db_uri,
        user_email=user.email,
    )
    if "attachments" in inspect.signature(build_enhance_prompt).parameters:
        _enhance_kwargs["attachments"] = attachment_rel_paths or None
    prompt_text = build_enhance_prompt(**_enhance_kwargs)
    _RUNNING[new_task.id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_run_execution(new_task.id, execution.id, prompt_text))
    _RUNNING[new_task.id]["task"] = bg

    return new_task


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: UUID,
    user: AdminUser = Depends(current_admin),
):
    """Cancel a task stuck in a non-terminal state.

    Unblocks the admin when an enhancement is stuck in `awaiting_input`
    (AI asked a clarifying question nobody answered) or `running` (crashed
    background worker) and is preventing new enhancements on the same slug
    from being queued (see `/enhance` 409 path).

    The DB row is marked `failed` with a 'Cancelled by user' result. If a
    background task is still tracked in `_RUNNING`, its asyncio.Task and
    subprocess are also cancelled so they stop consuming resources.
    """
    TERMINAL = {"completed", "failed"}
    async with session() as s:
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor",
                                is_admin=user.is_admin)
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.status in TERMINAL:
            raise HTTPException(
                status_code=409,
                detail=f"Task already {item.status}; nothing to cancel",
            )
        item.status = "failed"
        item.result = "Cancelled by user"
        item.updated_at = datetime.utcnow()
        await s.commit()
        await s.refresh(item)

    # Best-effort: cancel any in-flight asyncio task + child process
    from routes_execution import _RUNNING
    entry = _RUNNING.pop(task_id, None)
    if entry:
        bg_task = entry.get("task")
        if bg_task and not bg_task.done():
            bg_task.cancel()
        proc = entry.get("proc")
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    return item


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: AdminUser = Depends(current_admin),
):
    """Lightweight chat about an existing app.

    Calls the Anthropic Messages API directly — no build pipeline, no git
    commits, no file edits. The Enhance panel's Chat mode uses this so admins
    can ask questions, brainstorm changes, or just discuss the app without
    triggering an expensive build run that might fail on a greeting like "hi".

    Uses Haiku for latency + cost. Retrieves the existing app's file list so
    Claude can give grounded answers about what's in the app.
    """
    import os
    import httpx
    from uuid import UUID as _UUID

    try:
        source_id = _UUID(body.source_task_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid source_task_id")

    async with session() as s:
        source = await _get_owned_task(s, source_id, user.email)
    if not source.built_app_slug:
        raise HTTPException(status_code=400, detail="Source task has no built app to chat about")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Chat unavailable — ANTHROPIC_API_KEY not configured")

    slug = source.built_app_slug
    app_dir = os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps", slug)

    # Look up Supabase state for this project — whether it's linked decides
    # how the agent answers DB/backend questions.
    supabase_linked = False
    supabase_summary = ""
    try:
        from sqlalchemy import select as _sel
        from models import ProjectSupabase as _PS
        async with session() as s2:
            ps = (await s2.execute(
                _sel(_PS).where(_PS.slug == slug)
            )).scalar_one_or_none()
        if ps and (ps.linked_project_ref or ps.supabase_url):
            supabase_linked = True
            ref = ps.linked_project_ref or "(manual URL)"
            url = ps.supabase_url or "(via Management API)"
            supabase_summary = f"linked Supabase project: {ref}; URL: {url}"
        else:
            supabase_summary = "not connected"
    except Exception:
        supabase_summary = "(status unknown)"

    # Gather a compact file listing for context (file names only, no content)
    file_listing = ""
    try:
        entries = []
        for root, dirs, files in os.walk(app_dir):
            # Skip heavy/generated dirs
            dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", ".pytest_cache", "data", ".git")]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), app_dir)
                entries.append(rel)
                if len(entries) >= 60:
                    break
            if len(entries) >= 60:
                break
        file_listing = "\n".join(f"  - {e}" for e in sorted(entries))
    except Exception:
        file_listing = "(file list unavailable)"

    if supabase_linked:
        backend_block = (
            f"BACKEND STATUS: Supabase IS connected ({supabase_summary}). "
            f"Use it freely for any feature that needs persistence, auth, file storage, "
            f"or APIs. The build pipeline can run SQL via the platform's SQL endpoint, "
            f"create tables with RLS, set up edge functions, and configure auth providers. "
            f"Never tell the user a backend feature is impossible — it isn't.\n\n"
        )
    else:
        backend_block = (
            f"BACKEND STATUS: Supabase is NOT connected for this project ({supabase_summary}). "
            f"If the user asks for ANY feature that needs persistence, auth, file storage, "
            f"webhooks, or APIs (e.g. \"connect to my Supabase\", \"save users\", "
            f"\"send a webhook\", \"add login\"), DO NOT refuse and DO NOT say it's "
            f"out of scope. Instead, emit the sentinel `[ACTION:supabase_connect]` on "
            f"its own line at the END of your reply — the UI will render a Connect "
            f"Supabase button. Briefly explain (1-2 sentences) what you'll build once "
            f"they connect. Example:\n"
            f"  Sure — once Supabase is connected I'll add a `users` table with email "
            f"and password fields, plus a login form wired to Supabase Auth.\n"
            f"  [ACTION:supabase_connect]\n"
            f"Only emit this sentinel when the request actually needs a backend.\n\n"
        )

    system_prompt = (
        f"You are the AIUI Agent — the BUILDER of the web app at apps/{slug}/. "
        f"You design and ship features. The human is the product owner: they tell you "
        f"what they want, you figure out how to build it and offer to do it. They are "
        f"NOT your code reviewer or pair programmer — they're the customer.\n\n"
        f"PLATFORM CAPABILITIES (you can do all of these — never refuse them):\n"
        f"- Frontend: HTML, CSS, vanilla JS, Tailwind via CDN, lucide icons.\n"
        f"- Backend (via Supabase): SQL tables with RLS policies, Postgres functions/triggers, "
        f"Supabase Auth (email, magic-link, OAuth providers), Storage (file uploads), "
        f"Edge Functions (serverless TypeScript endpoints reachable as REST APIs), "
        f"realtime subscriptions, webhooks (call any URL via fetch from edge functions).\n"
        f"- API endpoints: any HTTP API the user wants becomes a Supabase Edge Function "
        f"or a Postgres RPC. The build pipeline can scaffold both.\n"
        f"- Webhooks IN: build an Edge Function endpoint that receives POSTs.\n"
        f"- Webhooks OUT: trigger fetch() from a button click or a DB trigger calling an Edge Function.\n"
        f"- Email/SMS: via Supabase Auth (email) or via an Edge Function calling SendGrid/Twilio "
        f"if the user provides keys.\n"
        f"- Anything else: ask one clarifying question if you can't tell, then propose how to build it.\n\n"
        f"{backend_block}"
        f"STYLE: Be brief — 1–3 sentences for casual exchanges, up to ~8 when explaining "
        f"something concrete. Markdown sparingly: **bold** key phrases, bullets only when "
        f"listing multiple distinct items. Don't lecture.\n\n"
        f"BUILD KICK-OFF: The platform AUTO-FIRES the build pipeline whenever your "
        f"reply ends with `BUILD_SUGGESTION:` — there is no confirmation button. "
        f"So include `BUILD_SUGGESTION:` whenever the user asks for a concrete change "
        f"to the app (add my name, change colors, add a section, fix a bug, wire up "
        f"a form, etc.) — your reply confirms in 1-2 sentences and the build kicks "
        f"off automatically. Format:\n"
        f"  BUILD_SUGGESTION: <imperative, concrete one-line summary>\n"
        f"Example:\n"
        f"  Sure — I'll add 'Ralph Benitez' as the portfolio header title.\n"
        f"  BUILD_SUGGESTION: Replace the placeholder portfolio header text with 'Ralph Benitez' as the H1.\n"
        f"\n"
        f"DO NOT emit BUILD_SUGGESTION for: greetings, pure questions about how the "
        f"app works (no change requested), brainstorming hypotheticals (\"what could "
        f"I do?\"), or asks for clarification before you can build. In those cases, "
        f"answer in plain text and ask follow-up questions.\n"
        f"DO emit BUILD_SUGGESTION when the user clearly wants the change made now "
        f"(\"add X\", \"change Y to Z\", \"yes do it\", \"build it\", or any specific "
        f"feature description). The user expects you to just do it.\n\n"
        f"NEVER refuse with phrases like \"out of scope\", \"beyond what we can do\", "
        f"\"this is a frontend-only app\". The platform handles backend; your job is to "
        f"figure out the design and ship it.\n\n"
        f"APP FILES:\n{file_listing}"
    )

    messages = [m.model_dump() for m in body.history] + [
        {"role": "user", "content": body.message}
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 700,
                    "system": system_prompt,
                    "messages": messages,
                },
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Chat upstream error: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Claude API returned {r.status_code}: {r.text[:200]}")

    data = r.json()
    parts = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
    reply_text = "\n".join(p for p in parts if p).strip()
    if not reply_text:
        reply_text = "(no reply generated)"
    return ChatResponse(reply=reply_text)
