"""create and apply mark the job with the calling agent's design skill.

The agent id comes from the tool runner, not the model, and the route looks
the skill up itself (design_skill.for_agent), so what reaches the builder is
the agent's real setting and never a flag the model chose.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import routes_code

SECRET = "test-internal-secret"
OWNER = "code-routes-design@example.com"
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.setattr(routes_code, "_apps_root_override", tmp_path,
                        raising=False)

    async def url(slug):
        return "https://ai-ui.example/apps/%s/" % slug
    monkeypatch.setattr(routes_code, "app_url", url)

    app = FastAPI()
    app.include_router(routes_code.router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def lookups(monkeypatch):
    """The design lookup, recording who asked. Agent dev has Impeccable."""
    seen = []

    async def _design_for(user_email, agent_id):
        seen.append((user_email, agent_id))
        return "impeccable" if agent_id == "agent-dev-c82b" else None
    monkeypatch.setattr(routes_code, "_design_for", _design_for)
    return seen


@pytest.fixture
def builds(monkeypatch):
    spawned = []

    async def _spawn_build(user_email, seed, description, design_skill=None):
        spawned.append(design_skill)
        return "task-1", "crumb-and-co"

    async def _spawn_enhance(user_email, slug, prompt, design_skill=None):
        spawned.append(design_skill)
        return "task-2", slug

    async def _consume(email, token):
        return {"slug": "crumb-and-co", "description": "bigger hours"}

    monkeypatch.setattr(routes_code, "_spawn_build", _spawn_build)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn_enhance)
    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    return spawned


@pytest.mark.parametrize("agent_id,expected", [
    ("agent-dev-c82b", "impeccable"),
    ("agent-other", None),
    (None, None),
])
async def test_create_marks_the_build_from_the_agent(
        client, lookups, builds, agent_id, expected):
    body = {"user_email": OWNER, "description": "a bakery landing page"}
    if agent_id is not None:
        body["agent_id"] = agent_id
    r = await client.post("/code/create", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert builds == [expected]
    assert lookups == [(OWNER, agent_id)]


@pytest.mark.parametrize("agent_id,expected", [
    ("agent-dev-c82b", "impeccable"),
    (None, None),
])
async def test_apply_marks_the_change_from_the_agent(
        client, lookups, builds, tmp_path, agent_id, expected):
    (tmp_path / "crumb-and-co").mkdir()
    (tmp_path / "crumb-and-co" / "index.html").write_text("<h1>Crumb</h1>")
    body = {"user_email": OWNER, "token": "t"}
    if agent_id is not None:
        body["agent_id"] = agent_id
    r = await client.post("/code/apply", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert builds == [expected]
    assert lookups == [(OWNER, agent_id)]


async def test_the_seam_is_the_real_lookup(monkeypatch):
    seen = []

    async def for_agent(user_email, agent_id):
        seen.append((user_email, agent_id))
        return "impeccable"
    monkeypatch.setattr(routes_code.design_skill, "for_agent", for_agent)
    assert await routes_code._design_for(OWNER, "agent-x") == "impeccable"
    assert seen == [(OWNER, "agent-x")]
