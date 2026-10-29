"""A picture sent to the agents is seen, not only described (2026-10-29).

Until now a picture became a description before the message was posted: one
call to the vision model, about seven seconds with the Send button doing
nothing, and the agents read what that model had written rather than the
picture. Now:

- the send goes at once; the description is written while the agents answer
  and replaces a placeholder in the stored message, for the turns after this
  one, for the agents that cannot see, and for the record;
- on the round that answers it, every agent whose model can see is handed
  the picture itself, on that one message only, never on a later turn;
- a model that cannot see (the free fallback glm-4.7-flash) is handed the
  words alone, so a fallback cannot fail on an image it cannot read;
- a message queued behind a running round keeps its preview once answered;
- a held approval does not carry the picture's bytes into the database.
"""
import asyncio
import importlib
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_attach
import agent_runner

EMAIL = "seer@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
PNG = b"\x89PNG\r\n\x1a\nfake"
THUMB = "data:image/jpeg;base64,QUJD"


class _User:
    email = EMAIL


class _Upload:
    def __init__(self, name, data, ctype=""):
        self.filename, self.content_type, self._data = name, ctype, data

    async def read(self, n=-1):
        return self._data if n < 0 else self._data[:n]


@pytest.fixture
def chat(monkeypatch):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)
    saved = []

    async def noop_create(email, title, s, agent_id=None):
        return "chat-1"

    async def save(email, s):
        saved.append([dict(m) for m in s.messages])

    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", save)
    routes_agent_chat.saved = saved
    yield routes_agent_chat
    agent_chat_store._SESSIONS.clear()


async def _until(check, seconds=2.0):
    for _ in range(int(seconds / 0.01)):
        if check():
            return True
        await asyncio.sleep(0.01)
    return False


# --- the send ---------------------------------------------------------------

async def test_a_picture_is_sent_without_waiting_for_its_description(chat, monkeypatch):
    looked = asyncio.Event()
    release = asyncio.Event()

    async def slow_eyes(email, url):
        looked.set()
        await release.wait()
        return "A whiteboard. It says: launch on Friday."

    monkeypatch.setattr(agent_attach, "_see", slow_eyes)
    # The eyes never answer until released below, so a send that waited on
    # them would hit this limit. Generous, because loading the conversation
    # tries a database that is not there and Windows takes a while to say so.
    out = await asyncio.wait_for(
        chat.agent_chat_send(message="what does this say", agent="",
                             files=[_Upload("board.png", PNG, "image/png")],
                             thumbs='{"board.png": "%s"}' % THUMB, user=_User()),
        timeout=10.0)
    assert "board.png" in out.body.decode()
    s = chat.store.get_session(EMAIL)
    said = s.messages[-1]
    assert said["content"].startswith("what does this say\n\n[Attached by the person: board.png (picture).")
    assert "launch on Friday" not in said["content"]
    assert said["attached"] == [{"name": "board.png", "kind": "image", "thumb": THUMB}]
    # The description is under way, and lands in the stored message.
    assert await _until(looked.is_set)
    release.set()
    assert await _until(lambda: "launch on Friday" in s.messages[-1]["content"])
    assert agent_attach.PENDING not in s.messages[-1]["content"]
    # The bubble is drawn from the same message, and still shows only words.
    assert agent_attach.split(s.messages[-1]["content"])[0] == "what does this say"


async def test_a_description_that_fails_is_said_in_the_message_not_refused(chat, monkeypatch):
    async def blind(email, url):
        raise RuntimeError("provider down")

    monkeypatch.setattr(agent_attach, "_see", blind)
    await chat.agent_chat_send(message="look", agent="",
                               files=[_Upload("a.png", PNG, "image/png")],
                               thumbs="", user=_User())
    s = chat.store.get_session(EMAIL)
    assert await _until(lambda: agent_attach.PENDING not in s.messages[-1]["content"])
    assert agent_attach.UNDESCRIBED in s.messages[-1]["content"]


async def test_the_description_is_saved_once_it_lands(chat, monkeypatch):
    async def eyes(email, url):
        return "A receipt for 42 euros."

    monkeypatch.setattr(agent_attach, "_see", eyes)
    await chat.agent_chat_send(message="", agent="",
                               files=[_Upload("r.png", PNG, "image/png")],
                               thumbs="", user=_User())
    s = chat.store.get_session(EMAIL)
    # Nobody has streamed the round yet, so nothing else will save it.
    s.streaming = False
    assert await _until(lambda: any("42 euros" in str(m) for snap in chat.saved for m in snap))


async def test_two_pictures_are_described_side_by_side(chat, monkeypatch):
    running = []
    most = []

    async def eyes(email, url):
        running.append(url)
        most.append(len(running))
        await asyncio.sleep(0.05)
        running.pop()
        return "a picture"

    monkeypatch.setattr(agent_attach, "_see", eyes)
    await chat.agent_chat_send(message="both", agent="",
                               files=[_Upload("a.png", PNG, "image/png"),
                                      _Upload("b.png", PNG + b"2", "image/png")],
                               thumbs="", user=_User())
    s = chat.store.get_session(EMAIL)
    assert await _until(lambda: agent_attach.PENDING not in s.messages[-1]["content"])
    assert max(most) == 2


# --- the round --------------------------------------------------------------

def _app(monkeypatch, chat_mod, seen):
    async def turn(email, agent, messages, names=(), **kw):
        seen.append([dict(m) for m in messages])
        return {"answer": "I see it", "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return [ADA]

    async def no_graph(email, question=""):
        return ""

    async def eyes(email, url):
        return "A whiteboard."

    monkeypatch.setattr(chat_mod, "_agents_for", agents_for)
    monkeypatch.setattr(chat_mod, "_turn_for", turn)
    monkeypatch.setattr(chat_mod.agent_graph, "graph_block", no_graph)
    monkeypatch.setattr(agent_attach, "_see", eyes)
    app = FastAPI()
    app.include_router(chat_mod.router)
    return TestClient(app)


def _parts(message):
    content = message["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def test_the_agent_answering_is_handed_the_picture_itself(chat, monkeypatch):
    seen = []
    c = _app(monkeypatch, chat, seen)
    hdr = {"X-User-Email": EMAIL}
    c.post("/tasks/agents/chat/send", data={"message": "what is this", "agent": "agent-a"},
           files={"files": ("board.png", PNG, "image/png")}, headers=hdr)
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=hdr)
    newest = [m for m in seen[0] if m.get("role") == "user"][-1]
    parts = _parts(newest)
    images = [p for p in parts if p.get("type") == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert any("what is this" in p.get("text", "") for p in parts if p.get("type") == "text")
    # Its bytes stay out of what is kept.
    s = chat.store.get_session(EMAIL, "agent-a")
    assert all(isinstance(m.get("content"), str) for m in s.messages)
    assert not any("base64" in str(m.get("content")) for m in s.messages)


def test_a_later_turn_reads_the_description_not_the_picture(chat, monkeypatch):
    seen = []
    c = _app(monkeypatch, chat, seen)
    hdr = {"X-User-Email": EMAIL}
    c.post("/tasks/agents/chat/send", data={"message": "what is this", "agent": "agent-a"},
           files={"files": ("board.png", PNG, "image/png")}, headers=hdr)
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=hdr)
    c.post("/tasks/agents/chat/send", data={"message": "and again?", "agent": "agent-a"},
           headers=hdr)
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=hdr)
    later = seen[1]
    assert not any(p.get("type") == "image_url" for m in later for p in _parts(m))
    assert any("A whiteboard." in p.get("text", "") for m in later for p in _parts(m))


def test_a_picture_queued_behind_a_round_keeps_its_preview(chat, monkeypatch):
    seen = []
    c = _app(monkeypatch, chat, seen)
    hdr = {"X-User-Email": EMAIL}
    c.post("/tasks/agents/chat/send", data={"message": "first", "agent": "agent-a"},
           headers=hdr)
    # The round for "first" has not run yet, so this one queues behind it.
    c.post("/tasks/agents/chat/send",
           data={"message": "and this", "agent": "agent-a",
                 "thumbs": '{"board.png": "%s"}' % THUMB},
           files={"files": ("board.png", PNG, "image/png")}, headers=hdr)
    s = chat.store.get_session(EMAIL, "agent-a")
    assert s.queued
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=hdr)
    queued_turn = [m for m in s.messages if m.get("role") == "user"][-1]
    assert queued_turn["content"].startswith("and this")
    assert queued_turn.get("attached") == [{"name": "board.png", "kind": "image", "thumb": THUMB}]
    # And it was answered with the picture in front of the agent.
    assert any(p.get("type") == "image_url"
               for p in _parts([m for m in seen[-1] if m.get("role") == "user"][-1]))


# --- the runner -------------------------------------------------------------

def _reply(content="ok"):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


PICTURE = [{"role": "user", "content": [
    {"type": "text", "text": "what is this\n\n[Attached by the person: a.png (picture). ...]"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]}]


async def _posted(agent, fail_first=False, monkeypatch=None):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if fail_first and len(posts) == 1:
            import httpx
            req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
            resp = httpx.Response(400, json={"detail": "Provider returned error"}, request=req)
            raise httpx.HTTPStatusError("400", request=req, response=resp)
        return _reply()

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(token="t", model=agent["id"], messages=list(PICTURE),
                                 tool_ids=None, user_email="o@example.com",
                                 tool_mode="read_only", agent=agent)
    return posts


def _user_content(payload):
    return [m for m in payload["messages"] if m["role"] == "user"][-1]["content"]


async def test_a_model_that_can_see_is_posted_the_picture():
    agent = {"id": "agent-1", "name": "Ada", "base_model_id": "z-ai/glm-5.3-flash",
             "params": {"system": "Be Ada."}}
    posts = await _posted(agent)
    content = _user_content(posts[0])
    assert isinstance(content, list)
    assert any(p.get("type") == "image_url" for p in content)


async def test_a_model_that_cannot_see_is_posted_the_words_alone():
    agent = {"id": "agent-1", "name": "Ada", "base_model_id": "z-ai/glm-4.7-flash",
             "params": {"system": "Be Ada."}}
    posts = await _posted(agent)
    content = _user_content(posts[0])
    assert isinstance(content, str)
    assert content.startswith("what is this")
    assert "base64" not in content


async def test_a_fallback_that_cannot_see_is_posted_the_words_alone(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", ["z-ai/glm-5.3-flash", "z-ai/glm-4.7-flash"])
    monkeypatch.setattr(agent_runner, "FREE_REASONING", "minimal")

    async def every_id():
        return None

    monkeypatch.setattr(agent_runner, "_available_free_ids", every_id)
    agent = {"id": "agent-1", "name": "Ada", "base_model_id": "z-ai/glm-5.3-flash",
             "params": {"system": "Be Ada."}}
    posts = await _posted(agent, fail_first=True)
    assert isinstance(_user_content(posts[0]), list)
    assert posts[1]["model"] == "z-ai/glm-4.7-flash"
    assert isinstance(_user_content(posts[1]), str)


# --- a held approval --------------------------------------------------------

def test_a_held_conversation_keeps_no_picture_bytes():
    import routes_agent_turn
    kept = routes_agent_turn._trim_for_storage(list(PICTURE))
    assert isinstance(kept[0]["content"], str)
    assert kept[0]["content"].startswith("what is this")
    assert "base64" not in kept[0]["content"]
