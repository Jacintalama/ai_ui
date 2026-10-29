"""The pipe says what the service is doing, while it is still doing it.

The main chat went silent for the length of a turn. Measured live on
2026-10-29, right after the free-model pool was fixed: 9.5s for "check my
inbox" and 12.3s for a message with an attachment that an agent took, with
nothing on screen for any of it, against a 120s timeout.

The service now reports each step over /agents/chat/stream as it happens,
and these tests are the pipe's half: it says each line, it leaves the final
line to the service, and it still works against a service that has never
heard of the route.

It does NOT stream the answer, and that is deliberate rather than unfinished:
`agent_jev.reply_answers` can decide an agent's reply did not answer the
question, in which case the reply is discarded and the free model answers
instead. Text that might still be thrown away must not already be on the
person's screen.
"""
import importlib.util
import json
import pathlib

import pytest

from conftest import repo_root_or_skip

PIPE_PATH = (repo_root_or_skip()
             / "open-webui-functions" / "auto_router_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("auto_router_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _q(text):
    return [{"role": "user", "content": text}]


#: What the service sends back when the assistant read the person's mail.
REPLY = {"turns": [{"agent": None, "answer": "Two unread.", "notes": []}],
         "rendered": "Two unread.", "rendered_web": "Two unread.",
         "queue": [], "marker": "", "status": "Used your email"}


def _streaming(lines, on_post=None):
    """An httpx-shaped client that serves `lines` as an event stream.

    Its `post` fails the test by default: if the stream worked, reaching the
    one-shot route as well would mean the turn ran twice.
    """
    class Response:
        status_code = 200

        async def aiter_lines(self):
            for line in lines:
                yield line

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            return Stream()

        async def post(self, url, json=None, headers=None):
            if on_post is None:
                raise AssertionError("the stream worked; the POST is a bug")
            return on_post(url)

    return Client


def _emitter(into):
    async def emit(ev):
        into.append((ev["data"]["description"], ev["data"]["done"]))
    return emit


# --- the line arrives during the wait, which is the whole point --------------

async def test_each_line_is_said_as_it_arrives(mod, monkeypatch):
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: status",
        'data: {"line": "Reading your email..."}',
        "",
        "event: reply",
        "data: " + json.dumps(REPLY),
        "",
    ]))
    said = []
    p = mod.Pipe()
    out, status = await p._agents_first({"messages": _q("check my inbox")},
                                        "o@example.com", _emitter(said))
    assert out == "Two unread."
    assert said == [("Reading your email...", False)], (
        "the line must arrive un-done, while the turn is still running")
    assert status == "Used your email"


async def test_every_line_is_said_in_order(mod, monkeypatch):
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: status", 'data: {"line": "Mia is answering..."}', "",
        "event: status", 'data: {"line": "Reading your email..."}', "",
        "event: reply", "data: " + json.dumps(REPLY), "",
    ]))
    said = []
    p = mod.Pipe()
    await p._agents_first({"messages": _q("mia, check my inbox")},
                          "o@example.com", _emitter(said))
    assert [line for line, _done in said] == ["Mia is answering...",
                                              "Reading your email..."]


async def test_a_keepalive_or_a_blank_line_is_ignored(mod, monkeypatch):
    """sse_starlette sends pings, and SSE separates events with blank lines."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        ": ping", "",
        "event: status", 'data: {"line": "Mia is answering..."}', "",
        ": ping", "",
        "event: reply", "data: " + json.dumps(REPLY), "",
    ]))
    said = []
    p = mod.Pipe()
    out, _status = await p._agents_first({"messages": _q("hi mia")},
                                         "o@example.com", _emitter(said))
    assert out == "Two unread."
    assert [line for line, _ in said] == ["Mia is answering..."]


async def test_unreadable_data_does_not_take_the_turn_down(mod, monkeypatch):
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: status", "data: {not json at all", "",
        "event: reply", "data: " + json.dumps(REPLY), "",
    ]))
    p = mod.Pipe()
    out, _status = await p._agents_first({"messages": _q("check my inbox")},
                                         "o@example.com", None)
    assert out == "Two unread."


async def test_the_pipe_asks_the_stream_route_first(mod, monkeypatch):
    asked = []

    class Response:
        status_code = 200

        async def aiter_lines(self):
            yield "event: reply"
            yield "data: " + json.dumps(REPLY)

    class Stream:
        async def __aenter__(self): return Response()
        async def __aexit__(self, *a): return False

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        def stream(self, method, url, headers=None, json=None):
            asked.append((method, url))
            return Stream()

    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    p = mod.Pipe()
    await p._agents_first({"messages": _q("check my inbox")},
                          "o@example.com", None)
    assert asked == [("POST", "http://tasks:8210/agents/chat/stream")]


# --- the final line belongs to the service ------------------------------------

async def test_the_service_decides_the_line_left_on_screen(mod, monkeypatch):
    """Only the service knows whether a real agent spoke, the assistant read
    something, or neither. Guessing it in the pipe is what put "Answered by
    your agent" over an answer with no agent in it (2026-10-28)."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: reply",
        "data: " + json.dumps(dict(REPLY, status="Answered by Mia")), "",
    ]))
    p = mod.Pipe()
    _out, status = await p._agents_first({"messages": _q("hi mia")},
                                         "o@example.com", None)
    assert status == "Answered by Mia"


async def test_an_empty_status_stays_empty(mod, monkeypatch):
    """The assistant with no tools, or the free model: nothing happened
    worth reporting, and the pipe must not invent something."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: reply", "data: " + json.dumps(dict(REPLY, status="")), "",
    ]))
    p = mod.Pipe()
    _out, status = await p._agents_first({"messages": _q("hello there")},
                                         "o@example.com", None)
    assert status == ""


async def test_a_reply_with_no_status_key_falls_back_to_the_agent_name(
        mod, monkeypatch):
    """A service too old to send one. The line is still right."""
    older = {"turns": [{"agent": {"id": "a1", "name": "Ada"},
                        "answer": "Done.", "notes": []}],
             "rendered": "**Ada**\n\nDone.", "queue": [], "marker": ""}
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: reply", "data: " + json.dumps(older), "",
    ]))
    p = mod.Pipe()
    _out, status = await p._agents_first({"messages": _q("hi ada")},
                                         "o@example.com", None)
    assert status == "Answered by Ada"


# --- nothing here may cost the answer -----------------------------------------

async def test_an_error_event_leaves_it_to_the_free_model(mod, monkeypatch):
    """The agents are a bonus on top of a working free model, so a service
    failure costs the agents and never the answer."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: error", "data: {}", "",
    ]))
    p = mod.Pipe()
    assert await p._agents_first({"messages": _q("check my inbox")},
                                 "o@example.com", None) is None


async def test_a_service_without_the_stream_route_still_works(mod, monkeypatch):
    """The pipe is a database row and the service is a container, so they are
    never updated in the same instant. In whichever order that happens the
    chat keeps working: a 404 falls back to the one-shot POST, which is
    exactly the old behaviour, with no progress lines."""
    posted = []

    class Gone:
        status_code = 404

        async def aiter_lines(self):
            return
            yield                                   # pragma: no cover

    class Stream:
        async def __aenter__(self): return Gone()
        async def __aexit__(self, *a): return False

    class Plain:
        status_code = 200

        @staticmethod
        def json():
            return REPLY

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, method, url, headers=None, json=None): return Stream()

        async def post(self, url, json=None, headers=None):
            posted.append(url)
            return Plain()

    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    said = []
    p = mod.Pipe()
    out, status = await p._agents_first({"messages": _q("check my inbox")},
                                        "o@example.com", _emitter(said))
    assert out == "Two unread."
    assert status == "Used your email"
    assert posted and posted[0].endswith("/agents/chat")
    assert said == [], "there is nothing to report without the stream"


async def test_a_stream_that_breaks_midway_is_not_run_a_second_time(
        mod, monkeypatch):
    """A retried turn could send the same email twice. If the stream dies
    after the work may already have started, the pipe gives up rather than
    POSTing the same message again."""
    posted = []

    class Response:
        status_code = 200

        async def aiter_lines(self):
            yield "event: status"
            yield 'data: {"line": "Reading your email..."}'
            raise RuntimeError("connection reset by peer")

    class Stream:
        async def __aenter__(self): return Response()
        async def __aexit__(self, *a): return False

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, method, url, headers=None, json=None): return Stream()

        async def post(self, url, json=None, headers=None):
            posted.append(url)
            raise AssertionError("the turn must not be run a second time")

    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    p = mod.Pipe()
    assert await p._agents_first({"messages": _q("check my inbox")},
                                 "o@example.com", None) is None
    assert posted == []


async def test_an_emitter_that_throws_cannot_cost_the_answer(mod, monkeypatch):
    """Open WebUI's socket can go away mid-turn. The answer still arrives."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _streaming([
        "event: status", 'data: {"line": "Reading your email..."}', "",
        "event: reply", "data: " + json.dumps(REPLY), "",
    ]))

    async def emit(_ev):
        raise RuntimeError("the socket went away")

    p = mod.Pipe()
    answered = await p._agents_first({"messages": _q("check my inbox")},
                                     "o@example.com", emit)
    assert answered is not None, "a dead status socket cost the whole answer"
    assert answered[0] == "Two unread."
