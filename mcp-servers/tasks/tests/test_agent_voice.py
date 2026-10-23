"""An agent's answer said out loud: what is read, who may ask, and what the
route does when the voice cannot be made.

Piper itself is never run here (the seam agent_voice._run is replaced). The
ASGI tests drive the real router, because a handler can be right and still
be unmounted."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import agent_voice
import routes_agents
from auth import current_user


# --- the words -----------------------------------------------------------------

def test_markdown_is_read_as_a_person_would_say_it():
    said = agent_voice.spoken_text(
        "## Done\n\n- **Two** invoices are due Friday.\n- See [the sheet](https://x.y/z) "
        "or https://example.com/a?b=c\n\n```python\nprint(1)\n```\n`inline` too | and | pipes")
    assert said.startswith("Done Two invoices are due Friday.")
    assert "**" not in said and "##" not in said and "](" not in said
    assert "the sheet" in said
    assert "https://" not in said and "a link" in said
    assert "print(1)" not in said and "code" in said
    assert "|" not in said


def test_nothing_but_marks_reads_as_nothing():
    assert agent_voice.spoken_text("```\n```\n\n---\n") == "code."
    assert agent_voice.spoken_text("   \n") == ""


def test_a_long_answer_is_capped_at_a_sentence_end():
    text = ("This is a sentence that goes on for a while. " * 30)
    said = agent_voice.spoken_text(text)
    assert len(said) <= agent_voice.MAX_CHARS
    assert said.endswith(".")
    assert not said.endswith(" .")


def test_a_cap_with_no_sentence_end_near_it_still_ends_in_a_full_stop():
    said = agent_voice.spoken_text("word " * 400)
    assert len(said) <= agent_voice.MAX_CHARS + 1
    assert said.endswith("word.")


def test_an_unknown_voice_falls_back_to_the_default():
    assert agent_voice.voice_or_default("ryan") == "ryan"
    assert agent_voice.voice_or_default("../etc/passwd") == "amy"
    assert agent_voice.voice_or_default(None) == "amy"


# --- the rate ------------------------------------------------------------------

def test_the_limit_is_per_person_per_minute():
    lim = agent_voice.RateLimit(per_minute=3)
    assert all(lim.allow("a@x", now=t) for t in (0, 1, 2))
    assert not lim.allow("a@x", now=3)
    assert lim.allow("b@x", now=3)
    # A minute on, the first three have aged out.
    assert lim.allow("a@x", now=61)


# --- the sound -----------------------------------------------------------------

async def test_no_model_is_a_voice_error_before_anything_is_spawned():
    async def never(model, text):
        raise AssertionError("piper must not run")
    with patch.object(agent_voice, "_run", never):
        with pytest.raises(agent_voice.VoiceError):
            await agent_voice.synthesize("Hello there.", "amy", exists=lambda p: False)


async def test_no_piper_binary_is_a_voice_error():
    async def never(model, text):
        raise AssertionError("piper must not run")
    with patch.object(agent_voice, "_run", never):
        with pytest.raises(agent_voice.VoiceError, match="piper is not installed"):
            await agent_voice.synthesize("Hello there.", "amy",
                                         exists=lambda p: p.endswith(".onnx"))


async def test_the_cleaned_words_and_the_voices_model_reach_piper():
    seen = {}
    async def fake(model, text):
        seen["model"], seen["text"] = model, text
        return b"RIFF" + b"\0" * 100
    with patch.object(agent_voice, "_run", fake):
        out = await agent_voice.synthesize("**Two** invoices", "ryan", exists=lambda p: True)
    assert out.startswith(b"RIFF")
    assert seen["text"] == "Two invoices"
    assert seen["model"].endswith("en_US-ryan-high.onnx")


# --- the route -----------------------------------------------------------------

class _User:
    email = "o@example.com"
    is_admin = False


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agents.router)
    app.dependency_overrides[current_user] = lambda: _User()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture(autouse=True)
def fresh_limit():
    with patch.object(agent_voice, "LIMIT", agent_voice.RateLimit()):
        yield


async def test_the_voices_are_listed_without_paths(client):
    async with client as c:
        r = await c.get("/agents/voice/voices")
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()["voices"]]
    assert ids == ["amy", "ryan", "lessac", "joe", "alan", "alba"]
    assert all("model" not in v and "/opt/" not in str(v) for v in r.json()["voices"])


async def test_a_sentence_comes_back_as_a_wav_in_the_voice_asked_for(client):
    async def fake(text, voice):
        assert text == "Two invoices are due Friday." and voice == "alba"
        return b"RIFF" + b"\0" * 40
    with patch.object(agent_voice, "synthesize", fake):
        async with client as c:
            r = await c.post("/agents/voice/say",
                             json={"text": "**Two** invoices are due Friday.", "voice": "alba"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.headers["x-voice"] == "alba"
    assert r.headers["cache-control"] == "no-store"
    assert r.content.startswith(b"RIFF")


async def test_nothing_to_say_and_an_unknown_voice_are_refused(client):
    async with client as c:
        empty = await c.post("/agents/voice/say", json={"text": "```\n```", "voice": ""})
        bad = await c.post("/agents/voice/say", json={"text": "Hello.", "voice": "nope"})
    assert empty.status_code == 400 or empty.json().get("detail")
    assert bad.status_code == 400


async def test_a_voice_that_cannot_be_made_is_a_503_not_a_crash(client):
    async def broken(text, voice):
        raise agent_voice.VoiceError("piper is not installed")
    with patch.object(agent_voice, "synthesize", broken):
        async with client as c:
            r = await c.post("/agents/voice/say", json={"text": "Hello there.", "voice": ""})
    assert r.status_code == 503


async def test_too_many_sentences_a_minute_is_a_429(client):
    async def fake(text, voice):
        return b"RIFF" + b"\0" * 40
    with patch.object(agent_voice, "LIMIT", agent_voice.RateLimit(per_minute=2)), \
         patch.object(agent_voice, "synthesize", fake):
        async with client as c:
            codes = [(await c.post("/agents/voice/say", json={"text": "Hi there.", "voice": ""})).status_code
                     for _ in range(3)]
    assert codes == [200, 200, 429]
