"""The lead's triage call: one free, tool-less completion, and a plan or None.

The model and the agent lookup are patched on the module, the same seams the
summariser's tests use. Every path but a good plan must come back None, and
None means the round runs as it does today.
"""
import asyncio
import json

import pytest

import agent_access
import agent_job_triage as triage
from agent_runner import FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED

pytestmark = pytest.mark.asyncio

ROSTER = [{"id": "agent-mia", "name": "Mia", "meta": {"role": "Researcher"}},
          {"id": "agent-ada", "name": "Ada", "meta": {"role": "Analyst"}},
          {"id": "agent-pat", "name": "Pat", "meta": {"role": "Manager"}}]
LEAD = ROSTER[2]
HISTORY = [{"role": "user", "content": "find the reports and compare them"}]

PLAN = json.dumps({"kind": "job", "steps": [
    {"agent": "Mia", "do": "Find the reports."},
    {"agent": "Ada", "do": "Compare them."}]})


@pytest.fixture
def model(monkeypatch):
    """Patch the lookup and the model. `answer` is what the model says, or an
    exception to raise; every call's keyword arguments are kept."""
    state = {"answer": PLAN, "calls": [], "resolved": []}

    async def fake_resolve(email, agent_id):
        state["resolved"].append((email, agent_id))
        return "tok", ["tool-a"], "all"

    async def fake_chat(**kwargs):
        state["calls"].append(kwargs)
        answer = state["answer"]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer()
        return answer, []

    monkeypatch.setattr(triage, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(triage, "_chat", fake_chat)
    return state


async def test_a_plan_answer_becomes_steps(model):
    steps = await triage.triage("a@example.com", LEAD, ROSTER, HISTORY)
    assert steps == [{"agent_id": "agent-mia", "task": "Find the reports."},
                     {"agent_id": "agent-ada", "task": "Compare them."}]
    assert model["resolved"] == [("a@example.com", "agent-pat")]


async def test_an_answer_object_means_no_job(model):
    model["answer"] = '{"kind": "answer"}'
    assert await triage.triage("a@example.com", LEAD, ROSTER, HISTORY) is None


async def test_a_model_that_raises_means_no_job(model):
    model["answer"] = RuntimeError("provider down")
    assert await triage.triage("a@example.com", LEAD, ROSTER, HISTORY) is None


async def test_a_lookup_that_raises_means_no_job(model, monkeypatch):
    async def broken(email, agent_id):
        raise RuntimeError("no token")
    monkeypatch.setattr(triage, "_resolve_agent", broken)
    assert await triage.triage("a@example.com", LEAD, ROSTER, HISTORY) is None


async def test_a_slow_model_means_no_job(model, monkeypatch):
    monkeypatch.setattr(triage, "TRIAGE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(triage, "TRIAGE_GRACE_SECONDS", 0.05)

    async def slow():
        await asyncio.sleep(5)
        return PLAN, []

    model["answer"] = slow
    loop = asyncio.get_running_loop()
    began = loop.time()
    assert await triage.triage("a@example.com", LEAD, ROSTER, HISTORY) is None
    assert loop.time() - began < 2


async def test_a_busy_sentence_means_no_job(model):
    for busy in (FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED):
        model["answer"] = busy
        assert await triage.triage("a@example.com", LEAD, ROSTER,
                                   HISTORY) is None


async def test_no_lead_or_no_team_means_no_job(model):
    assert await triage.triage("a@example.com", None, ROSTER, HISTORY) is None
    assert await triage.triage("a@example.com", LEAD, [], HISTORY) is None
    assert model["calls"] == []


async def test_the_instruction_carries_the_marker_and_the_names(model):
    await triage.triage("a@example.com", LEAD, ROSTER, HISTORY)
    messages = model["calls"][0]["messages"]
    assert messages[:-1] == HISTORY, "the conversation comes first, unchanged"
    last = messages[-1]
    assert last["role"] == "user"
    assert last["content"].startswith(triage.TRIAGE_MARKER)
    for name in ("Mia", "Ada", "Pat"):
        assert name in last["content"]
    assert '{"kind": "answer"}' in last["content"]


async def test_the_history_passed_in_is_not_changed(model):
    history = list(HISTORY)
    await triage.triage("a@example.com", LEAD, ROSTER, history)
    assert history == HISTORY


async def test_tools_are_off_and_the_paid_model_is_out_of_reach(model):
    await triage.triage("a@example.com", LEAD, ROSTER, HISTORY)
    call = model["calls"][0]
    assert call["tool_ids"] is None
    assert call["tool_mode"] == agent_access.MODE_READ_ONLY
    assert call["refusal_reason"]
    assert call["max_iterations"] == 1
    assert call["timeout"] == triage.TRIAGE_TIMEOUT_SECONDS
    assert "intent" in call and call["intent"] is None
    assert call["model"] == "agent-pat" and call["agent"] is LEAD
    assert call["user_email"] == "a@example.com"
    assert call["token"] == "tok"
