"""An agent whose model changed must heal itself, and say why when it cannot.

Both of these come from one incident on 2026-09-08. Ralph's two agents were
switched to a different base model. Open WebUI keeps its model list in memory
and the chat route reads that, not the database, so every turn afterwards came
back 400 "Function not found: gpt-4o-mini". Opening the site in a browser
fixed it, because the page calls /api/models, which rebuilds the cache. The
tasks service never calls it, so a scheduled run at 3am would simply have
failed with nothing in the log to say why.

Two defects, tested separately:

  1. Nothing refreshed the cache, so the failure persisted until a human
     happened to load a page.
  2. _post_chat called raise_for_status(), which throws the response body
     away. The log held a stack trace and no reason. The one sentence that
     explained the whole thing never reached it, and finding it took four
     probes against production.
"""
import httpx
import pytest

import agent_runner


def _resp(status, body):
    return httpx.Response(status, json=body,
                          request=httpx.Request("POST", "http://owui/x"))


OK = {"choices": [{"message": {"content": "hello"}}]}
STALE = {"detail": "Function not found: gpt-4o-mini"}


def test_a_stale_model_cache_is_recognised():
    assert agent_runner._is_stale_model_cache(_resp(400, STALE))


@pytest.mark.parametrize("status,body", [
    (400, {"detail": "model not found"}),
    (400, {"detail": "messages: field required"}),
    (401, {"detail": "Function not found: x"}),
    (500, {"detail": "Function not found: x"}),
    (200, {"detail": "Function not found: x"}),
])
def test_nothing_else_is_mistaken_for_it(status, body):
    """The retry costs a whole extra completion, so it fires on this one
    signature and nothing near it. A 500 that happens to carry the words is
    the server being broken, not a cache being behind."""
    assert not agent_runner._is_stale_model_cache(_resp(status, body))


def test_a_response_with_no_json_body_does_not_blow_up():
    """Open WebUI is not the only thing that can answer this URL. A proxy or
    a gateway erroring returns HTML, and .json() on it raises."""
    r = httpx.Response(400, text="<html>Bad Gateway</html>",
                       request=httpx.Request("POST", "http://owui/x"))
    assert not agent_runner._is_stale_model_cache(r)


async def test_a_stale_cache_is_refreshed_and_the_turn_retried(monkeypatch):
    calls = []
    refreshed = []

    async def fake_post(client, payload, token):
        calls.append(payload)
        return _resp(400, STALE) if len(calls) == 1 else _resp(200, OK)

    async def fake_refresh(client, token):
        refreshed.append(token)

    monkeypatch.setattr(agent_runner, "_post_once", fake_post)
    monkeypatch.setattr(agent_runner, "_refresh_models", fake_refresh)

    out = await agent_runner._post_chat({"model": "agent-1"}, "tok")
    assert out == OK
    assert refreshed == ["tok"], "the model cache was never rebuilt"
    assert len(calls) == 2, "it did not try again after refreshing"


async def test_it_retries_once_and_not_forever(monkeypatch):
    """A model that genuinely does not exist returns this same 400 every
    time. Retrying on every attempt would double the cost of every failing
    turn and, in the loop above this, do it five times over."""
    calls = []

    async def always_stale(client, payload, token):
        calls.append(payload)
        return _resp(400, STALE)

    monkeypatch.setattr(agent_runner, "_post_once", always_stale)
    monkeypatch.setattr(agent_runner, "_refresh_models",
                        lambda client, token: _noop())

    with pytest.raises(httpx.HTTPStatusError):
        await agent_runner._post_chat({"model": "agent-1"}, "tok")
    assert len(calls) == 2


async def _noop():
    return None


async def test_a_refresh_that_itself_fails_does_not_hide_the_real_error(
        monkeypatch):
    """The refresh is a repair attempt, not the job. If it fails the caller
    still has to see the completion's own failure, not an error from the
    thing that was trying to help."""
    async def always_stale(client, payload, token):
        return _resp(400, STALE)

    async def broken_refresh(client, token):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(agent_runner, "_post_once", always_stale)
    monkeypatch.setattr(agent_runner, "_refresh_models", broken_refresh)

    with pytest.raises(httpx.HTTPStatusError):
        await agent_runner._post_chat({"model": "agent-1"}, "tok")


async def test_a_healthy_turn_makes_exactly_one_request(monkeypatch):
    """The overwhelmingly common case. Nothing added here may cost a second
    completion when the first one worked."""
    calls = []

    async def fine(client, payload, token):
        calls.append(payload)
        return _resp(200, OK)

    refreshed = []
    monkeypatch.setattr(agent_runner, "_post_once", fine)
    monkeypatch.setattr(agent_runner, "_refresh_models",
                        lambda c, t: refreshed.append(t) or _noop())

    assert await agent_runner._post_chat({"model": "m"}, "tok") == OK
    assert len(calls) == 1
    assert refreshed == []


async def test_the_reason_reaches_the_log(monkeypatch, caplog):
    """The whole point of the second fix. raise_for_status still raises, so
    every caller behaves as before, but the body is written down first."""
    async def bad(client, payload, token):
        return _resp(400, {"detail": "messages: field required"})

    monkeypatch.setattr(agent_runner, "_post_once", bad)
    monkeypatch.setattr(agent_runner, "_refresh_models", lambda c, t: _noop())

    with caplog.at_level("ERROR"):
        with pytest.raises(httpx.HTTPStatusError):
            await agent_runner._post_chat({"model": "m"}, "tok")
    assert "messages: field required" in caplog.text


async def test_the_token_is_never_written_to_the_log(monkeypatch, caplog):
    """This project has already leaked a token through an error that carried
    a URL. The body is Open WebUI's own words and is safe; the token is not,
    and must not arrive in the log by some other route."""
    async def bad(client, payload, token):
        return _resp(400, {"detail": "nope"})

    monkeypatch.setattr(agent_runner, "_post_once", bad)
    monkeypatch.setattr(agent_runner, "_refresh_models", lambda c, t: _noop())

    with caplog.at_level("ERROR"):
        with pytest.raises(httpx.HTTPStatusError):
            await agent_runner._post_chat({"model": "m"}, "sekrit-token")
    assert "sekrit-token" not in caplog.text


# --- the free router answering 200 with a failure ---------------------------

# Ralph set Ada to Auto (Free) and she stopped replying. Every OpenRouter
# model works, with and without tools; the free ROUTER is a lottery across
# models that are constantly rate limited, and it reports that by returning
# HTTP 200 with an error sentence as the assistant's content. Nothing
# downstream can tell that from an answer, which is why the same cause showed
# sometimes as raw router text and sometimes as "could not answer".

ROUTER_FAIL = ("[auto-router] every free model was rate-limited or failed. "
               "Last: google/gemma-4-26b-a4b-it:free -> 429: {\"error\": ...}")


def test_the_routers_own_failure_is_recognised():
    assert agent_runner._router_gave_up(ROUTER_FAIL)


def test_a_normal_answer_is_not_mistaken_for_it():
    for ok in ("OK.", "", "Here are your unread emails:",
               "I could not reach the rate-limited service you asked about",
               "[auto-router] routed to nvidia/nemotron-3-super-120b-a12b:free"):
        assert not agent_runner._router_gave_up(ok), ok


def test_a_non_string_answer_does_not_blow_up():
    for junk in (None, 5, [], {}):
        assert not agent_runner._router_gave_up(junk)


async def test_an_exhausted_router_answers_in_words_a_person_can_act_on(
        monkeypatch):
    """The raw text names a model nobody chose and a status code. The person
    needs to know it is their model setting and that changing it fixes it."""
    async def router_failed(payload, token, timeout=None):
        return {"choices": [{"message": {"content": ROUTER_FAIL}}]}

    monkeypatch.setattr(agent_runner, "_post_chat", router_failed)
    answer, notes = await agent_runner._chat(
        token="t", model="agent-1", messages=[{"role": "user", "content": "hi"}],
        tool_ids=None, user_email="who@example.com", tool_mode="read_only")
    low = (answer + " ".join(notes)).lower()
    assert "free" in low
    assert "model" in low
    assert "429" not in low, "the status code helps nobody"
    assert "gemma" not in low, "it names a model they never chose"


async def test_a_working_router_answer_is_left_alone(monkeypatch):
    """It succeeds most of the time, and its footer saying which model it
    picked is genuinely useful."""
    good = "OK.\n\n*Auto-routed to the free general model `nemotron`.*"

    async def router_ok(payload, token, timeout=None):
        return {"choices": [{"message": {"content": good}}]}

    monkeypatch.setattr(agent_runner, "_post_chat", router_ok)
    answer, _notes = await agent_runner._chat(
        token="t", model="agent-1", messages=[{"role": "user", "content": "hi"}],
        tool_ids=None, user_email="who@example.com", tool_mode="read_only")
    assert answer == good
