"""Running an agent from outside with an automation key (2026-10-27).

What has to hold: a call proves whose agents it may run with a key the
person made, and nothing else; the agent is found exactly, by id or name;
the turn runs on the automation surface, where only `all` acts; a workflow
always reads a status, never a stack trace; a callback goes only to a
public host; and keys are shown once, listed, capped and revoked.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import agent_access
import agent_activity
import automation_keys as ak
import routes_automation as ra
from auth import CurrentUser, current_user

OWNER = "owner@example.com"
ADA = {"id": "agent-ada-1a2b", "name": "Ada", "user_id": "u1", "meta": {}}
MIA = {"id": "agent-mia-3c4d", "name": "Mia", "user_id": "u1", "meta": {}}


# --- the keys themselves ---------------------------------------------------

def test_a_key_is_recognisable_unguessable_and_stored_only_as_a_hash():
    k = ak.make_key()
    assert k.startswith("iok_") and len(k) > 30 and ak.looks_like_key(k)
    assert ak.make_key() != k
    assert ak.hash_key(k) != k and len(ak.hash_key(k)) == 64
    assert ak.prefix_of(k) == k[:12]
    assert not ak.looks_like_key("sk-abcdefghijklmnopqrstuvwxyz")
    assert not ak.looks_like_key("iok_short") and not ak.looks_like_key(None)


async def test_the_owner_is_found_by_hash_and_nothing_else(monkeypatch):
    k = ak.make_key()
    seen = {}

    async def by_hash(h):
        seen["hash"] = h
        return OWNER if h == ak.hash_key(k) else None
    monkeypatch.setattr(ak, "_email_for_hash_seam", by_hash)
    assert await ak.email_for(k) == OWNER
    assert seen["hash"] == ak.hash_key(k), "the key itself reached the database"
    assert await ak.email_for(ak.make_key()) is None
    assert await ak.email_for("not a key") is None


async def test_a_database_outage_reads_as_not_a_key(monkeypatch):
    monkeypatch.setattr(ak, "_email_for_hash_seam", AsyncMock(side_effect=RuntimeError("down")))
    assert await ak.email_for(ak.make_key()) is None


async def test_creating_returns_the_key_once_and_stores_the_hash(monkeypatch):
    stored = {}

    async def create(email, label, key_hash, prefix):
        stored.update(email=email, label=label, key_hash=key_hash, prefix=prefix)
        return {"id": "k1", "label": label, "prefix": prefix}
    monkeypatch.setattr(ak, "_create", create)
    out = await ak.create(OWNER, "  n8n   inbox  ")
    assert out["key"].startswith("iok_") and stored["key_hash"] == ak.hash_key(out["key"])
    assert stored["label"] == "n8n inbox" and stored["prefix"] == ak.prefix_of(out["key"])
    assert "key_hash" not in out


# --- the surface --------------------------------------------------------------

@pytest.mark.parametrize("level,expected", [
    (None, agent_access.MODE_READ_ONLY), ("read", agent_access.MODE_READ_ONLY),
    ("ask", agent_access.MODE_ASK), ("all", agent_access.MODE_FULL)])
def test_an_automation_acts_for_all_asks_for_ask_and_reads_otherwise(level, expected):
    assert agent_access.effective_mode(level, "full", agent_access.SURFACE_AUTOMATION) == expected


def test_the_automation_refusal_reads_as_a_clause():
    for level in (None, "read"):
        reason = agent_access.refusal_reason(level, None, agent_access.SURFACE_AUTOMATION)
        assert reason[0].islower() and not reason.endswith(".")


async def test_the_run_is_recorded_as_an_automation(monkeypatch):
    import routes_agent_turn as rt
    seen = {}

    async def resolve(user_email, agent_id):
        return ("tok", [], agent_access.LEVEL_ALL, {"id": agent_id, "name": "Ada"}, [])

    async def chat(**kw):
        seen["mode"] = kw.get("tool_mode")
        return ("done", [])

    async def start_run(agent_id, user_email, source, parent_run_id=None):
        seen["source"] = source
        return "run-1"

    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", start_run)
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection", lambda *a, **k: None)
    out = await rt._run_turn(OWNER, "agent-ada-1a2b", [{"role": "user", "content": "hi"}],
                             surface=agent_access.SURFACE_AUTOMATION)
    assert out["answer"] == "done"
    assert seen["source"] == agent_activity.SOURCE_AUTOMATION
    assert seen["mode"] == agent_access.MODE_FULL


# --- the route ----------------------------------------------------------------

@pytest.fixture
def wired(monkeypatch):
    key = ak.make_key()
    seen = {"turns": [], "posted": [], "spawned": []}

    async def email_for(k):
        return OWNER if k == key else None

    async def agents(email):
        return [ADA, MIA] if email == OWNER else []

    async def run_turn(email, agent_id, messages, brief=False, surface=None):
        seen["turns"].append({"email": email, "agent_id": agent_id,
                              "messages": messages, "brief": brief, "surface": surface})
        return {"answer": f"Hello from {agent_id}.", "notes": ["a note"]}

    async def post(url, payload):
        seen["posted"].append((url, payload))
        return True

    def spawn(coro):
        seen["spawned"].append(coro)
        return coro

    monkeypatch.setattr(ak, "email_for", email_for)
    monkeypatch.setattr(ra, "_agents_seam", agents)
    monkeypatch.setattr(ra, "_run_turn_seam", run_turn)
    monkeypatch.setattr(ra, "_post_callback_seam", post)
    monkeypatch.setattr(ra, "_spawn", spawn)
    monkeypatch.setattr(ra, "_resolve_seam", lambda host: ["93.184.216.34"])
    seen["key"] = key
    return seen


@pytest.fixture
def client(wired):
    app = FastAPI()
    app.include_router(ra.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app)


def _auth(wired, key=None):
    return {"Authorization": "Bearer " + (key or wired["key"])}


def test_no_key_and_a_wrong_key_are_refused_before_anything_runs(client, wired):
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": "hi"})
    assert r.status_code == 401 and "Agents page" in r.json()["detail"]
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": "hi"},
                    headers=_auth(wired, "iok_" + "x" * 32))
    assert r.status_code == 401 and "revoked" in r.json()["detail"]
    # The gateway's own header does not stand in for a key.
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": "hi"},
                    headers={"X-User-Email": OWNER})
    assert r.status_code == 401
    assert wired["turns"] == []


def test_the_agent_runs_by_name_on_the_automation_surface(client, wired):
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "ada", "message": "What is due this week?"},
                    headers=_auth(wired))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "done" and out["agent"] == {"id": "agent-ada-1a2b", "name": "Ada"}
    assert out["answer"] == "Hello from agent-ada-1a2b." and out["notes"] == ["a note"]
    assert len(out["id"]) == 32
    turn = wired["turns"][0]
    assert turn["email"] == OWNER and turn["agent_id"] == "agent-ada-1a2b"
    assert turn["messages"] == [{"role": "user", "content": "What is due this week?"}]
    assert turn["brief"] is True and turn["surface"] == agent_access.SURFACE_AUTOMATION


def test_the_agent_runs_by_id_too(client, wired):
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "agent-mia-3c4d", "message": "hi"}, headers=_auth(wired))
    assert r.status_code == 200 and r.json()["agent"]["name"] == "Mia"


def test_an_unknown_agent_is_named_with_the_ones_that_exist(client, wired):
    r = client.post("/api/tasks/agents/run", json={"agent": "Zed", "message": "hi"},
                    headers=_auth(wired))
    assert r.status_code == 404
    assert "No agent called 'Zed'" in r.json()["detail"]
    assert "Ada, Mia" in r.json()["detail"]
    assert wired["turns"] == []


def test_a_near_miss_does_not_run_an_agent():
    assert ra.find_agent([ADA, MIA], "Ad") is None
    assert ra.find_agent([ADA, MIA], "") is None
    assert ra.find_agent([ADA, dict(MIA, name="ada")], "Ada") is None, "two of them"
    assert ra.find_agent([ADA], " ADA ") is ADA


def test_a_turn_that_blows_up_is_a_failed_status_not_a_500(client, wired, monkeypatch):
    monkeypatch.setattr(ra, "_run_turn_seam", AsyncMock(side_effect=RuntimeError("boom")))
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": "hi"},
                    headers=_auth(wired))
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and r.json()["notes"] == [ra.TURN_FAILED]
    assert "boom" not in r.text


def test_a_known_refusal_from_the_turn_is_passed_on_as_a_note(client, wired, monkeypatch):
    monkeypatch.setattr(ra, "_run_turn_seam", AsyncMock(
        side_effect=HTTPException(status_code=409, detail="This agent is set to a model that cannot run an agent.")))
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": "hi"},
                    headers=_auth(wired))
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert r.json()["notes"] == ["This agent is set to a model that cannot run an agent."]


def test_an_empty_or_huge_message_is_refused(client, wired):
    r = client.post("/api/tasks/agents/run", json={"agent": "Ada", "message": ""},
                    headers=_auth(wired))
    assert r.status_code == 422
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "Ada", "message": "x" * (ra.MAX_MESSAGE_CHARS + 1)},
                    headers=_auth(wired))
    assert r.status_code == 422


async def test_a_callback_returns_at_once_and_posts_the_result(client, wired):
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "Ada", "message": "hi",
                          "callback_url": "https://hooks.example.com/run"},
                    headers=_auth(wired))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "accepted" and out["agent"]["name"] == "Ada"
    assert wired["turns"] == [], "it ran before answering"
    assert len(wired["spawned"]) == 1
    await wired["spawned"][0]
    assert len(wired["turns"]) == 1
    url, payload = wired["posted"][0]
    assert url == "https://hooks.example.com/run"
    assert payload["id"] == out["id"] and payload["status"] == "done"
    assert payload["answer"] == "Hello from agent-ada-1a2b." and payload["agent"]["name"] == "Ada"


@pytest.mark.parametrize("url", [
    "ftp://hooks.example.com/x", "hooks.example.com/x", "http://localhost/x",
    "http://tasks.internal/x", "http://open-webui.local/x"])
def test_a_callback_that_is_not_a_public_web_address_is_refused(client, wired, url):
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "Ada", "message": "hi", "callback_url": url},
                    headers=_auth(wired))
    assert r.status_code == 422, (url, r.text)
    assert wired["spawned"] == []


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.5", "172.17.0.2", "192.168.1.9",
                                  "169.254.169.254", "::1", "0.0.0.0"])
def test_a_callback_host_that_resolves_inside_is_refused(client, wired, monkeypatch, addr):
    monkeypatch.setattr(ra, "_resolve_seam", lambda host: [addr])
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "Ada", "message": "hi",
                          "callback_url": "https://hooks.example.com/run"},
                    headers=_auth(wired))
    assert r.status_code == 422 and "internet" in r.json()["detail"]


def test_a_callback_host_that_cannot_be_found_is_refused(client, wired, monkeypatch):
    def gone(host):
        raise OSError("no such host")
    monkeypatch.setattr(ra, "_resolve_seam", gone)
    r = client.post("/api/tasks/agents/run",
                    json={"agent": "Ada", "message": "hi",
                          "callback_url": "https://nowhere.example.com/run"},
                    headers=_auth(wired))
    assert r.status_code == 422


async def test_the_callback_is_retried_on_a_server_error_and_never_raises(monkeypatch):
    codes = iter([503, 200])

    class R:
        def __init__(self, code):
            self.status_code = code

    class Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return R(next(codes))

    monkeypatch.setattr(ra.httpx, "AsyncClient", Client)
    monkeypatch.setattr(ra.asyncio, "sleep", AsyncMock())
    assert await ra._post_callback("https://hooks.example.com/run", {"a": 1}) is True


# --- the key routes -------------------------------------------------------------

def test_keys_are_listed_made_shown_once_and_revoked(client, monkeypatch):
    rows = []

    async def create(email, label, key_hash, prefix):
        rows.append({"id": f"k{len(rows) + 1}", "label": label, "prefix": prefix,
                     "email": email, "hash": key_hash})
        return {k: v for k, v in rows[-1].items() if k not in ("email", "hash")}

    async def listing(email):
        return [{k: v for k, v in r.items() if k not in ("email", "hash")}
                for r in rows if r["email"] == email]

    async def revoke(email, key_id):
        return any(r["id"] == key_id and r["email"] == email for r in rows)

    monkeypatch.setattr(ak, "_create", create)
    monkeypatch.setattr(ak, "_list", listing)
    monkeypatch.setattr(ak, "_revoke", revoke)

    r = client.post("/api/tasks/agents/keys", json={"label": "n8n inbox"})
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["key"].startswith("iok_") and made["label"] == "n8n inbox"
    assert made["prefix"] == made["key"][:12]
    r = client.get("/api/tasks/agents/keys")
    assert r.json()["keys"] == [{"id": "k1", "label": "n8n inbox", "prefix": made["prefix"]}]
    assert "key" not in r.json()["keys"][0], "the key was shown again"
    assert client.delete("/api/tasks/agents/keys/k1").json() == {"revoked": True}
    assert client.delete("/api/tasks/agents/keys/k9").json() == {"revoked": False}


def test_the_key_limit_is_a_sentence_not_a_500(client, monkeypatch):
    monkeypatch.setattr(ak, "_create", AsyncMock(side_effect=ak.TooManyKeys()))
    r = client.post("/api/tasks/agents/keys", json={"label": "one more"})
    assert r.status_code == 409 and "Revoke one" in r.json()["detail"]


def test_the_key_routes_need_a_signed_in_person(wired):
    app = FastAPI()
    app.include_router(ra.router, prefix="/api/tasks")
    c = TestClient(app)
    assert c.get("/api/tasks/agents/keys").status_code == 401
    assert c.post("/api/tasks/agents/keys", json={"label": "x"}).status_code == 401
