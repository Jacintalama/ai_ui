"""A proxy tool that fails says which tool failed, and what was wrong.

Measured on production 2026-11-09, as Ralph's own agent `cronss`, which is
at `all` access and holds the connected-apps tool, so nothing about
permissions is involved:

    asked for my-clickup_create_taskk ->
      There is no tool called call_tool. Its name may have changed. To find
      the right one, call search_tools with what you are trying to do, then
      call_tool to run what it returns.

    asked for my-clickup_create_task (no arguments) ->
      The tool call_tool could not be run this time.

Both sentences are about `call_tool`, which is the generic runner every
proxy tool goes through, not the tool that failed. Two separate harms:

1. The recovery sentence from PR #148 is unusable for the ~200 tools it
   was written for. It tells the model to look up `call_tool`, which is
   not renamed, is not missing, and which `search_tools` deliberately
   never returns (see PROXY_META_METHODS). So a renamed ClickUp tool
   still ends in the retry loop that PR was meant to break.

2. The second call was refused with HTTP 422 and a body that named
   exactly what was wrong:

       loc ["body","list_id"]  type missing
       loc ["body","name"]     type missing

   All of it was dropped. The model cannot fix a call when it is not told
   what was wrong with it, so one forgotten argument ends the attempt and
   the owner is told the agent could not create anything.

`is_write_call` has read the inner `tool_name` since PR #147. These
sentences never did.

The old test for this (test_a_missing_tool_says_how_to_recover) formats
NO_SUCH_TOOL by hand with the right name, so it passed throughout. These
assert what the runner actually substitutes.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import agent_tools as T
from agent_tools import execute_tool_call

WRAPPED = "my-clickup_create_task"


def _call(name, args=None):
    return {"id": "c1", "function": {"name": name,
                                     "arguments": json.dumps(args or {})}}


def _wrapped(tool_name, args=None):
    return _call("call_tool", {"tool_name": tool_name,
                               "arguments": args or {}})


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _proxy_says(status, payload):
    async def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp(status, payload)
    return fake_post


async def _run(call, status, payload):
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json", new=_proxy_says(status, payload)):
        return await execute_tool_call(call, "owner@example.com")


def _validation_body(fields, server="my-clickup", extra=None):
    """The shape mcp-proxy really returns: its own sentence with the
    server's JSON body appended as a string."""
    inner = {"detail": [dict({"type": "missing",
                              "loc": ["body", f],
                              "msg": "Field required",
                              "input": {}}, **(extra or {}))
                        for f in fields]}
    return {"detail": "Server %s returned: %s" % (server, json.dumps(inner))}


# --------------------------------------------------------------- the name

async def test_a_missing_proxy_tool_is_named_in_the_sentence():
    out = await _run(_wrapped("my-clickup_create_taskk"), 404,
                     {"detail": "not found"})
    assert "my-clickup_create_taskk" in out, out


async def test_a_missing_proxy_tool_is_not_reported_as_call_tool():
    """The whole sentence exists to be acted on. Naming the runner sends
    the model to look up a tool that search_tools never returns."""
    out = await _run(_wrapped("my-clickup_create_taskk"), 404,
                     {"detail": "not found"})
    assert "no tool called call_tool" not in out, out


async def test_a_refused_service_names_the_tool_not_the_runner():
    out = await _run(_wrapped("my-trello_create_card"), 403,
                     {"detail": "no access"})
    assert "my-trello_create_card" in out, out
    assert "behind the tool call_tool" not in out, out


async def test_a_broken_service_names_the_tool_not_the_runner():
    out = await _run(_wrapped("my-github_create_issue"), 500,
                     {"detail": "boom"})
    assert "my-github_create_issue" in out, out
    assert "The tool call_tool" not in out, out


async def test_an_unwrapped_proxy_tool_still_names_itself():
    """Regression guard: most native and proxy calls arrive unwrapped and
    already named themselves correctly. That must not change."""
    out = await _run(_call("my-clickup_list_tasks"), 500, {"detail": "boom"})
    assert "my-clickup_list_tasks" in out, out


async def test_a_runner_call_with_no_inner_name_still_answers():
    """A malformed call must not crash the one function whose contract is
    that it never raises. There is nothing better to name here."""
    out = await _run(_call("call_tool"), 500, {"detail": "boom"})
    assert "call_tool" in out, out


# ------------------------------------------------------- what was wrong

async def test_a_rejected_call_says_which_field_was_missing():
    out = await _run(_wrapped(WRAPPED), 422, _validation_body(
        ["list_id", "name"]))
    assert "list_id" in out, out
    assert "name" in out, out


async def test_the_named_fields_are_read_from_the_body():
    """Not a canned guess about create_task: a different complaint names
    different fields."""
    out = await _run(_wrapped("my-clickup_get_spaces"), 422,
                     _validation_body(["team_id"]))
    assert "team_id" in out, out
    assert "list_id" not in out, out


async def test_a_rejected_call_still_names_the_tool():
    out = await _run(_wrapped(WRAPPED), 422, _validation_body(["list_id"]))
    assert WRAPPED in out, out


async def test_an_argument_value_is_never_read_back_to_the_model():
    """A validation body echoes the arguments it rejected under `input`.
    Only field names and reasons may leave this function: an argument can
    hold anything the model was handed, and a proxy error can carry the
    URL it called, which for Trello has the credential in its query
    string."""
    body = _validation_body(
        ["list_id"],
        extra={"input": {"token": "shh-9f3a-secret", "name": "x"}})
    out = await _run(_wrapped(WRAPPED), 422, body)
    assert "shh-9f3a-secret" not in out, out


async def test_a_rejection_that_says_nothing_useful_falls_back():
    """A 422 whose body is not a validation complaint must still produce
    the plain sentence, naming the right tool, rather than nothing."""
    out = await _run(_wrapped(WRAPPED), 422, {"detail": "no idea"})
    assert WRAPPED in out, out
    assert len(out) > 20, out


# ------------------------------------------------- the pure decisions

def test_the_tool_name_helper_reads_the_inner_name():
    assert T.called_tool_name("call_tool", {"tool_name": WRAPPED}) == WRAPPED


def test_the_tool_name_helper_keeps_an_ordinary_name():
    assert T.called_tool_name("gmail_send", {"to": "x"}) == "gmail_send"


def test_the_tool_name_helper_survives_junk():
    for params in ({}, None, {"tool_name": ""}, {"tool_name": "  "},
                   {"tool_name": 7}, {"tool_name": "call_tool"},
                   "not a dict"):
        assert T.called_tool_name("call_tool", params) == "call_tool", params


def test_the_complaint_names_every_field_and_its_reason():
    body = json.dumps(_validation_body(["list_id", "name"]))
    said = T.argument_complaint(body)
    assert said is not None
    assert "list_id" in said and "name" in said


def test_the_complaint_is_none_when_there_is_nothing_to_say():
    for body in ("", "not json", "{}", '{"detail": "words"}',
                 '{"detail": [1, 2, 3]}', None):
        assert T.argument_complaint(body) is None, body


async def test_a_rejected_call_is_told_to_call_it_again():
    """Naming the fields is half of it. PR #148's sentence works because
    it says what to DO; this one has to as well, or the model reports the
    rejection to its owner instead of fixing the call."""
    out = await _run(_wrapped(WRAPPED), 422, _validation_body(["list_id"]))
    assert "again" in out.lower(), out


async def test_a_tool_that_times_out_names_the_tool_not_the_runner():
    async def boom(url, json=None, headers=None, timeout=None):
        raise RuntimeError("connect timeout to http://mcp-proxy:8000")

    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json", new=boom):
        out = await execute_tool_call(_wrapped(WRAPPED), "owner@example.com")
    assert WRAPPED in out, out


async def test_a_tool_that_times_out_still_hides_the_exception_text():
    """Unchanged rule: an httpx error carries the URL it called, and
    my-trello's credential rides in that URL's query string."""
    async def boom(url, json=None, headers=None, timeout=None):
        raise RuntimeError("connect timeout to http://mcp-proxy:8000")

    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json", new=boom):
        out = await execute_tool_call(_wrapped(WRAPPED), "owner@example.com")
    assert "mcp-proxy:8000" not in out, out
    assert "connect timeout" not in out, out


# ------------------------------------- what the OWNER is told and asked

def _reply(content=None, calls=None):
    message = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if calls is not None:
        message["tool_calls"] = calls
    return {"choices": [{"message": message}]}


async def test_a_refusal_the_owner_reads_names_the_real_tool():
    """A read only agent that tries a ClickUp write tells its owner
    "Declined to run call_tool", which names nothing they can act on."""
    import agent_runner

    async def fake_post(payload, token, timeout=None):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_wrapped(WRAPPED, {"name": "x"})])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=["server:mcp-proxy"], user_email="owner@example.com",
            tool_mode="read_only")

    assert notes, notes
    assert WRAPPED in notes[0], notes[0]


async def test_the_refusal_fed_back_to_the_model_names_it_too():
    import agent_runner

    seen = {}

    async def fake_post(payload, token, timeout=None):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_wrapped(WRAPPED, {"name": "x"})])
        seen["messages"] = payload.get("messages")
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()):
        await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=["server:mcp-proxy"], user_email="owner@example.com",
            tool_mode="read_only")

    results = [m for m in (seen.get("messages") or [])
               if m.get("role") == "tool"]
    assert results, seen.get("messages")
    assert WRAPPED in results[-1].get("content", ""), results[-1]


def test_the_question_asks_about_the_tool_not_the_runner():
    """The question Ralph answers. "Vera wants to run: call_tool" buries
    what he is approving one line down, under a key called tool_name."""
    import routes_agent_turn as rt

    said = rt.approval_question("Vera", [_wrapped(WRAPPED, {
        "list_id": "901", "name": "Buy milk"})])
    first_tool_line = said.splitlines()[1].strip()
    assert first_tool_line == WRAPPED, said


def test_the_question_shows_the_arguments_that_will_be_sent():
    """Wrapped, the real arguments arrive as one stringified dict under
    `arguments` and are truncated. Unwrapped they read as themselves."""
    import routes_agent_turn as rt

    said = rt.approval_question("Vera", [_wrapped(WRAPPED, {
        "list_id": "901", "name": "Buy milk"})])
    assert "list_id: 901" in said, said
    assert "name: Buy milk" in said, said


def test_an_ordinary_call_is_still_asked_about_unchanged():
    import routes_agent_turn as rt

    said = rt.approval_question("Mia", [_call("send_email", {"to": "a@b.c"})])
    assert said.splitlines()[1].strip() == "send_email", said
    assert "to: a@b.c" in said, said


# -------------------------------------------- measured on the box, both
# vendors, 2026-11-09. The two per-user servers share one validation
# shape, so the complaint is not a ClickUp-specific trick:
#
#   my-clickup_create_task     {} -> 422  list_id (missing), name (missing)
#   my-trello_create_card      {} -> 422  list_id (missing), name (missing)
#   my-trello_comment_on_card  {} -> 422  card_id (missing), text (missing)
#   my-trello_list_cards       {} -> 422  list_id (missing)
#   my-trello_add_card         {} -> 404  (no such tool, and there is not)
#
# No credential appeared in any raw body or any complaint, checked by
# searching each for the live values.
@pytest.mark.parametrize("tool,fields", [
    ("my-clickup_create_task", ["list_id", "name"]),
    ("my-trello_create_card", ["list_id", "name"]),
    ("my-trello_comment_on_card", ["card_id", "text"]),
    ("my-trello_list_cards", ["list_id"]),
])
async def test_both_per_user_servers_name_their_own_fields(tool, fields):
    out = await _run(_wrapped(tool), 422, _validation_body(fields))
    assert tool in out, out
    for field in fields:
        assert field in out, out
