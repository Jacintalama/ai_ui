"""The code endpoints, and the checks they must never skip.

Membership is the one that matters: the caller supplies a slug, so the
service has to decide whether that slug is theirs on every single call
rather than trusting an earlier answer.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import routes_code

SECRET = "test-internal-secret"
OWNER = "code-routes-owner@example.com"


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
