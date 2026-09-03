"""The code endpoints, and the checks they must never skip.

Membership is the one that matters: the caller supplies a slug, so the
service has to decide whether that slug is theirs on every single call
rather than trusting an earlier answer.

The last test needs a real database, so locally it errors at setup with no
Postgres, exactly like the db tier described in CLAUDE.md. It uses
db_session_nondestructive, which truncates nothing, and deletes only the
rows it creates, matched on an email unique to this file.
"""
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import routes_code
from models import TaskItem

SECRET = "test-internal-secret"
OWNER = "code-routes-owner@example.com"

# Only the db-backed test below uses these two. They are unique to this file
# so its cleanup can match on the email and delete nothing else.
BUILD_OWNER = "code-routes-build-owner@example.com"
BUILD_SLUG = "code-routes-build-only-app"


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


async def test_the_secret_is_required(client):
    r = await client.get("/code/apps", params={"user_email": OWNER})
    assert r.status_code == 403


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


@pytest_asyncio.fixture
async def only_a_build_task(db_session_nondestructive):
    """One build task owned by BUILD_OWNER and deliberately no membership
    row, which is the state a build lands in when the membership grant
    fails open. Deletes only rows matched on BUILD_OWNER, before and after,
    so this is safe against the real database."""
    async def _purge():
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.items WHERE assignee_email = :email"),
            {"email": BUILD_OWNER})
        await db_session_nondestructive.execute(
            text("DELETE FROM tasks.project_members WHERE user_email = :email"),
            {"email": BUILD_OWNER})
        await db_session_nondestructive.commit()

    await _purge()
    db_session_nondestructive.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Build Owner", assignee_email=BUILD_OWNER,
        description="build the shop", priority="NICE_TO_HAVE",
        status="completed", built_app_slug=BUILD_SLUG,
    ))
    await db_session_nondestructive.commit()
    yield db_session_nondestructive
    await _purge()


async def test_an_app_owned_through_a_build_task_is_listed(client, only_a_build_task):
    """The read gate grants access through a build task as well as a
    membership row. Listing only members would hide an app the person
    can open, which is reachable because the membership grant after a
    build fails open."""
    r = await client.get("/code/apps", params={"user_email": BUILD_OWNER},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert BUILD_SLUG in r.json()["apps"]
