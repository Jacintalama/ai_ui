"""Jev decides who handles a message to the whole team (agent_decider).

The answer the reader is tested against is the real one: a call made from
the server with the saved key on 2026-10-20 (HTTP 200, 0.28 s), pasted
verbatim. A fixture written from the docs could only prove what the docs
imagine; this one proves the reader reads what Jev actually sends.
"""
import asyncio
import json

import httpx
import pytest

import agent_decider as d

AVA = {"id": "agent-ava", "name": "Ava", "meta": {"role": "project manager"}}
DEV = {"id": "agent-dev", "name": "Dev", "meta": {"role": "developer"}}
VERA = {"id": "agent-vera", "name": "Vera",
        "meta": {"description": "researcher"}}
TEAM = [AVA, DEV, VERA]

REAL = json.loads(
    '{"model":"jev-1.13.0","answers":{"kind":{"type":"choice","choice":'
    '"answer","confidence":0.96,"probabilities":{"answer":0.98,"job":0.02}},'
    '"who":{"type":"choice","choice":"Dev","confidence":0.67,'
    '"probabilities":{"Ava":0.14,"Dev":0.78,"Vera":0.08}}},'
    '"usage":{"input_tokens":436,"output_tokens":68}}')


def _answer(kind, kc, who=None, wc=None, tokens=400):
    answers = {"kind": {"type": "choice", "choice": kind, "confidence": kc}}
    if who is not None:
        answers["who"] = {"type": "choice", "choice": who, "confidence": wc}
    return {"model": "jev-1.13.0", "answers": answers,
            "usage": {"input_tokens": tokens, "output_tokens": 60}}


# --- the request ------------------------------------------------------------

def test_the_request_asks_two_choice_questions_of_jev():
    body = d.build_request("can someone check how many apps I have?", [], TEAM)
    assert set(body["questions"]) == {"kind", "who"}
    kind = body["questions"]["kind"]
    assert kind["type"] == "choice"
    assert set(kind["criteria"]) == {"answer", "job"}
    who = body["questions"]["who"]
    assert who["type"] == "choice"
    assert who["criteria"] == {"Ava": "project manager", "Dev": "developer",
                               "Vera": "researcher"}


def test_the_state_holds_the_team_the_recent_lines_and_the_message():
    history = [{"role": "user", "content": "earlier question"},
               {"role": "assistant", "content": "earlier answer"},
               {"role": "user", "content": "check my apps please"}]
    state = d.build_request("check my apps please", history, TEAM)["state"]
    assert "Ava (project manager)" in state
    assert "earlier question" in state and "earlier answer" in state
    assert state.rstrip().endswith("check my apps please")
    # The message is the last line, not repeated from the history as well.
    assert state.count("check my apps please") == 1


def test_the_state_is_kept_short():
    history = [{"role": "user", "content": "x" * 5000}] * 20
    state = d.build_request("the message", history, TEAM)["state"]
    assert state.count("x" * 300) == d.HISTORY_LINES
    assert "x" * 301 not in state


def test_an_agent_with_no_role_is_a_team_member():
    body = d.build_request("hello there team", [],
                           [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}])
    assert body["questions"]["who"]["criteria"] == {"A": "team member",
                                                     "B": "team member"}


def test_two_agents_with_one_name_cannot_be_told_apart():
    twin = {"id": "agent-dev-2", "name": "Dev"}
    assert d.build_request("hello there team", [], TEAM + [twin]) is None


def test_the_model_is_pinned_to_the_version_the_cut_off_was_tuned_on(
        monkeypatch):
    # jev-latest is an alias TypeSafe moves to each new release, which would
    # change the answers under a cut-off measured on 1.13 (2026-10-21).
    monkeypatch.delenv("JEV_MODEL", raising=False)
    assert d.build_request("hello there team", [], TEAM)["model"] == \
        "jev-1.13.0"


def test_a_model_override_reaches_the_request(monkeypatch):
    monkeypatch.setenv("JEV_MODEL", "jev-preview")
    assert d.build_request("hello there team", [], TEAM)["model"] == \
        "jev-preview"


# --- reading the answer -----------------------------------------------------

def test_the_real_answer_is_not_sure_enough_who_should_answer(monkeypatch):
    monkeypatch.setenv("JEV_MIN_CONFIDENCE", "0.8")
    got = d.read_answer(REAL, TEAM)
    assert got.path == d.PATH_FALLBACK
    assert got.reason == "low confidence"
    assert got.kind == "answer" and got.kind_confidence == 0.96
    assert got.agent_id == "agent-dev" and got.agent_confidence == 0.67
    assert got.model == "jev-1.13.0" and got.input_tokens == 436


def test_the_real_answer_picks_dev_at_a_lower_bar(monkeypatch):
    monkeypatch.setenv("JEV_MIN_CONFIDENCE", "0.6")
    got = d.read_answer(REAL, TEAM)
    assert got.path == d.PATH_ONE_AGENT
    assert got.agent_id == "agent-dev"


def test_a_sure_job_goes_to_the_lead_for_a_plan(monkeypatch):
    monkeypatch.delenv("JEV_MIN_CONFIDENCE", raising=False)
    got = d.read_answer(_answer("job", 0.9, "Ava", 0.3), TEAM)
    assert got.path == d.PATH_PLAN


def test_a_sure_answer_by_a_sure_agent_is_one_agent(monkeypatch):
    monkeypatch.delenv("JEV_MIN_CONFIDENCE", raising=False)
    got = d.read_answer(_answer("answer", 0.9, "Vera", 0.85), TEAM)
    assert got.path == d.PATH_ONE_AGENT
    assert got.agent_id == "agent-vera"


def test_an_unsure_job_falls_back(monkeypatch):
    monkeypatch.delenv("JEV_MIN_CONFIDENCE", raising=False)
    got = d.read_answer(_answer("job", 0.7, "Ava", 0.9), TEAM)
    assert got.path == d.PATH_FALLBACK
    assert got.reason == "low confidence"


@pytest.mark.parametrize("data", [
    None, "text", {}, {"answers": {}},
    {"answers": {"kind": {"choice": "maybe", "confidence": 0.99}}},
    {"answers": {"kind": {"choice": "answer", "confidence": "high"}}},
    _answer("answer", 0.99, "Nobody", 0.99),
])
def test_an_answer_that_cannot_be_read_falls_back(data):
    got = d.read_answer(data, TEAM)
    assert got.path == d.PATH_FALLBACK
    assert got.reason == "unreadable answer"


def test_the_price_is_input_tokens_only():
    assert d.cost_usd(436) == pytest.approx(436 * 0.042 / 1_000_000)
    assert d.cost_usd(None) is None


# --- the call ---------------------------------------------------------------

@pytest.fixture
def seams(monkeypatch):
    """_post and record replaced; returns what each was called with."""
    calls = {"post": [], "record": []}
    state = {"reply": _answer("answer", 0.95, "Dev", 0.9), "error": None,
             "record_error": None}

    async def post(body, key):
        calls["post"].append((body, key))
        if state["error"] is not None:
            raise state["error"]
        return state["reply"]

    async def record(email, chat_id, decision):
        calls["record"].append((email, chat_id, decision))
        if state["record_error"] is not None:
            raise state["record_error"]

    monkeypatch.setattr(d, "_post", post)
    monkeypatch.setattr(d, "record", record)
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.delenv("JEV_MIN_CONFIDENCE", raising=False)
    return calls, state


async def test_no_key_means_no_call_and_no_record(seams, monkeypatch):
    calls, _ = seams
    monkeypatch.setenv("TYPESAFE_API_KEY", "  ")
    assert await d.decide("p@example.com", "chat-1", "hello there team",
                          [], TEAM) is None
    assert calls == {"post": [], "record": []}


async def test_a_decision_is_made_once_and_recorded_once(seams):
    calls, _ = seams
    got = await d.decide("p@example.com", "chat-1", "how many apps do I have",
                         [], TEAM)
    assert got.path == d.PATH_ONE_AGENT and got.agent_id == "agent-dev"
    assert got.ms >= 0 and got.input_tokens == 400
    assert len(calls["post"]) == 1
    body, key = calls["post"][0]
    assert key == "apikey_test" and body["questions"]["who"]
    assert calls["record"] == [("p@example.com", "chat-1", got)]


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"),
                                   asyncio.TimeoutError()])
async def test_a_slow_jev_is_a_recorded_fallback(seams, error):
    calls, state = seams
    state["error"] = error
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], TEAM)
    assert got.path == d.PATH_FALLBACK and got.reason == "timeout"
    assert len(calls["record"]) == 1


async def test_a_failing_jev_is_a_recorded_fallback(seams):
    calls, state = seams
    state["error"] = RuntimeError("HTTP 500")
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], TEAM)
    assert got.path == d.PATH_FALLBACK and got.reason == "error: RuntimeError"
    assert len(calls["record"]) == 1


async def test_a_record_that_fails_still_returns_the_decision(seams):
    _, state = seams
    state["record_error"] = RuntimeError("db down")
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], TEAM)
    assert got.path == d.PATH_ONE_AGENT


async def test_names_that_clash_are_a_fallback_without_a_call(seams):
    calls, _ = seams
    twin = {"id": "agent-dev-2", "name": "Dev"}
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], TEAM + [twin])
    assert got.path == d.PATH_FALLBACK and got.reason == "names not unique"
    assert calls["post"] == []
    assert len(calls["record"]) == 1


async def test_the_real_record_never_raises(monkeypatch):
    """record is bookkeeping beside a round that matters more: with no
    database at all it logs and returns."""
    import agent_decider
    import importlib
    importlib.reload(agent_decider)

    def broken_session():
        raise RuntimeError("no database")

    monkeypatch.setattr(agent_decider, "session", broken_session)
    await agent_decider.record("p@example.com", None,
                               agent_decider.Decision(path="fallback"))


# --- review fixes, 2026-10-20 -----------------------------------------------

def test_no_test_reaches_jev_unless_it_asks_to():
    """The container has the real key. A test that drives a team round and
    forgot to stub decide must not call TypeSafe or write a decision row."""
    import os
    assert "TYPESAFE_API_KEY" not in os.environ


@pytest.mark.parametrize("value, on", [(None, False), ("", False),
                                       ("   ", False), ("apikey_x", True)])
def test_jev_is_enabled_only_with_a_key(monkeypatch, value, on):
    if value is not None:
        monkeypatch.setenv("TYPESAFE_API_KEY", value)
    assert d.enabled() is on


async def test_too_few_named_agents_is_said_so(seams):
    calls, _ = seams
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], [DEV, {"id": "agent-x", "name": "  "}])
    assert got.path == d.PATH_FALLBACK
    assert got.reason == "too few named agents"
    assert calls["post"] == []


async def test_a_slow_record_does_not_hold_the_round(seams, monkeypatch):
    _, state = seams
    import time

    async def slow_record(email, chat_id, decision):
        await asyncio.sleep(5)

    monkeypatch.setattr(d, "record", slow_record)
    monkeypatch.setattr(d, "RECORD_TIMEOUT_SECONDS", 0.1)
    started = time.monotonic()
    got = await d.decide("p@example.com", None, "how many apps do I have",
                         [], TEAM)
    assert time.monotonic() - started < 1.0
    assert got.path == d.PATH_ONE_AGENT
