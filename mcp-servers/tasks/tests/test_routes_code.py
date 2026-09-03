"""The code endpoints, and the checks they must never skip.

Membership is the one that matters: the caller supplies a slug, so the
service has to decide whether that slug is theirs on every single call
rather than trusting an earlier answer.

The last three tests need a real database, so locally they error at setup
with no Postgres, exactly like the db tier described in CLAUDE.md. They use
db_session_nondestructive, which truncates nothing, and delete only the
rows they create, matched on emails unique to this file.
"""
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import routes_code
from models import ProjectMember, TaskItem

SECRET = "test-internal-secret"
OWNER = "code-routes-owner@example.com"

# Only the db-backed tests below use these. They are unique to this file so
# its cleanup can match on the email and delete nothing else.
BUILD_OWNER = "code-routes-build-owner@example.com"
BUILD_SLUG = "code-routes-build-only-app"
# A row with no directory, the shape the cron scheduler's sched-... rows have.
GHOST_SLUG = "code-routes-never-an-app"
MEMBER = "code-routes-member@example.com"
STRANGER = "code-routes-stranger@example.com"
MEMBER_SLUG = "code-routes-member-app"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.setattr(routes_code, "_apps_root_override", tmp_path, raising=False)

    app = FastAPI()
    app.include_router(routes_code.router)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://t")


def _app_on_disk(tmp_path, slug="shop"):
    d = tmp_path / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<h1>Shop</h1>\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/code/apps", None),
    ("GET", "/code/file", None),
    ("GET", "/code/search", None),
    ("POST", "/code/propose", {"user_email": OWNER, "slug": "shop",
                               "description": "x"}),
    ("POST", "/code/apply", {"user_email": OWNER, "token": "t"}),
])
async def test_every_endpoint_requires_the_secret(client, method, path, payload):
    """Internal only is this surface's primary safety property, and it was
    held by a single test on a single endpoint. A refactor that moved the
    check and missed one would have served app source to anything that can
    reach tasks:8210."""
    if method == "GET":
        r = await client.get(path, params={"user_email": OWNER,
                                           "slug": "shop", "path": "index.html",
                                           "query": "x"})
    else:
        r = await client.post(path, json=payload)
    assert r.status_code == 403, path


def test_the_router_is_mounted_once_and_only_internally():
    """The mount itself, pinned. Read through app.openapi() and not
    app.routes: several test files here note that the container's FastAPI
    includes routers lazily, and prod runs a later version than local. A
    second mount under /api/tasks would put an internal-only surface on a
    publicly routed prefix."""
    from main import app
    paths = set(app.openapi()["paths"].keys())
    assert {"/code/apps", "/code/file", "/code/search",
            "/code/propose", "/code/apply"} <= paths
    assert not [p for p in paths if p.startswith("/api/tasks/code")]


async def test_a_non_member_cannot_read_a_file(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _no(*_args, **_kwargs):
        return False
    monkeypatch.setattr(routes_code, "_can_see", _no)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "index.html"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 403


async def test_a_member_reads_their_own_file(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _yes(*_args, **_kwargs):
        return True
    monkeypatch.setattr(routes_code, "_can_see", _yes)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "index.html"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert "Shop" in r.json()["text"]


async def test_a_refused_path_is_a_clean_400_not_a_stack_trace(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _yes(*_args, **_kwargs):
        return True
    monkeypatch.setattr(routes_code, "_can_see", _yes)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "../secret.txt"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert "not inside this app" in r.json()["detail"]


async def test_apply_never_takes_the_slug_from_the_caller(client, monkeypatch):
    """The slug comes out of the stored proposal. A caller that sends one
    must not be able to steer the build with it."""
    seen = {}

    async def _consume(email, token):
        return {"slug": "from-the-proposal", "description": "make it blue"}

    async def _spawn(email, slug, prompt):
        seen["slug"] = slug
        seen["prompt"] = prompt
        return ("task-1", slug)

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t",
                                "slug": "attacker-supplied"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert seen["slug"] == "from-the-proposal"


async def test_apply_with_a_bad_token_starts_nothing(client, monkeypatch):
    from code_proposals import ProposalError

    async def _consume(email, token):
        raise ProposalError("that approval code is not usable")

    started = []

    async def _spawn(email, slug, prompt):
        started.append(slug)
        return ("task-1", slug)

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "nope"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert started == []


async def test_propose_checks_membership_before_writing_a_token(client, monkeypatch):
    async def _no(*_args, **_kwargs):
        return False
    written = []

    async def _create(email, slug, description):
        written.append(slug)
        return "token"

    monkeypatch.setattr(routes_code, "_can_see", _no)
    monkeypatch.setattr(routes_code, "create_proposal", _create)

    r = await client.post("/code/propose",
                          json={"user_email": OWNER, "slug": "shop",
                                "description": "make it blue"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 403
    assert written == []


async def test_what_the_person_approves_is_what_will_run(client, monkeypatch, tmp_path):
    """The description shown at propose time and the one apply executes
    must be the same string. They come from different places: the
    response echoes the request, while apply reads the stored row. If
    create_proposal ever normalises differently from this endpoint,
    somebody approves one change and another one runs."""
    _app_on_disk(tmp_path)
    stored = {}

    async def _create(email, slug, description):
        # Stands in for the real create_proposal, including its strip.
        stored["description"] = description.strip()
        return "token-abc"

    async def _consume(email, token):
        return {"slug": "shop", "description": stored["description"]}

    seen = {}

    async def _spawn(email, slug, prompt):
        seen["prompt"] = prompt
        return ("task-1", slug)

    async def _yes(*_args, **_kwargs):
        return True

    monkeypatch.setattr(routes_code, "_can_see", _yes)
    monkeypatch.setattr(routes_code, "create_proposal", _create)
    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    proposed = await client.post(
        "/code/propose",
        json={"user_email": OWNER, "slug": "shop",
              "description": "  make the button blue  "},
        headers={"X-Internal-Secret": SECRET})
    assert proposed.status_code == 200
    shown = proposed.json()["description"]

    applied = await client.post(
        "/code/apply",
        json={"user_email": OWNER, "token": "token-abc"},
        headers={"X-Internal-Secret": SECRET})
    assert applied.status_code == 200

    assert shown == stored["description"], (
        "the person was shown something other than what was stored")
    assert seen["prompt"] == shown, (
        "the build ran with something other than what the person approved")


@pytest.mark.parametrize("status", [403, 404, 409])
async def test_a_refused_build_gives_the_approval_back(client, monkeypatch, status):
    """All three are raised before the builder writes anything, so all
    three must give the approval back. The 409 is the one that bites: it
    means an enhance is already running, which includes one waiting on a
    human, and burning the approval there would make the assistant ask the
    same person for the same yes over and over."""
    restored = []

    async def _consume(email, token):
        return {"slug": "shop", "description": "make it blue"}

    async def _restore(email, token):
        restored.append(token)

    async def _spawn(email, slug, prompt):
        raise HTTPException(status_code=status, detail="refused before any write")

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "restore_proposal", _restore)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == status
    assert restored == ["t"]


async def test_a_failure_to_restore_still_shows_the_real_status(client, monkeypatch):
    """Giving the approval back is best effort. If it fails, the person
    must still be told an enhance is already running, not handed a 500
    that tells them nothing."""
    async def _consume(email, token):
        return {"slug": "shop", "description": "make it blue"}

    async def _restore(email, token):
        raise RuntimeError("the database went away")

    async def _spawn(email, slug, prompt):
        raise HTTPException(status_code=409,
                            detail="An enhancement is already in progress")

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "restore_proposal", _restore)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 409
    assert "already in progress" in r.json()["detail"]


async def test_an_unexpected_failure_keeps_the_approval_spent(client, monkeypatch):
    """Fail closed. If the builder broke in a way we do not recognise,
    work may already have started, and giving the code back could run
    the same change twice."""
    restored = []

    async def _consume(email, token):
        return {"slug": "shop", "description": "make it blue"}

    async def _restore(email, token):
        restored.append(token)

    async def _spawn(email, slug, prompt):
        raise RuntimeError("something else entirely")

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "restore_proposal", _restore)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    with pytest.raises(RuntimeError):
        await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t"},
                          headers={"X-Internal-Secret": SECRET})
    assert restored == []


async def test_an_unrecognised_http_failure_keeps_the_approval_spent(client, monkeypatch):
    """The three statuses that give the approval back are the three the
    builder raises before it inserts anything. A 500 is not one of them:
    by then the build may exist, so the approval stays spent. Without this
    the status list itself is untested, because a plain exception never
    reaches that branch at all."""
    restored = []

    async def _consume(email, token):
        return {"slug": "shop", "description": "make it blue"}

    async def _restore(email, token):
        restored.append(token)

    async def _spawn(email, slug, prompt):
        raise HTTPException(status_code=500, detail="the build blew up midway")

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "restore_proposal", _restore)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 500
    assert restored == []


def _build_row(slug):
    return TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Build Owner", assignee_email=BUILD_OWNER,
        description="build the shop", priority="NICE_TO_HAVE",
        status="completed", built_app_slug=slug,
    )


@pytest_asyncio.fixture
async def build_rows_without_membership(db_session_nondestructive):
    """Two build tasks owned by BUILD_OWNER and deliberately no membership
    row, which is the state a build lands in when the membership grant
    fails open. One of the two will have a directory on disk and the other
    never will, the way the cron scheduler's sched-... rows never do.
    Deletes only rows matched on BUILD_OWNER, before and after, so this is
    safe against the real database."""
    async def _purge():
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.items WHERE assignee_email = :email"),
            {"email": BUILD_OWNER})
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.project_members WHERE user_email = :email"),
            {"email": BUILD_OWNER})
        await db_session_nondestructive.commit()

    await _purge()
    db_session_nondestructive.add(_build_row(BUILD_SLUG))
    db_session_nondestructive.add(_build_row(GHOST_SLUG))
    await db_session_nondestructive.commit()
    yield db_session_nondestructive
    await _purge()


async def test_an_app_owned_through_a_build_task_is_listed(
        client, tmp_path, build_rows_without_membership):
    """The read gate grants access through a build task as well as a
    membership row. Listing only members would hide an app the person
    can open, which is reachable because the membership grant after a
    build fails open."""
    _app_on_disk(tmp_path, BUILD_SLUG)

    r = await client.get("/code/apps", params={"user_email": BUILD_OWNER},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert BUILD_SLUG in r.json()["apps"]


async def test_a_slug_with_no_directory_is_not_listed(
        client, tmp_path, build_rows_without_membership):
    """tasks.items holds BUILD rows the cron scheduler wrote that were
    never apps and have no directory, and rows for apps since deleted.
    Listing one lets somebody approve a change to a thing that cannot be
    changed, and the builder would then spawn a real agent against a path
    that does not exist."""
    _app_on_disk(tmp_path, BUILD_SLUG)

    r = await client.get("/code/apps", params={"user_email": BUILD_OWNER},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    apps = r.json()["apps"]
    # Both halves matter: a filter that simply dropped everything would
    # satisfy the second assertion on its own.
    assert BUILD_SLUG in apps
    assert GHOST_SLUG not in apps


async def test_a_slug_with_no_directory_cannot_be_proposed_against(
        client, build_rows_without_membership):
    """The listing filter stops a ghost slug being offered. This stops
    one being named directly, which is the path that reaches the builder
    and spawns an agent against a directory that does not exist."""
    r = await client.post(
        "/code/propose",
        json={"user_email": BUILD_OWNER, "slug": GHOST_SLUG,
              "description": "make it blue"},
        headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert "no app by that name" in r.json()["detail"]


@pytest_asyncio.fixture
async def a_real_membership(db_session_nondestructive):
    """One membership row for MEMBER and nothing at all for STRANGER, so
    the real gate has something true and something false to decide.
    Deletes only rows matched on those two emails, before and after."""
    async def _purge():
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.project_members"
                 " WHERE user_email IN (:a, :b)"),
            {"a": MEMBER, "b": STRANGER})
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.items WHERE assignee_email IN (:a, :b)"),
            {"a": MEMBER, "b": STRANGER})
        await db_session_nondestructive.commit()

    await _purge()
    db_session_nondestructive.add(ProjectMember(
        slug=MEMBER_SLUG, user_email=MEMBER, role="owner", added_by=MEMBER))
    await db_session_nondestructive.commit()
    yield db_session_nondestructive
    await _purge()


async def test_the_real_membership_check_decides_who_reads(
        client, tmp_path, a_real_membership):
    """_can_see is monkeypatched in every other test in this file, so the
    real query has never run here, and the one other database test calls
    an endpoint that does not use it. Swapping its two arguments would
    make every read allow or deny universally in production, which is
    invisible to a test that stubs the function out."""
    _app_on_disk(tmp_path, MEMBER_SLUG)

    allowed = await client.get(
        "/code/file",
        params={"user_email": MEMBER, "slug": MEMBER_SLUG,
                "path": "index.html"},
        headers={"X-Internal-Secret": SECRET})
    assert allowed.status_code == 200
    assert "Shop" in allowed.json()["text"]

    refused = await client.get(
        "/code/file",
        params={"user_email": STRANGER, "slug": MEMBER_SLUG,
                "path": "index.html"},
        headers={"X-Internal-Secret": SECRET})
    assert refused.status_code == 403
