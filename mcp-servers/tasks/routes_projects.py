"""Per-project membership management + live presence + version history.

Membership: each built app (identified by its slug) has a `project_members`
ACL. The task creator is auto-added as `owner` on completion (and via
backfill). Admins can invite/remove members.

Presence: in-memory heartbeat map. Each user of the preview UI posts a
heartbeat every ~10s; after 20s of silence they're considered gone. Used
to (a) show who else is looking at a project, (b) prevent two users from
kicking off a Build on the same app at the same time.

Versions: backed by git history. `git log -- apps/<slug>/` is the source
of truth. Rollback restores files from a chosen SHA with a new commit on
top (so the "bad" version stays in history, marked as superseded).
"""
import asyncio
import os
import re
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from auth import AdminUser, current_admin
from db import session
from models import ChatMessage, ProjectMember, ProjectSupabase, PublishedApp, TaskItem
from schemas import InviteRequest, MemberOut, RoleUpdate

# Domain that wildcard-published apps live under. Override via env if needed.
PUBLIC_DOMAIN = os.environ.get("AIUI_PUBLIC_DOMAIN", "ai-ui.coolestdomain.win")
# Public IP that custom domains must point to. Override via env on the host.
SERVER_IP = os.environ.get("AIUI_SERVER_IP", "46.224.193.25")
# Reserved hostname suffix users cannot claim as a custom domain.
RESERVED_DOMAIN_SUFFIXES = (".coolestdomain.win",)
# RFC 1123-ish hostname check: each label 1-63 chars, ASCII alnum + hyphen,
# no leading/trailing hyphen, total length under 253.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)

router = APIRouter(prefix="/api/projects")

TEAM_EMAIL = "team@aiui.local"

# In-memory presence: slug -> { email -> {"last_seen": ts, "is_building": bool} }
_PRESENCE: dict[str, dict[str, dict]] = defaultdict(dict)
_PRESENCE_TTL_SECONDS = 20  # entries older than this are pruned


def _prune(slug: str) -> None:
    """Drop entries older than TTL for a given slug."""
    now = time.time()
    bucket = _PRESENCE.get(slug, {})
    stale = [e for e, v in bucket.items() if now - v["last_seen"] > _PRESENCE_TTL_SECONDS]
    for e in stale:
        bucket.pop(e, None)


async def _user_can_see_project(s, slug: str, email: str) -> bool:
    """Return True if the user is a member, the assignee, or it's in the
    team bucket. Used as the read-access gate for project endpoints."""
    # Member row exists? (.limit(1) because user_email could match the
    # user AND team@aiui.local, and we just need any match.)
    row = (
        await s.execute(
            select(ProjectMember).where(
                and_(
                    ProjectMember.slug == slug,
                    ProjectMember.user_email.in_([email, TEAM_EMAIL]),
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row is not None:
        return True
    # Or the task was created by them?
    task = (
        await s.execute(
            select(TaskItem).where(
                and_(
                    TaskItem.built_app_slug == slug,
                    TaskItem.assignee_email.in_([email, TEAM_EMAIL]),
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    return task is not None


ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


async def _require_role(s, slug: str, email: str, min_role: str,
                        *, is_admin: bool = False) -> str:
    """Raise 403 unless the user has at least `min_role` on the project.

    When `is_admin=True`, the user bypasses the role check entirely (returns
    "owner"). Callers should pass `user.is_admin` to opt in. The helper
    looks up the user's role in `tasks.project_members`; if there's no
    membership row but the user is the original assignee on a TaskItem
    with that slug, they're treated as implicit owner.

    Returns the user's effective role (for callers that want to log it).
    """
    if is_admin:
        return "owner"
    # Defense-in-depth: even though current_admin lowercases, callers may
    # pass an unnormalized value from elsewhere (e.g. path params).
    email = (email or "").strip().lower()
    member = (
        await s.execute(
            select(ProjectMember).where(
                and_(
                    ProjectMember.slug == slug,
                    ProjectMember.user_email == email,
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    if member is None:
        # Fall back to "creator implicitly owns it" if there's a TaskItem.
        task = (
            await s.execute(
                select(TaskItem).where(
                    and_(
                        TaskItem.built_app_slug == slug,
                        TaskItem.assignee_email == email,
                    )
                ).limit(1)
            )
        ).scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=403, detail="Not a member of this project")
        role = "owner"
    else:
        role = member.role

    if ROLE_RANK.get(role, -1) < ROLE_RANK[min_role]:
        raise HTTPException(
            status_code=403,
            detail=f"This action needs role '{min_role}' — you have '{role}'.",
        )
    return role


@router.get("/{slug}/members", response_model=list[MemberOut])
async def list_members(slug: str, user: AdminUser = Depends(current_admin)):
    """List all members of a project. Anyone who can see the project can
    list its members; non-members get 403."""
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        rows = (
            await s.execute(
                select(ProjectMember)
                .where(ProjectMember.slug == slug)
                .order_by(ProjectMember.added_at)
            )
        ).scalars().all()
    return rows


@router.post("/{slug}/members", response_model=MemberOut, status_code=201)
async def invite_member(
    slug: str,
    body: InviteRequest,
    user: AdminUser = Depends(current_admin),
):
    """Invite a user to the project. Admin-only for now.

    The invited email is stored as-given — downstream auth matches against
    the authenticated X-User-Email header, so it must match the email the
    invitee logs in with.
    """
    invited = body.user_email.strip().lower()
    if not invited or "@" not in invited:
        raise HTTPException(status_code=400, detail="Invalid email")

    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        # Project must exist (some task must have built it).
        exists = (
            await s.execute(
                select(TaskItem.id).where(TaskItem.built_app_slug == slug).limit(1)
            )
        ).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=404, detail="Project not found")

        # Upsert member.
        existing = (
            await s.execute(
                select(ProjectMember).where(
                    and_(ProjectMember.slug == slug, ProjectMember.user_email == invited)
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.role = body.role
            member = existing
        else:
            member = ProjectMember(
                slug=slug,
                user_email=invited,
                role=body.role,
                added_by=user.email,
            )
            s.add(member)
        await s.commit()
        await s.refresh(member)
    return member


@router.delete("/{slug}/members/{email}", status_code=204)
async def remove_member(
    slug: str,
    email: str,
    user: AdminUser = Depends(current_admin),
):
    """Remove a user from a project. Admin-only. Refuses to remove the
    last owner (leaving the project orphaned)."""
    target = email.strip().lower()
    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        row = (
            await s.execute(
                select(ProjectMember).where(
                    and_(ProjectMember.slug == slug, ProjectMember.user_email == target)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Member not found")
        if row.role == "owner":
            # Count remaining owners
            owner_count = len(
                (
                    await s.execute(
                        select(ProjectMember).where(
                            and_(ProjectMember.slug == slug, ProjectMember.role == "owner")
                        )
                    )
                ).scalars().all()
            )
            if owner_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot remove the last owner of a project",
                )
        await s.delete(row)
        await s.commit()
    return None


@router.patch("/{slug}/members/{email}", response_model=MemberOut)
async def update_member_role(
    slug: str,
    email: str,
    body: RoleUpdate,
    user: AdminUser = Depends(current_admin),
):
    """Change a member's role. Owner-only. Refuses to demote the last owner."""
    target = email.strip().lower()
    if body.role not in ("owner", "editor", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        row = (
            await s.execute(
                select(ProjectMember).where(
                    and_(ProjectMember.slug == slug, ProjectMember.user_email == target)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Member not found")
        if row.role == "owner" and body.role != "owner":
            owner_count = len(
                (
                    await s.execute(
                        select(ProjectMember).where(
                            and_(ProjectMember.slug == slug, ProjectMember.role == "owner")
                        )
                    )
                ).scalars().all()
            )
            if owner_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot demote the last owner — invite another owner first or transfer ownership",
                )
        row.role = body.role
        await s.commit()
        await s.refresh(row)
    return row


@router.post("/{slug}/leave", status_code=204)
async def leave_project(slug: str, user: AdminUser = Depends(current_admin)):
    """Self-remove from a project. Refused if you're the last owner."""
    _validate_slug(slug)
    async with session() as s:
        row = (
            await s.execute(
                select(ProjectMember).where(
                    and_(
                        ProjectMember.slug == slug,
                        ProjectMember.user_email == user.email,
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Not a member of this project")
        if row.role == "owner":
            owner_count = len((
                await s.execute(
                    select(ProjectMember).where(
                        and_(ProjectMember.slug == slug, ProjectMember.role == "owner")
                    )
                )
            ).scalars().all())
            if owner_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="You're the last owner — promote someone else first or unpublish the project.",
                )
        await s.delete(row)
        await s.commit()
    return None


# ---------------------------------------------------------------------------
# Presence (live "who is here / who is building")
# ---------------------------------------------------------------------------

class PresenceHeartbeat(BaseModel):
    is_building: bool = False


class PresenceEntry(BaseModel):
    user_email: str
    is_building: bool
    seconds_since_seen: float


@router.post("/{slug}/presence")
async def heartbeat(
    slug: str,
    body: PresenceHeartbeat,
    user: AdminUser = Depends(current_admin),
):
    """Update (or create) this user's presence entry for the given slug.
    Client should call this every ~10s while viewing the preview page."""
    _PRESENCE[slug][user.email] = {
        "last_seen": time.time(),
        "is_building": bool(body.is_building),
    }
    return {"ok": True, "me": user.email}


@router.get("/{slug}/presence", response_model=list[PresenceEntry])
async def list_presence(slug: str, user: AdminUser = Depends(current_admin)):
    """Return everyone currently viewing the project, with their status."""
    _prune(slug)
    now = time.time()
    return [
        PresenceEntry(
            user_email=email,
            is_building=v["is_building"],
            seconds_since_seen=round(now - v["last_seen"], 1),
        )
        for email, v in _PRESENCE[slug].items()
    ]


@router.delete("/{slug}/presence", status_code=204)
async def clear_presence(slug: str, user: AdminUser = Depends(current_admin)):
    """Explicit sign-off (sent on page unload when possible)."""
    _PRESENCE[slug].pop(user.email, None)
    return None


# ---------------------------------------------------------------------------
# Version history (git log + rollback)
# ---------------------------------------------------------------------------

REPO_ROOT = "/workspace/ai_ui"  # bind-mounted git working tree inside container
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")


class VersionEntry(BaseModel):
    sha: str
    short_sha: str
    date: str
    author: str
    message: str
    is_current: bool = False
    status: str = "ok"  # "ok" | "error" | "rollback"
    task_id: str | None = None
    actor_email: str | None = None  # who created the task that led to this commit


class RollbackRequest(BaseModel):
    sha: str = Field(min_length=7, max_length=40)


async def _run_git(*args: str, cwd: str = REPO_ROOT) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout_stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


def _validate_slug(slug: str) -> None:
    """Guard path-injection: only allow safe slug characters."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")


@router.get("/{slug}/versions", response_model=list[VersionEntry])
async def list_versions(slug: str, user: AdminUser = Depends(current_admin)):
    """List all commits that touched apps/<slug>/.

    Each commit is cross-referenced with the tasks table so we can mark:
    - "error" — a task whose result mentions the commit SHA failed
    - "rollback" — commit message starts with "Rollback"
    - "ok" — normal build/enhance commit
    """
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")

    # Get git log for apps/<slug>/ — up to 100 most recent.
    rc, out = await _run_git(
        "log",
        "--max-count=100",
        "--format=%H%x1f%an%x1f%ct%x1f%s",
        "--",
        f"apps/{slug}/",
    )
    if rc != 0:
        # No commits yet? Empty list is fine.
        if "does not have any commits" in out or "unknown revision" in out:
            return []
        raise HTTPException(status_code=500, detail=f"git log failed: {out[:300]}")

    # Also ask for the *current* HEAD sha so we can mark is_current.
    _, head_out = await _run_git("rev-parse", "HEAD")
    head_sha = head_out.strip()

    # Build a map of commit SHA prefixes → task ids whose result mentions them.
    # We look up all tasks with this slug to keep the query small.
    async with session() as s:
        tasks_rows = (
            await s.execute(
                select(TaskItem).where(TaskItem.built_app_slug == slug)
            )
        ).scalars().all()
    # Map short-sha → (task_id, status, actor_email) for any commit
    # referenced in a task's result field.
    by_sha: dict[str, tuple[str, str, str | None]] = {}
    for t in tasks_rows:
        if not t.result:
            continue
        for m in re.findall(r"\b([0-9a-f]{7,40})\b", t.result):
            short = m[:7]
            by_sha.setdefault(
                short,
                (str(t.id), t.status or "completed", t.assignee_email),
            )

    versions: list[VersionEntry] = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, author, ct, msg = parts
        short = sha[:7]
        tstatus = "ok"
        task_id = None
        actor_email = None
        if msg.lower().startswith("rollback"):
            tstatus = "rollback"
        corr = by_sha.get(short)
        if corr:
            task_id = corr[0]
            actor_email = corr[2]
            if corr[1] == "failed":
                tstatus = "error"
        versions.append(VersionEntry(
            sha=sha,
            short_sha=short,
            date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ct))),
            author=author,
            message=msg,
            is_current=(sha == head_sha),
            status=tstatus,
            task_id=task_id,
            actor_email=actor_email,
        ))
    return versions


@router.post("/{slug}/rollback")
async def rollback_project(
    slug: str,
    body: RollbackRequest,
    user: AdminUser = Depends(current_admin),
):
    """Restore apps/<slug>/ to the content at a specific commit.

    Creates a new commit on top of HEAD so history is preserved — the
    "error version" stays in the log but no longer represents the current
    state of the app. Owners only (plus admins) can rollback.
    """
    _validate_slug(slug)
    if not re.fullmatch(r"[0-9a-f]{7,40}", body.sha):
        raise HTTPException(status_code=400, detail="Invalid SHA")

    # Access: must be project member with 'owner' role OR an admin.
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)

    # Verify the SHA exists and touched this app.
    rc, out = await _run_git("cat-file", "-e", f"{body.sha}^{{commit}}")
    if rc != 0:
        raise HTTPException(status_code=404, detail="Commit not found")

    # Guard against dirty tree in apps/<slug>/.
    rc, dirty = await _run_git("status", "--porcelain", "--", f"apps/{slug}/")
    if rc == 0 and dirty.strip():
        raise HTTPException(
            status_code=409,
            detail=f"apps/{slug}/ has uncommitted changes — commit or discard first"
        )

    # Perform the checkout + commit.
    rc, out = await _run_git("checkout", body.sha, "--", f"apps/{slug}/")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"checkout failed: {out[:300]}")

    rc, out = await _run_git("add", f"apps/{slug}/")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"add failed: {out[:300]}")

    rc, status_out = await _run_git("diff", "--cached", "--quiet")
    # --quiet returns 1 if there ARE changes, 0 if none. No `raise` — we
    # read the exit code.
    if rc == 0:
        # Nothing to commit — target SHA already matches current files.
        return {"ok": True, "noop": True, "message": "Already at that version"}

    rc, out = await _run_git(
        "-c", f"user.email={user.email}",
        "-c", f"user.name={user.email.split('@')[0]}",
        "commit",
        "-m", f"Rollback apps/{slug}/ to {body.sha[:7]}",
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"commit failed: {out[:300]}")

    return {"ok": True, "noop": False}


# ---------------------------------------------------------------------------
# Publish (host the app at <slug>.ai-ui.coolestdomain.win)
# ---------------------------------------------------------------------------

class PublishStatus(BaseModel):
    published: bool
    public_url: str | None = None
    published_at: str | None = None
    published_by: str | None = None


def _public_host_for(slug: str) -> str:
    return f"{slug}.{PUBLIC_DOMAIN}"


def _public_url_for(slug: str) -> str:
    return f"https://{_public_host_for(slug)}/"


@router.get("/{slug}/publish", response_model=PublishStatus)
async def get_publish(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        row = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
    if row is None:
        return PublishStatus(published=False)
    return PublishStatus(
        published=True,
        public_url=_public_url_for(slug),
        published_at=row.published_at.isoformat() if row.published_at else None,
        published_by=row.published_by,
    )


@router.post("/{slug}/publish", response_model=PublishStatus)
async def publish_app(slug: str, user: AdminUser = Depends(current_admin)):
    """Publish apps/<slug>/ at https://<slug>.ai-ui.coolestdomain.win/.

    Owner/admin only. The Caddy wildcard handler reverse-proxies the
    subdomain back into this service's /__public/<slug>/ static route.
    """
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)

        # Verify apps/<slug>/index.html exists — otherwise publishing is pointless.
        index_path = os.path.join(REPO_ROOT, "apps", slug, "index.html")
        if not os.path.isfile(index_path):
            raise HTTPException(
                status_code=400,
                detail=f"apps/{slug}/index.html not found — only static apps with index.html are publishable today.",
            )

        existing = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if existing:
            return PublishStatus(
                published=True,
                public_url=_public_url_for(slug),
                published_at=existing.published_at.isoformat() if existing.published_at else None,
                published_by=existing.published_by,
            )
        row = PublishedApp(
            slug=slug,
            published_by=user.email,
            public_host=_public_host_for(slug),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    return PublishStatus(
        published=True,
        public_url=_public_url_for(slug),
        published_at=row.published_at.isoformat() if row.published_at else None,
        published_by=row.published_by,
    )


# ---------------------------------------------------------------------------
# Custom domains for published apps
# ---------------------------------------------------------------------------

class CustomDomainRequest(BaseModel):
    domain: str = Field(min_length=4, max_length=253)


class DnsInstruction(BaseModel):
    record_type: str
    name: str
    value: str
    note: str


class CustomDomainStatus(BaseModel):
    domain: str | None = None  # the user-supplied PARENT domain (e.g. example.com)
    public_url: str | None = None  # full live URL: https://<slug>.<domain>/
    fqdn: str | None = None  # just the hostname: <slug>.<domain>
    verified: bool = False
    verified_at: str | None = None
    server_ip: str
    instructions: list[DnsInstruction] = []
    last_check: dict | None = None


def _validate_custom_domain(domain: str) -> str:
    domain = (domain or "").strip().lower().rstrip(".")
    if not _DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail="Invalid domain format")
    if any(domain == s.lstrip(".") or domain.endswith(s) for s in RESERVED_DOMAIN_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail="Use the auto subdomain for our domain — custom hosts under coolestdomain.win are reserved",
        )
    return domain


def _instructions_for(slug: str, parent: str) -> list[DnsInstruction]:
    """DNS records the user must add at their registrar.

    The app's public URL is <slug>.<parent>. The user adds either a single
    A record for that exact subdomain, OR a wildcard so any future app on
    the same parent works automatically.

    NOTE: Only A records work — CNAME via our Cloudflare-fronted subdomain
    can't terminate HTTPS because Cloudflare has no cert for the user's
    hostname.
    """
    return [
        DnsInstruction(
            record_type="A",
            name=slug,
            value=SERVER_IP,
            note=f"Required. Adds {slug}.{parent} → our server. Use DNS-only (no proxy/CDN).",
        ),
        DnsInstruction(
            record_type="A",
            name="*",
            value=SERVER_IP,
            note=f"Optional wildcard. If you add this instead, ALL apps under {parent} will work without per-app DNS. Use DNS-only.",
        ),
    ]


def _split_host(host: str) -> tuple[str, str] | None:
    """Split a custom-domain host into (slug, parent). Returns None if the
    host has fewer than 3 labels (no leading subdomain)."""
    parts = (host or "").lower().strip().rstrip(".").split(".")
    if len(parts) < 3:
        return None
    return parts[0], ".".join(parts[1:])


async def _resolve_a_records(domain: str) -> list[str]:
    """Resolve a domain to ALL its A-record IPs.

    The container's libc resolver (via socket.getaddrinfo) often returns
    only ONE address per query — it applies RFC 6724 sorting and Docker's
    internal DNS forwards opaquely — which made verification miss the
    user's correct A record when they also had a stale CNAME alongside it.

    We bypass the container resolver entirely with DNS-over-HTTPS to
    Cloudflare (1.1.1.1). Falls back to socket.getaddrinfo if DoH fails.
    """
    domain = domain.strip().rstrip(".")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(
                "https://1.1.1.1/dns-query",
                params={"name": domain, "type": "A"},
                headers={"Accept": "application/dns-json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                ips = sorted({
                    a["data"] for a in (data.get("Answer") or [])
                    if a.get("type") == 1 and isinstance(a.get("data"), str)
                })
                if ips:
                    return ips
    except Exception:
        pass

    # Fallback: libc resolver. Better than nothing if DoH is blocked.
    import socket as _socket
    def _do() -> list[str]:
        try:
            res = _socket.getaddrinfo(domain, None, _socket.AF_INET, _socket.SOCK_STREAM)
            return sorted({r[4][0] for r in res})
        except OSError:
            return []
    return await asyncio.get_event_loop().run_in_executor(None, _do)


# Cloudflare's published IPv4 ranges (https://www.cloudflare.com/ips-v4).
# Hardcoded — they're extremely stable. Used to detect when a user's custom
# domain CNAMEs through Cloudflare, which won't terminate HTTPS for their
# hostname (Cloudflare doesn't have a cert for it).
_CLOUDFLARE_V4 = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22",
    "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
    "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22",
    "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
)


def _is_cloudflare_ip(ip: str) -> bool:
    import ipaddress
    try:
        addr = ipaddress.IPv4Address(ip)
    except (ipaddress.AddressValueError, ValueError):
        return False
    for cidr in _CLOUDFLARE_V4:
        try:
            if addr in ipaddress.IPv4Network(cidr):
                return True
        except (ipaddress.NetmaskValueError, ValueError):
            continue
    return False


def _build_status(slug: str, pub: PublishedApp | None,
                   last_check: dict | None = None) -> CustomDomainStatus:
    if pub is None or not pub.custom_domain:
        return CustomDomainStatus(server_ip=SERVER_IP, last_check=last_check)
    fqdn = f"{slug}.{pub.custom_domain}"
    verified = pub.custom_domain_verified_at is not None
    return CustomDomainStatus(
        domain=pub.custom_domain,
        fqdn=fqdn,
        public_url=f"https://{fqdn}/",
        verified=verified,
        verified_at=(
            pub.custom_domain_verified_at.isoformat() if pub.custom_domain_verified_at else None
        ),
        server_ip=SERVER_IP,
        instructions=_instructions_for(slug, pub.custom_domain),
        last_check=last_check,
    )


@router.get("/{slug}/publish/domain", response_model=CustomDomainStatus)
async def get_custom_domain(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        pub = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
    return _build_status(slug, pub)


@router.post("/{slug}/publish/domain", response_model=CustomDomainStatus)
async def set_custom_domain(
    slug: str,
    body: CustomDomainRequest,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    domain = _validate_custom_domain(body.domain)

    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)

        pub = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if pub is None:
            raise HTTPException(
                status_code=409,
                detail="Publish the app to its subdomain first — then attach your custom domain",
            )

        # Custom domain is a parent — multiple apps may share one (each gets
        # its own subdomain), so no global uniqueness check on the parent
        # itself. The (slug, parent) pair is naturally unique because slug
        # is the primary key.

        # Setting (or changing) the domain resets verification.
        pub.custom_domain = domain
        pub.custom_domain_verified_at = None
        await s.commit()
        await s.refresh(pub)

    return _build_status(slug, pub)


@router.post("/{slug}/publish/domain/verify", response_model=CustomDomainStatus)
async def verify_custom_domain(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        pub = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if pub is None or not pub.custom_domain:
            raise HTTPException(status_code=404, detail="No custom domain set")
        parent = pub.custom_domain
        fqdn = f"{slug}.{parent}"

        # Resolve the actual public hostname (<slug>.<parent>). If it
        # returns Cloudflare IPs, the user has the wrong type of record
        # for that subdomain — likely a CNAME through a Cloudflare-proxied
        # apex, which can't terminate TLS.
        ips = await _resolve_a_records(fqdn)
        ok = SERVER_IP in ips

        warning = None
        if not ok and ips and any(_is_cloudflare_ip(ip) for ip in ips):
            warning = (
                f"{fqdn} points at Cloudflare ({', '.join(ips)}). "
                f"That can't terminate HTTPS for your domain. Add an A record for "
                f"\"{slug}\" (or wildcard \"*\") pointing to {SERVER_IP}, with "
                f"the proxy/CDN toggle OFF (DNS-only)."
            )
        elif not ok and not ips:
            warning = (
                f"No A record found for {fqdn} yet. Add an A record for "
                f"\"{slug}\" or wildcard \"*\" → {SERVER_IP} at your DNS provider, "
                f"then click Re-verify (DNS may take a few minutes to propagate)."
            )
        elif not ok:
            warning = (
                f"{fqdn} resolves to {', '.join(ips)} — expected {SERVER_IP}. "
                f"Update the A record at your DNS provider."
            )

        if ok:
            from datetime import datetime as _dt
            pub.custom_domain_verified_at = _dt.utcnow()
            await s.commit()
            await s.refresh(pub)

    return _build_status(slug, pub, last_check={
        "fqdn": fqdn,
        "resolved_ips": ips,
        "expected_ip": SERVER_IP,
        "match": ok,
        "warning": warning,
    })


# ---------------------------------------------------------------------------
# Rename project (slug rename)
# ---------------------------------------------------------------------------

class RenameRequest(BaseModel):
    new_slug: str = Field(min_length=3, max_length=50)


@router.post("/{slug}/rename")
async def rename_project(
    slug: str,
    body: RenameRequest,
    user: AdminUser = Depends(current_admin),
):
    """Rename a project's slug.

    This moves apps/<old>/ → apps/<new>/ on disk (with a git commit),
    updates every DB row that references the slug, and re-keys any
    existing publish + custom-domain rows. Owner-only. Refused while
    a build is in flight or if any code uncommitted in the app dir.
    """
    _validate_slug(slug)
    new_slug = (body.new_slug or "").strip().lower()
    if not _SLUG_RE.match(new_slug):
        raise HTTPException(status_code=400, detail="Invalid name. Use lowercase letters, digits, and hyphens (3–50 chars).")
    if new_slug == slug:
        return {"ok": True, "noop": True, "message": "Same name — nothing to do."}

    # ── Authorization ──────────────────────────────────────────────────
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)

        # New slug must be available everywhere.
        from sqlalchemy import text as _text
        from models import TaskItem
        clash_in_tasks = (
            await s.execute(
                select(TaskItem.id).where(TaskItem.built_app_slug == new_slug).limit(1)
            )
        ).scalar_one_or_none()
        clash_in_pub = (
            await s.execute(
                select(PublishedApp.slug).where(PublishedApp.slug == new_slug).limit(1)
            )
        ).scalar_one_or_none()
        clash_in_members = (
            await s.execute(
                select(ProjectMember.slug).where(ProjectMember.slug == new_slug).limit(1)
            )
        ).scalar_one_or_none()
        if clash_in_tasks or clash_in_pub or clash_in_members:
            raise HTTPException(status_code=409, detail=f"Name '{new_slug}' is already taken.")

        # Refuse if a build is mid-flight on the old slug.
        active = (
            await s.execute(
                select(TaskItem.id).where(
                    TaskItem.built_app_slug == slug,
                    TaskItem.status.in_(["running", "planning", "awaiting_input"]),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if active:
            raise HTTPException(
                status_code=409,
                detail="A build is currently running on this project. Wait for it to finish before renaming.",
            )

    # ── Filesystem move + git commit ───────────────────────────────────
    old_dir = os.path.join(REPO_ROOT, "apps", slug)
    new_dir = os.path.join(REPO_ROOT, "apps", new_slug)
    if not os.path.isdir(old_dir):
        raise HTTPException(status_code=404, detail=f"apps/{slug}/ not found on disk")
    if os.path.exists(new_dir):
        raise HTTPException(status_code=409, detail=f"apps/{new_slug}/ already exists on disk")

    # Refuse if dir has uncommitted changes — we can't safely git-mv it.
    rc, dirty = await _run_git("status", "--porcelain", "--", f"apps/{slug}/")
    if rc == 0 and dirty.strip():
        raise HTTPException(
            status_code=409,
            detail=f"apps/{slug}/ has uncommitted changes. Wait for the current build to commit, then try again.",
        )

    rc, out = await _run_git("mv", f"apps/{slug}", f"apps/{new_slug}")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git mv failed: {out[:300]}")
    rc, out = await _run_git(
        "-c", f"user.email={user.email}",
        "-c", f"user.name={user.email.split('@')[0]}",
        "commit",
        "-m", f"Rename apps/{slug} → apps/{new_slug}",
    )
    if rc != 0:
        # Roll back the git-mv so we don't leave the working tree in a half state.
        await _run_git("reset", "--hard", "HEAD")
        raise HTTPException(status_code=500, detail=f"commit failed: {out[:300]}")

    # ── DB updates ─────────────────────────────────────────────────────
    try:
        async with session() as s:
            await s.execute(
                _text("UPDATE tasks.items SET built_app_slug = :n WHERE built_app_slug = :o"),
                {"o": slug, "n": new_slug},
            )
            await s.execute(
                _text("UPDATE tasks.published_apps SET slug = :n WHERE slug = :o"),
                {"o": slug, "n": new_slug},
            )
            await s.execute(
                _text("UPDATE tasks.project_members SET slug = :n WHERE slug = :o"),
                {"o": slug, "n": new_slug},
            )
            await s.commit()
    except Exception as exc:
        # DB update failed — roll the git rename back.
        await _run_git("revert", "--no-edit", "HEAD")
        raise HTTPException(status_code=500, detail=f"DB rename failed: {exc}")

    # Renaming changes the auto-subdomain URL and any custom-domain FQDN.
    # Custom domain mapping must be re-verified by the user since DNS now
    # needs to point at <new_slug>.<parent>.
    return {
        "ok": True,
        "old_slug": slug,
        "new_slug": new_slug,
        "auto_url": f"https://{new_slug}.{PUBLIC_DOMAIN}/",
    }


@router.delete("/{slug}/publish/domain", status_code=204)
async def remove_custom_domain(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        pub = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if pub is None:
            return None
        pub.custom_domain = None
        pub.custom_domain_verified_at = None
        await s.commit()
    return None


@router.delete("/{slug}/publish", status_code=204)
async def unpublish_app(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        existing = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if existing is None:
            return None
        await s.delete(existing)
        await s.commit()
    return None


@router.delete("/{slug}", status_code=204)
async def delete_project(slug: str, user: AdminUser = Depends(current_admin)):
    """Owner-only hard delete: removes the app folder on disk and every DB
    row that references this slug — items, executions (cascade), members,
    chat history, supabase config, published mapping. There's no undo."""
    from sqlalchemy import delete as _del
    import shutil
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        # DB cascade: items first (executions FK-cascade off items),
        # then per-slug tables.
        await s.execute(_del(TaskItem).where(TaskItem.built_app_slug == slug))
        await s.execute(_del(ChatMessage).where(ChatMessage.slug == slug))
        await s.execute(_del(ProjectSupabase).where(ProjectSupabase.slug == slug))
        await s.execute(_del(PublishedApp).where(PublishedApp.slug == slug))
        await s.execute(_del(ProjectMember).where(ProjectMember.slug == slug))
        await s.commit()
    # Filesystem: remove the app's folder if present. Best-effort — DB is
    # already wiped, so we don't fail the whole call on rmtree errors.
    workspace = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
    app_dir = os.path.join(workspace, "apps", slug)
    if os.path.isdir(app_dir):
        try:
            shutil.rmtree(app_dir)
        except Exception:
            pass
    return None
