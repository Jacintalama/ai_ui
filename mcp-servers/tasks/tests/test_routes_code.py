"""The code endpoints, and the checks they must never skip.

Membership is the one that matters: the caller supplies a slug, so the
service has to decide whether that slug is theirs on every single call
rather than trusting an earlier answer.

Several tests below need a real database, so locally they error at setup
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
REAL_PROPOSAL_OWNER = "code-routes-real-proposal@example.com"


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
    # Creating is the newest way in and the most powerful: it starts a real
    # build. Listed here the day it was added, because the point of this
    # parametrisation is that a new route cannot quietly skip the check.
    ("POST", "/code/create", {"user_email": OWNER, "description": "a page"}),
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


# Building something that does not exist yet. Ralph's screenshot, 2026-09-18:
# he asked for a camera landing page called Thunder, and the agent answered "I
# can only build inside an existing app, so choose one of your existing app
# slugs". Every route above needs a slug, so the one thing an agent could not
# do was make the thing being asked for.

@pytest.fixture
def no_builder(monkeypatch):
    """The builder, replaced by a record of what it was asked.

    _spawn_build exists as a seam for exactly this: the real one imports the
    execution stack and starts an agent against a real directory.
    """
    asked = {}

    async def spawn(user_email, seed, description):
        asked.update(user_email=user_email, seed=seed, description=description)
        return "task-1", "camera-brand-9f21"

    async def url(slug):
        return "https://ai-ui.example/app-builder"

    monkeypatch.setattr(routes_code, "_spawn_build", spawn)
    monkeypatch.setattr(routes_code, "app_url", url)
    return asked


async def _create(client, **body):
    return await client.post("/code/create", json=body,
                             headers={"X-Internal-Secret": SECRET})


async def test_a_new_app_is_built_from_their_own_words(client, no_builder):
    """The description is the brief the builder works from, so it is passed
    through rather than summarised on the way."""
    r = await _create(client, user_email=OWNER, name="Thunder",
                      description="a landing page for my camera brand")
    assert r.status_code == 200, r.text
    assert no_builder["description"] == "a landing page for my camera brand"
    assert no_builder["user_email"] == OWNER
    assert r.json()["slug"] == "camera-brand-9f21"


async def test_the_reply_says_where_to_watch_it(client, no_builder):
    """Nothing is published while it builds, so the honest destination is App
    Builder, where the build can be watched."""
    r = await _create(client, user_email=OWNER, description="a page")
    assert r.json()["url"].endswith("/app-builder")
    assert r.json()["task_id"] == "task-1"


async def test_the_name_is_only_a_seed_for_the_slug(client, no_builder):
    await _create(client, user_email=OWNER, name="Thunder",
                  description="a landing page for my camera brand")
    assert no_builder["seed"] == "Thunder"


async def test_no_name_seeds_the_slug_from_the_description(client, no_builder):
    """Asking for a name twice is a worse conversation than picking one: "a
    landing page for my camera brand" is already a usable seed."""
    await _create(client, user_email=OWNER,
                  description="a landing page for my camera brand")
    assert no_builder["seed"] == "a landing page for my camera brand"


@pytest.mark.parametrize("description", ["", "   ", "\n\t "])
async def test_an_empty_description_builds_nothing(client, no_builder,
                                                   description):
    """A build with no brief produces something nobody asked for, and it holds
    the platform's single build slot while it does."""
    r = await _create(client, user_email=OWNER, description=description)
    assert r.status_code == 400
    assert no_builder == {}, "it started a build with no brief"


async def test_one_build_at_a_time_reaches_the_caller(client, monkeypatch):
    """The builder allows one build platform-wide and says so with a 429.
    Swallowing it would leave an agent reporting a failure for a queue."""
    async def busy(user_email, seed, description):
        raise HTTPException(status_code=429,
                            detail="A build is already running. Try shortly.")

    monkeypatch.setattr(routes_code, "_spawn_build", busy)
    r = await _create(client, user_email=OWNER, description="a page")
    assert r.status_code == 429
    assert "already running" in r.json()["detail"]


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


async def test_apply_never_takes_the_slug_from_the_caller(client, monkeypatch, tmp_path):
    """The slug comes out of the stored proposal. A caller that sends one
    must not be able to steer the build with it."""
    _app_on_disk(tmp_path, "from-the-proposal")
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


@pytest_asyncio.fixture
async def clean_real_proposal(db_session_nondestructive):
    """Deletes only rows this test created, matched on REAL_PROPOSAL_OWNER,
    before and after. Same cleanup pattern as test_code_proposals.py's
    clean_proposals fixture: nothing else in tasks.agent_proposals is
    touched, which is what makes this safe against the real database."""
    async def _purge():
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.agent_proposals WHERE user_email = :email"),
            {"email": REAL_PROPOSAL_OWNER})
        await db_session_nondestructive.commit()
    await _purge()
    yield db_session_nondestructive
    await _purge()


async def test_what_the_person_approves_is_what_will_run_for_real(
        client, monkeypatch, tmp_path, clean_real_proposal):
    """test_what_the_person_approves_is_what_will_run above proves the
    route agrees with a copy of create_proposal's strip() living in this
    test file, not with create_proposal itself. If the real function ever
    normalised differently, a person would approve one string while
    another ran, and that test would stay green. This one runs the real
    create_proposal and consume_proposal, with only _can_see and
    _spawn_enhance stubbed, so a real drift between the route and storage
    would actually fail here."""
    _app_on_disk(tmp_path)

    async def _yes(*_args, **_kwargs):
        return True
    monkeypatch.setattr(routes_code, "_can_see", _yes)

    seen = {}

    async def _spawn(email, slug, prompt):
        seen["prompt"] = prompt
        return ("task-1", slug)

    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    proposed = await client.post(
        "/code/propose",
        json={"user_email": REAL_PROPOSAL_OWNER, "slug": "shop",
              "description": "  make the button blue  "},
        headers={"X-Internal-Secret": SECRET})
    assert proposed.status_code == 200
    shown = proposed.json()["description"]

    applied = await client.post(
        "/code/apply",
        json={"user_email": REAL_PROPOSAL_OWNER,
              "token": proposed.json()["token"]},
        headers={"X-Internal-Secret": SECRET})
    assert applied.status_code == 200

    assert seen["prompt"] == shown, (
        "the build ran with something other than what the person approved")


async def test_apply_refuses_a_proposal_whose_app_directory_is_gone(
        client, tmp_path, clean_real_proposal):
    """propose refuses a slug with no directory via _require_member. Up to
    thirty minutes can pass before apply runs. The normal delete path
    removes the task rows first, so the builder would 404 there anyway; the
    residual case this guards is a directory removed by hand on the box
    while its rows survive, which CLAUDE.md says happens on this server.
    apply must re-check rather than send an agent at a path that is gone,
    and it must give the approval back exactly like the other refusals
    raised before the builder is reached."""
    import shutil

    from code_proposals import consume_proposal, create_proposal

    _app_on_disk(tmp_path, "shop")
    token = await create_proposal(REAL_PROPOSAL_OWNER, "shop", "make it blue")

    # The directory vanishes by hand, the way CLAUDE.md describes, while
    # the proposal row survives.
    shutil.rmtree(tmp_path / "shop")

    r = await client.post(
        "/code/apply",
        json={"user_email": REAL_PROPOSAL_OWNER, "token": token},
        headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert "no app by that name" in r.json()["detail"]

    # The approval was given back: consuming it again for real succeeds,
    # which only a genuinely restored row allows.
    again = await consume_proposal(REAL_PROPOSAL_OWNER, token)
    assert again["slug"] == "shop"


@pytest.mark.parametrize("status", [403, 404, 409])
async def test_a_refused_build_gives_the_approval_back(client, monkeypatch, tmp_path, status):
    """All three are raised before the builder writes anything, so all
    three must give the approval back. The 409 is the one that bites: it
    means an enhance is already running, which includes one waiting on a
    human, and burning the approval there would make the assistant ask the
    same person for the same yes over and over."""
    _app_on_disk(tmp_path)
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


async def test_a_failure_to_restore_still_shows_the_real_status(client, monkeypatch, tmp_path):
    """Giving the approval back is best effort. If it fails, the person
    must still be told an enhance is already running, not handed a 500
    that tells them nothing."""
    _app_on_disk(tmp_path)

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


async def test_an_unexpected_failure_keeps_the_approval_spent(client, monkeypatch, tmp_path):
    """Fail closed. If the builder broke in a way we do not recognise,
    work may already have started, and giving the code back could run
    the same change twice."""
    _app_on_disk(tmp_path)
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


async def test_an_unrecognised_http_failure_keeps_the_approval_spent(client, monkeypatch, tmp_path):
    """The three statuses that give the approval back are the three the
    builder raises before it inserts anything. A 500 is not one of them:
    by then the build may exist, so the approval stays spent. Without this
    the status list itself is untested, because a plain exception never
    reaches that branch at all."""
    _app_on_disk(tmp_path)
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


def test_the_builder_seam_still_has_the_shape_we_call_it_with():
    """routes_code spends the person's approval BEFORE this call, so a
    drift here fails after the approval is gone and in a way apply
    cannot classify, meaning it neither restores it nor explains
    itself. Nothing else in the repo asserts this seam."""
    import inspect
    from routes_aiuibuilder import _create_and_spawn_enhance

    params = list(inspect.signature(_create_and_spawn_enhance).parameters)
    assert params[:3] == ["email", "slug", "prompt"], params
    assert inspect.iscoroutinefunction(_create_and_spawn_enhance)
