"""A free agent moving to the paid model inside one turn.

Every test drives agent_runner._chat with a fake _post_chat, the pattern in
test_agent_free_fallback.py. Nothing reaches a model, a database or a clock:
the daily count and the record of a move are AsyncMocks, and the sticky
window is cleared per test.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import agent_activity
import agent_escalation
import agent_runner

FREE = "nvidia/nemotron-3-super-120b-a12b:free"
POOL = [FREE, "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-mini:free"]


def _reply(content="ok", calls=None, usage=None):
    msg = {"content": content, "tool_calls": calls or None}
    body = {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}
    if usage is not None:
        body["usage"] = usage
    return body


def _call(name, cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def _http(status, detail="boom"):
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(status, json={"detail": detail}, request=req)
    return httpx.HTTPStatusError(str(status), request=req, response=resp)


def _agent(base=FREE):
    return {"id": "agent-1", "name": "Ada", "base_model_id": base,
            "params": {"system": "Be Ada."}}


class _AsyncNone:
    async def __call__(self):
        return None


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", list(POOL))
    monkeypatch.setattr(agent_runner, "FREE_REASONING", "none")
    monkeypatch.setattr(agent_runner, "_available_free_ids", _AsyncNone())
    monkeypatch.setattr(agent_escalation, "PAID_MODEL", "gpt-5.5")
    monkeypatch.setattr(agent_escalation, "PAID_REASONING", "low")
    monkeypatch.setattr(agent_escalation, "PAID_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(agent_escalation, "DAILY_CAP", 40)
    monkeypatch.setattr(agent_escalation, "PAID_EXTRA_ROUNDS", 3)
    monkeypatch.setattr(agent_escalation, "CONVERSATION_CHARS", 60000)
    monkeypatch.setattr(agent_escalation, "PRICES", {"gpt-5.5": (5.0, 30.0)})
    monkeypatch.setattr(agent_escalation, "_windows", {})
    monkeypatch.setattr(agent_escalation, "_noted", set())
    count = AsyncMock(return_value=0)
    marked = AsyncMock()
    monkeypatch.setattr(agent_activity, "paid_turns_today", count)
    monkeypatch.setattr(agent_activity, "mark_escalated", marked)
    return {"count": count, "marked": marked}


async def _run(fake_post, text="hi", *, agent=None, may_pass=False,
               follow_up=False, intent=True, tool=None, usage=None,
               max_iterations=7, timeout=60, messages=None, tool_mode="read_only"):
    intent_obj = (agent_escalation.Intent(person_text=text, may_pass=may_pass,
                                          follow_up=follow_up)
                  if intent else None)
    usage = usage if usage is not None else agent_escalation.TurnUsage(run_id="run-1")

    async def no_tool(*a, **k):
        return "tool ran"

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=tool or no_tool):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=messages or [{"role": "system", "content": "identity"},
                                  {"role": "user", "content": text}],
            tool_ids=["code"], user_email="ada@example.com",
            tool_mode=tool_mode, agent=agent or _agent(), intent=intent_obj,
            usage=usage, max_iterations=max_iterations, timeout=timeout)
    return answer, notes, usage


# --- up front ---------------------------------------------------------------

async def test_a_build_request_goes_to_the_paid_model_from_the_first_post(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append((payload, timeout))
        return _reply("built", usage={"prompt_tokens": 1000, "completion_tokens": 100})

    answer, _, usage = await _run(fake_post, "build me a todo app")

    assert answer == "built"
    payload, used_timeout = posts[0]
    assert payload["model"] == "gpt-5.5"
    assert payload["messages"][0] == {"role": "system", "content": "Be Ada."}
    assert payload["tool_ids"] == ["code"]
    assert payload["reasoning_effort"] == "low"
    assert used_timeout == 90
    assert usage.escalation == "build"
    assert usage.model == "gpt-5.5"
    assert usage.cost_usd == pytest.approx((1000 * 5 + 100 * 30) / 1_000_000)
    wired["marked"].assert_awaited_once_with("run-1", "build")


async def test_an_ordinary_question_stays_on_the_free_model(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("Standup at 9:30", usage={"prompt_tokens": 900, "completion_tokens": 20})

    answer, _, usage = await _run(fake_post, "what is on my calendar tomorrow?")

    assert answer == "Standup at 9:30"
    assert [p["model"] for p in posts] == ["agent-1"]
    assert posts[0]["reasoning_effort"] == "none"
    assert usage.escalation is None
    assert usage.model == FREE
    assert usage.cost_usd == 0.0
    wired["count"].assert_not_awaited()


async def test_no_intent_never_moves_which_is_what_the_summariser_relies_on(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("notes")

    await _run(fake_post, "build me a todo app", intent=False)
    assert [p["model"] for p in posts] == ["agent-1"]
    wired["count"].assert_not_awaited()


async def test_an_agent_on_a_paid_model_is_left_where_its_owner_put_it(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("done")

    await _run(fake_post, "build me a todo app", agent=_agent(base="gpt-4o-mini"))
    assert [p["model"] for p in posts] == ["agent-1"]
    wired["count"].assert_not_awaited()


async def test_blank_reasoning_sends_no_reasoning_on_the_paid_model(wired, monkeypatch):
    monkeypatch.setattr(agent_escalation, "PAID_REASONING", "")
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("built")

    await _run(fake_post, "build me a todo app")
    assert posts[0]["model"] == "gpt-5.5"
    assert "reasoning_effort" not in posts[0]


# --- the cap ----------------------------------------------------------------

async def test_at_the_cap_the_turn_stays_free_and_says_so_once_a_day(wired):
    wired["count"].return_value = 40
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("here is a start")

    first, _, usage = await _run(fake_post, "build me a todo app")
    second, _, _ = await _run(fake_post, "build me a todo app")

    assert [p["model"] for p in posts] == ["agent-1", "agent-1"]
    assert first == ("here is a start\n\nToday's limit of 40 turns on the "
                     "stronger model is used up, so this answer comes from "
                     "the free model.")
    assert second == "here is a start"
    assert usage.escalation is None
    wired["marked"].assert_not_awaited()


async def test_a_count_that_failed_stays_free_and_says_nothing(wired):
    wired["count"].return_value = None
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("here is a start")

    answer, _, _ = await _run(fake_post, "build me a todo app")
    assert answer == "here is a start"
    assert [p["model"] for p in posts] == ["agent-1"]


async def test_the_cap_note_is_never_added_to_a_pass_and_is_kept_for_an_answer(wired):
    """An unnamed agent whose first free reply takes the job asks to move,
    is refused at the cap, and then passes. The room drops a PASS, so a note
    on it would be lost, and the day's one note would be spent on nothing."""
    wired["count"].return_value = 40
    replies = [_reply("", calls=[_call("list_my_apps")]), _reply("PASS"),
               _reply("here is a start")]

    async def fake_post(payload, token, timeout=None):
        return replies.pop(0)

    passed, _, _ = await _run(fake_post, "build me a todo app", may_pass=True)
    answered, _, _ = await _run(fake_post, "build me a todo app")

    assert passed == "PASS"
    assert answered == ("here is a start\n\nToday's limit of 40 turns on the "
                        "stronger model is used up, so this answer comes from "
                        "the free model.")
    assert wired["count"].await_count == 2


#: A PASS in the shapes the room drops without drawing: a name label line in
#: front, bold or with a colon, and a routing pipe's footer after it.
LABELLED_PASSES = [
    "Ada:\n\nPASS",
    "**Ada**\n\nPASS",
    "PASS\n\n*Auto (Smart): routed to the paid general model `gpt-5.5`.*",
]


@pytest.mark.parametrize("said", LABELLED_PASSES)
async def test_a_labelled_pass_ends_the_turn_on_the_free_model(wired, said):
    """The room strips a leading "Ada:" before its PASS check. The loop
    did not, so this was re-asked on the paid model, spent a paid turn and
    opened the sticky window for an agent that said nothing (review,
    2026-09-18)."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply(said)

    answer, _, usage = await _run(fake_post, "build me a todo app", may_pass=True)
    assert answer == said
    assert [p["model"] for p in posts] == ["agent-1"]
    assert usage.escalation is None
    wired["count"].assert_not_awaited()
    assert not agent_escalation.in_window("ada@example.com", "agent-1")


@pytest.mark.parametrize("said", LABELLED_PASSES)
async def test_at_the_cap_a_labelled_pass_comes_back_without_the_cap_note(wired, said):
    wired["count"].return_value = 40
    replies = [_reply(said),
               _reply("", calls=[_call("list_my_apps")]), _reply(said)]

    async def fake_post(payload, token, timeout=None):
        return replies.pop(0)

    # Passing on the first reply, and passing after a refused move.
    first, _, _ = await _run(fake_post, "build me a todo app", may_pass=True)
    # The note is said once a day; forget it so the second run could say it.
    agent_escalation._noted.clear()
    after_refusal, _, _ = await _run(fake_post, "build me a todo app", may_pass=True)

    assert first == said
    assert after_refusal == said
    assert "Today's limit" not in first + after_refusal


async def test_a_labelled_pass_followed_by_an_answer_is_still_an_answer(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("Ada:\n\nPASS\n\nI read the files, I will build it.")
        return _reply("built it")

    answer, _, usage = await _run(fake_post, "build me a todo app", may_pass=True)
    assert answer == "built it"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert usage.escalation == "build"


# --- the room: decide on free first -----------------------------------------

async def test_an_unnamed_agent_that_passes_costs_nothing_paid(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("PASS")

    answer, _, usage = await _run(fake_post, "build me a todo app", may_pass=True)
    assert answer == "PASS"
    assert [p["model"] for p in posts] == ["agent-1"]
    assert usage.escalation is None
    wired["count"].assert_not_awaited()


async def test_an_unnamed_agent_that_takes_the_job_moves_before_any_tool_runs(wired):
    posts = []
    ran = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps")])
        return _reply("built it")

    async def tool(call, *a, **k):
        ran.append(call["function"]["name"])
        return "[]"

    answer, _, usage = await _run(fake_post, "build me a todo app",
                                  may_pass=True, tool=tool)
    assert answer == "built it"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert ran == []
    assert usage.escalation == "build"


# --- partway through --------------------------------------------------------

async def test_an_app_change_tool_moves_the_turn_and_no_tool_runs_twice(wired):
    posts = []
    ran = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("read_app_file", "r1")])
        if len(posts) == 2:
            return _reply("", calls=[_call("propose_app_change", "p1")])
        if len(posts) == 3:
            return _reply("", calls=[_call("propose_app_change", "p2")])
        return _reply("proposed")

    async def tool(call, *a, **k):
        ran.append(call["id"])
        return "result of " + call["id"]

    answer, _, usage = await _run(fake_post, "the header looks off",
                                  tool=tool)
    assert answer == "proposed"
    assert [p["model"] for p in posts] == ["agent-1", "agent-1", "gpt-5.5", "gpt-5.5"]
    # The read ran once on the free model; the free model's change was never
    # run; the paid model's change ran once.
    assert ran == ["r1", "p2"]
    carried = [m for m in posts[2]["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in carried] == ["r1"]
    assert usage.escalation == "heavy_tool"


async def test_an_empty_answer_is_asked_again_on_the_paid_model(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("")
        return _reply("a real answer")

    answer, _, usage = await _run(fake_post, "summarise my week")
    assert answer == "a real answer"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert usage.escalation == "empty_answer"


async def test_reasoning_with_no_answer_is_asked_again_on_the_paid_model(wired):
    """The design's other empty answer: the model thought and said nothing.
    The thinking is not an answer and is never shown."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {
                "content": None, "tool_calls": None,
                "reasoning_content": "The person wants a summary of"},
                "finish_reason": "length"}]}
        return _reply("a real answer")

    answer, _, usage = await _run(fake_post, "summarise my week")
    assert answer == "a real answer"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert usage.escalation == "empty_answer"


async def test_a_long_conversation_moves_before_the_post(wired, monkeypatch):
    monkeypatch.setattr(agent_escalation, "CONVERSATION_CHARS", 50)
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("ok")

    await _run(fake_post, "summarise " + "x" * 60)
    assert posts[0]["model"] == "gpt-5.5"


async def test_a_spent_pool_moves_to_paid_with_the_carried_conversation(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps", "l1")])
        if payload["model"] != "gpt-5.5":
            raise _http(400, "Provider returned error")
        return _reply("answered on paid")

    answer, _, usage = await _run(fake_post, "which of my apps is newest?")
    assert answer == "answered on paid"
    assert [p["model"] for p in posts] == [
        "agent-1", "agent-1", "nex-agi/nex-n2.5-pro:free",
        "nex-agi/nex-n2.5-mini:free", "gpt-5.5"]
    assert any(m.get("tool_call_id") == "l1" for m in posts[-1]["messages"])
    assert usage.escalation == "pool_spent"


async def test_a_paid_model_that_also_fails_after_a_spent_pool_is_the_busy_sentence(wired):
    async def fake_post(payload, token, timeout=None):
        raise _http(400, "Provider returned error")

    answer, _, _ = await _run(fake_post, "which of my apps is newest?")
    assert answer == agent_runner.FREE_POOL_EXHAUSTED


async def test_out_of_rounds_on_free_the_paid_model_gets_three_more(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5" and len(posts) >= 4:
            return _reply("finished on paid")
        return _reply("", calls=[_call("list_my_apps", "c%d" % len(posts))])

    answer, notes, usage = await _run(fake_post, "check my apps", max_iterations=2)
    assert answer == "finished on paid"
    assert [p["model"] for p in posts] == ["agent-1", "agent-1", "gpt-5.5", "gpt-5.5"]
    assert usage.escalation == "rounds_cap"
    assert notes == []


async def test_out_of_rounds_on_paid_too_says_how_many_rounds_in_total(wired):
    async def fake_post(payload, token, timeout=None):
        if payload.get("tool_ids") is None:
            return _reply("wrote it up")
        return _reply("", calls=[_call("list_my_apps")])

    answer, notes, _ = await _run(fake_post, "check my apps", max_iterations=2)
    assert answer == "wrote it up"
    assert notes == [agent_runner.RAN_OUT_OF_ROUNDS % 5]


async def test_a_paid_model_that_fails_in_its_extra_rounds_gives_the_free_model_none(wired):
    """The rounds added at the round cap are the paid model's. When it fails
    and the turn goes back to the free model, that model has spent its own
    rounds already, so its tool calls are not run and it writes up what it
    has (review of Task 7, 2026-09-17)."""
    posts = []
    ran = []

    async def fake_post(payload, token, timeout=None):
        writing_up = payload.get("tool_ids") is None
        posts.append(("write-up on " if writing_up else "") + payload["model"])
        if payload["model"] == "gpt-5.5":
            raise _http(500)
        if writing_up:
            return _reply("wrote it up")
        return _reply("", calls=[_call("list_my_apps", "c%d" % len(posts))])

    async def tool(call, *a, **k):
        ran.append(call["id"])
        return "[]"

    answer, notes, usage = await _run(fake_post, "check my apps",
                                      max_iterations=2, tool=tool)
    assert answer == "wrote it up"
    assert posts == ["agent-1", "agent-1", "gpt-5.5", "agent-1",
                     "write-up on agent-1"]
    assert ran == ["c1", "c2"]
    assert notes == [agent_runner.RAN_OUT_OF_ROUNDS % 2]
    assert usage.escalation == "rounds_cap"


async def test_a_failing_paid_model_goes_back_to_the_free_model_it_left(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5":
            raise _http(400, "Unsupported value: 'reasoning_effort'")
        return _reply("free answer")

    answer, _, usage = await _run(fake_post, "build me a todo app")
    assert answer == "free answer"
    assert [p["model"] for p in posts] == ["gpt-5.5", "agent-1"]
    assert posts[1]["reasoning_effort"] == "none"
    assert usage.escalation == "build"


@pytest.mark.parametrize("body", [b"<html>busy</html>", b"\x80 not utf-8"])
async def test_a_paid_reply_that_is_not_json_goes_back_to_the_free_model(wired, body):
    """A 200 whose body is not JSON, a proxy's page say, is an HTTP failure
    like any other. What the fake raises is what httpx itself raises from
    _post_chat's r.json() for that body: JSONDecodeError for the first,
    UnicodeDecodeError for the second, both ValueErrors."""
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload["model"])
        if payload["model"] == "gpt-5.5":
            return httpx.Response(200, content=body, request=req).json()
        return _reply("free answer")

    answer, _, _ = await _run(fake_post, "build me a todo app")
    assert answer == "free answer"
    assert posts == ["gpt-5.5", "agent-1"]


@pytest.mark.parametrize("status", [401, 403])
async def test_a_401_or_403_on_the_paid_model_is_raised_not_hidden(wired, status):
    """Only the paid post fails, so a loop that went back to the free model
    would answer instead of raising."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload["model"])
        if payload["model"] == "gpt-5.5":
            raise _http(status, "Not authenticated")
        return _reply("free answer")

    with pytest.raises(httpx.HTTPStatusError):
        await _run(fake_post, "build me a todo app")
    assert posts == ["gpt-5.5"]


async def test_it_moves_at_most_once_a_turn(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5":
            raise _http(500)
        if len(posts) == 2:
            return _reply("", calls=[_call("propose_app_change")])
        return _reply("free again")

    await _run(fake_post, "build me a todo app", max_iterations=3)
    assert wired["count"].await_count == 1
    assert [p["model"] for p in posts].count("gpt-5.5") == 1


# --- staying on it ----------------------------------------------------------

async def test_a_follow_up_stays_paid_and_a_plain_question_goes_back(wired):
    models = []

    async def fake_post(payload, token, timeout=None):
        models.append(payload["model"])
        return _reply("ok")

    await _run(fake_post, "build me a todo app")
    await _run(fake_post, "make it blue")
    await _run(fake_post, "what is on my calendar tomorrow?")
    await _run(fake_post, "", follow_up=True)
    assert models == ["gpt-5.5", "gpt-5.5", "agent-1", "gpt-5.5"]


async def test_a_move_whose_paid_model_only_failed_opens_no_window(wired):
    """Only a paid completion that answered opens the window. A move that
    went back to the free model leaves it closed: otherwise every later
    message moves again, waits out the paid timeout, goes back to free and
    uses a slot of the daily cap, and the window never closes while the
    person keeps typing (review of Task 7, 2026-09-17)."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append((payload["model"], timeout))
        if payload["model"] == "gpt-5.5":
            raise httpx.ReadTimeout("slow")
        return _reply("free answer")

    await _run(fake_post, "build me a todo app")
    assert not agent_escalation.in_window("ada@example.com", "agent-1")
    await _run(fake_post, "make it blue")
    await _run(fake_post, "and the footer too")

    assert posts == [("gpt-5.5", 90), ("agent-1", 60),
                     ("agent-1", 60), ("agent-1", 60)]
    assert wired["count"].await_count == 1
    wired["marked"].assert_awaited_once_with("run-1", "build")


async def test_usage_is_summed_over_every_completion_in_the_turn(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps")],
                          usage={"prompt_tokens": 1000, "completion_tokens": 100})
        return _reply("done", usage={"prompt_tokens": 1500, "completion_tokens": 200})

    _, _, usage = await _run(fake_post, "build me a todo app")
    assert (usage.prompt_tokens, usage.completion_tokens) == (2500, 300)
    assert usage.cost_usd == pytest.approx((2500 * 5 + 300 * 30) / 1_000_000)


async def test_a_turn_on_free_and_paid_records_the_paid_model_and_prices_only_paid(wired):
    """Free decides, paid answers once, paid fails, free writes the answer.
    The row said the free id, because it answered last, beside a cost that
    only the paid completion can have run up (review, 2026-09-18). The
    tokens stay totals of every completion; the cost is the paid ones."""
    posts = []
    free_use = {"prompt_tokens": 900, "completion_tokens": 20}
    paid_use = {"prompt_tokens": 1000, "completion_tokens": 100}

    async def fake_post(payload, token, timeout=None):
        posts.append(payload["model"])
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps", "c1")], usage=free_use)
        if len(posts) == 2:
            return _reply("", calls=[_call("list_my_apps", "c2")], usage=paid_use)
        if len(posts) == 3:
            raise _http(500)
        return _reply("done", usage={"prompt_tokens": 1200, "completion_tokens": 50})

    answer, _, usage = await _run(fake_post, "build me a todo app", may_pass=True)
    assert answer == "done"
    assert posts == ["agent-1", "gpt-5.5", "gpt-5.5", "agent-1"]
    assert usage.model == "gpt-5.5"
    assert (usage.prompt_tokens, usage.completion_tokens) == (3100, 170)
    assert usage.cost_usd == pytest.approx((1000 * 5 + 100 * 30) / 1_000_000)


# --- how long a turn can take -----------------------------------------------

async def _timeouts_of_a_turn_whose_write_up_fails(text, **kw):
    """Every post of one turn with the timeout it was given. Every round asks
    for a tool, so the turn spends all its rounds, and every write-up post
    times out, the paid one and each free id after it."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append((payload["model"], timeout))
        if payload.get("tool_ids") is None:
            raise httpx.ReadTimeout("slow")
        return _reply("", calls=[_call("list_my_apps", "c%d" % len(posts))])

    await _run(fake_post, text, **kw)
    return posts


@pytest.mark.parametrize("rounds, timeout", [(7, 60), (8, 240)])
async def test_a_turn_that_moves_at_the_round_cap_fits_inside_the_worst_turn(
        wired, rounds, timeout):
    """Walked post by post, each at its full timeout: every free round, the
    paid model's extra rounds, a paid write-up that times out, and the free
    write-up spending the whole pool. worst_turn_seconds sizes the token and
    the stale windows, so a path it leaves out is a working turn called dead
    or a token that expires under it. Its first version stopped at a paid
    write-up that answered (review, 2026-09-17)."""
    posts = await _timeouts_of_a_turn_whose_write_up_fails(
        "check my apps", max_iterations=rounds, timeout=timeout)

    write_up = max(timeout, agent_runner.FINAL_ROUND_MIN_TIMEOUT_SECONDS)
    assert posts == ([("agent-1", timeout)] * rounds
                     + [("gpt-5.5", max(timeout, 90))] * 3
                     + [("gpt-5.5", max(write_up, 90)), ("agent-1", write_up)]
                     + [(m, write_up) for m in POOL[1:]])
    assert sum(t for _, t in posts) <= agent_runner.worst_turn_seconds(
        rounds, timeout)


async def test_a_turn_that_moves_at_the_start_fits_inside_the_worst_turn(wired):
    """The other shape: an unnamed agent's free answer is set aside, every
    round goes to the paid model, and the write-up fails the same way."""
    posts = await _timeouts_of_a_turn_whose_write_up_fails(
        "build me a todo app", may_pass=True)

    assert posts == ([("agent-1", 60)] + [("gpt-5.5", 90)] * 7
                     + [("gpt-5.5", 120), ("agent-1", 120)]
                     + [(m, 120) for m in POOL[1:]])
    assert sum(t for _, t in posts) <= agent_runner.worst_turn_seconds(7, 60)
