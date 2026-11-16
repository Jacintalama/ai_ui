"""When IO cannot be reached, the person is told, not quietly downgraded.

Measured on production 2026-11-16. A deploy restarted the tasks container
at 13:29:34. A message sent in that window:

    in my airtable AIUI Team table, add 2 rows: Test Member A, status
    Active, role Developer; ... Then list the rows back to me.

never reached the service at all, and was answered by a free model with
no tools:

    I haven't added those rows... I don't have the ability to modify
    Airtable in this reply... say it once more.

Nothing was wrong with the routing. The same wording scores
server:mcp-proxy 3 out of 3 against the live picker, well over the 0.75
cut. The service was simply not there for about twenty seconds, and
`_agents_first` returns None for that exactly as it returns None when IO
has decided nobody should answer. The pipe cannot tell those apart, so it
did the silent thing, and the person was told the platform cannot do
something it does perfectly well.

That is worse than a slow answer. It denies a capability at the moment
somebody asks for it, which is the same failure the Trello note caused in
October, arriving by a different road. It happens on EVERY deploy, to
everyone: four deploys went out the day this was found.

The distinction is already in the code and only needed using.
`_ask_streaming` returns `may_retry`, which is True only when the request
was never accepted, so nothing can have run. That, plus a one-shot POST
that also fails, is the one case where it is both TRUE and SAFE to say
the apps were out of reach.

The two cases that must stay silent are the point of the other tests
here:

  * IO answered and decided nobody should take it. Ordinary. Most
    messages. Saying anything would be noise on every greeting.
  * the stream was ACCEPTED and then failed. The turn may already have
    run, tools and all, so telling somebody their apps were unreachable
    could have them send the same email twice.
"""
import importlib.util
import json

import pytest

from conftest import repo_root_or_skip

PIPE_PATH = (repo_root_or_skip()
             / "open-webui-functions" / "auto_router_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("auto_router_pipe",
                                                  PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _q(text):
    return [{"role": "user", "content": text}]


def _emitter(into):
    async def emit(ev):
        into.append((ev["data"]["description"], ev["data"]["done"]))
    return emit


def _client(stream_raises=False, stream_lines=None, post=None):
    """An httpx-shaped client. `stream_raises` is a container that is not
    there: connection refused, which is what a restart looks like."""

    class Response:
        status_code = 200

        async def aiter_lines(self):
            for line in stream_lines or []:
                yield line

    class Stream:
        async def __aenter__(self):
            if stream_raises:
                raise OSError("connect call failed to tasks:8210")
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
            if post is None:
                raise OSError("connect call failed to tasks:8210")
            return post(url)

    return Client


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


AIRTABLE = ("in my airtable AIUI Team table, add 2 rows: Test Member A, "
            "status Active, role Developer. Then list the rows back to me.")


# --- the case that cost a real answer --------------------------------------

async def test_an_unreachable_service_is_said_out_loud(mod, monkeypatch):
    monkeypatch.setattr(mod.httpx, "AsyncClient", _client(stream_raises=True))
    said = []
    out = await mod.Pipe()._agents_first({"messages": _q(AIRTABLE)},
                                         "o@example.com", _emitter(said))
    assert out is None, "the free model still answers; it just says so"
    assert said, (
        "nothing was said. A person whose tools vanished for twenty "
        "seconds was told the platform cannot do something it can.")


async def test_what_it_says_is_about_the_apps_and_names_no_url(mod,
                                                               monkeypatch):
    monkeypatch.setattr(mod.httpx, "AsyncClient", _client(stream_raises=True))
    said = []
    await mod.Pipe()._agents_first({"messages": _q(AIRTABLE)},
                                   "o@example.com", _emitter(said))
    line = " ".join(text for text, _ in said).lower()
    assert "app" in line or "tool" in line, (
        "the line has to be about the thing that was lost: %r" % line)
    # An httpx error carries the URL and the internal host. Neither is the
    # person's business and one of them is an internal address.
    for leak in ("http://", "https://", "tasks:", "8210", "traceback"):
        assert leak not in line, "the line leaks %r: %r" % (leak, line)


# --- the cases that must stay silent ---------------------------------------

async def test_io_deciding_nobody_should_answer_says_nothing(mod,
                                                             monkeypatch):
    """The ordinary path for most messages. A line here would be noise on
    every greeting."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _client(
        stream_raises=True,
        post=lambda url: _Resp(200, {"turns": [], "rendered": ""})))
    said = []
    out = await mod.Pipe()._agents_first({"messages": _q("hello")},
                                         "o@example.com", _emitter(said))
    assert out is None
    assert said == [], (
        "IO was reached and said nobody should take it. That is not an "
        "outage and must not be announced: %r" % (said,))


async def test_a_turn_that_was_accepted_then_failed_says_nothing(
        mod, monkeypatch):
    """The stream was accepted, so the turn may already have run with its
    tools. Telling somebody their apps were unreachable could have them
    repeat an action that already happened."""
    monkeypatch.setattr(mod.httpx, "AsyncClient", _client(stream_lines=[
        "event: status",
        'data: {"line": "Reading your Airtable..."}',
        "",
        "event: error",
        'data: {"error": "boom"}',
        "",
    ]))
    said = []
    out = await mod.Pipe()._agents_first({"messages": _q(AIRTABLE)},
                                         "o@example.com", _emitter(said))
    assert out is None
    lines = [t for t, _ in said]
    assert "Reading your Airtable..." in lines, "the progress line is kept"
    unreachable = [t for t in lines
                   if "reach" in t.lower() or "without them" in t.lower()]
    assert unreachable == [], (
        "the turn was accepted and may have run; claiming the apps were "
        "out of reach invites a second send: %r" % (lines,))


async def test_a_working_turn_is_untouched(mod, monkeypatch):
    """The whole feature is a bonus on top of a working free model, so the
    ordinary success path must be exactly as it was."""
    reply = {"turns": [{"agent": None, "answer": "Added.", "notes": []}],
             "rendered": "Added.", "rendered_web": "Added.",
             "status": "Used your account and the web"}
    monkeypatch.setattr(mod.httpx, "AsyncClient", _client(stream_lines=[
        "event: reply", "data: " + json.dumps(reply), ""]))
    said = []
    out = await mod.Pipe()._agents_first({"messages": _q(AIRTABLE)},
                                         "o@example.com", _emitter(said))
    assert out[0] == "Added."
    assert out[1] == "Used your account and the web"
    assert [t for t, _ in said if "reach" in t.lower()] == []
