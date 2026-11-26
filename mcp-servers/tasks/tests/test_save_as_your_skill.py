"""Save as your skill: what counts as something made."""
import json

import pytest

import agent_activity
import skill_offer

OK = json.dumps({"ok": True, "item": {"id": "w1"}})
BAD = json.dumps({"ok": False, "error": "n8n refused it"})


@pytest.mark.parametrize("tool", ["my-n8n_create_workflow", "create_workflow",
                                  "my-n8n_activate_workflow"])
def test_a_workflow_that_was_made_counts(tool):
    assert skill_offer.counts(tool, agent_activity.STEP_OK, OK)


def test_a_refused_or_failed_workflow_does_not_count():
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, BAD)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_FAILED, OK)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, "not json")
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, "[1]")
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, None)


def test_an_automation_counts_only_when_it_was_made():
    assert skill_offer.counts("create_automation", agent_activity.STEP_OK,
                              "Made the automation Leads. Ada will do that ...")
    assert not skill_offer.counts("create_automation", agent_activity.STEP_OK,
                                  "Nothing was made: name taken")


def test_other_tools_never_count():
    for t in ("my-n8n_list_my_workflows", "my-n8n_update_workflow",
              "my-n8n_deactivate_workflow", "create_schedule", "send_email"):
        assert not skill_offer.counts(t, agent_activity.STEP_OK, OK)


def test_note_collects_only_inside_collecting():
    skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)   # no error
    with skill_offer.collecting() as made:
        skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)
        skill_offer.note("send_email", agent_activity.STEP_OK, OK)
        skill_offer.note(None, None, None)
    assert made == ["create_workflow"]


def test_the_link_is_added_once():
    once = skill_offer.with_link("Done.")
    assert once == "Done.\n\n" + skill_offer.LINK
    assert skill_offer.with_link(once) == once


# --- Task 2: every call is reported, and the main chat adds the link -------

from unittest.mock import AsyncMock  # noqa: E402

import agent_tools  # noqa: E402
import routes_agent_turn as rt  # noqa: E402

SECRET = "s3cret"
MADE = "Made the automation Leads. Ada will do that when a webhook arrives."


class _Body:
    """Only what _chat_inner reads before it hands over."""

    def __init__(self, text, route_only=True):
        self.messages = [{"role": "user", "content": text}]
        self.user_email = "owner@example.com"
        self.chat_id = "chat-1"
        self.agent_id = None
        self.route_only = route_only
        self.first_only = False


async def test_execute_tool_call_reports_what_it_ran(monkeypatch):
    monkeypatch.setattr(agent_tools, "_load_native_tool_source",
                        AsyncMock(return_value="def create_automation(): pass"))
    monkeypatch.setattr(agent_tools, "_run_native", AsyncMock(return_value=MADE))
    with skill_offer.collecting() as made:
        got = await agent_tools.execute_tool_call(
            {"function": {"name": "create_automation", "arguments": "{}"}},
            "a@b.c")
    assert got == MADE
    assert made == ["create_automation"]


async def test_a_proxy_call_is_reported_by_its_inner_name(monkeypatch):
    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            # The real proxy answers with an object, and _call_via_proxy
            # turns it back into text.
            return {"ok": True, "item": {"id": "w1"}}

    monkeypatch.setattr(agent_tools, "_load_native_tool_source",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(agent_tools, "_post_json", AsyncMock(return_value=_Resp()))
    with skill_offer.collecting() as made:
        await agent_tools.execute_tool_call(
            {"function": {"name": "call_tool", "arguments": json.dumps(
                {"tool_name": "my-n8n_create_workflow", "arguments": {}})}},
            "a@b.c")
    assert made == ["my-n8n_create_workflow"]


async def test_a_failed_or_malformed_call_reports_nothing_and_still_answers(monkeypatch):
    monkeypatch.setattr(agent_tools, "_load_native_tool_source",
                        AsyncMock(return_value="def create_automation(): pass"))
    monkeypatch.setattr(agent_tools, "_run_native",
                        AsyncMock(side_effect=RuntimeError("boom")))
    with skill_offer.collecting() as made:
        got = await agent_tools.execute_tool_call(
            {"function": {"name": "create_automation", "arguments": "{}"}},
            "a@b.c")
        bad = await agent_tools.execute_tool_call("not a call", "a@b.c")
    assert "could not be run" in got
    assert "malformed" in bad
    assert made == []


async def test_a_broken_note_never_breaks_the_call(monkeypatch):
    monkeypatch.setattr(agent_tools, "_load_native_tool_source",
                        AsyncMock(return_value="def create_automation(): pass"))
    monkeypatch.setattr(agent_tools, "_run_native", AsyncMock(return_value=MADE))

    def boom(*a, **k):
        raise RuntimeError("note broke")

    monkeypatch.setattr(skill_offer, "note", boom)
    got = await agent_tools.execute_tool_call(
        {"function": {"name": "create_automation", "arguments": "{}"}}, "a@b.c")
    assert got == MADE


def test_the_offer_goes_on_the_last_reply():
    out = rt._reply([{"agent": None, "answer": "Made it.", "notes": []}])
    got = rt._with_skill_offer(out, ["create_automation"])
    assert got["turns"][-1]["answer"].endswith(skill_offer.LINK)
    assert skill_offer.LINK in got["rendered_web"]
    assert skill_offer.LINK in got["rendered"]
    # Nothing the reply carried is lost.
    assert set(out) <= set(got)
    # The caller's dict is not changed under it.
    assert out["turns"][-1]["answer"] == "Made it."


def test_the_offer_keeps_what_it_does_not_rebuild():
    out = rt._reply([{"agent": None, "answer": "Made it.", "notes": []}],
                    queue=["agent-x"], marker="m", status="Used n8n")
    out["extra"] = 1
    got = rt._with_skill_offer(out, ["create_workflow"])
    assert (got["queue"], got["marker"], got["status"], got["extra"]) == \
        (["agent-x"], "m", "Used n8n", 1)


def test_the_offer_is_never_added_twice():
    out = rt._reply([{"agent": None, "answer": "Made it.", "notes": []}])
    once = rt._with_skill_offer(out, ["create_workflow"])
    twice = rt._with_skill_offer(once, ["create_workflow", "create_automation"])
    assert twice["turns"][-1]["answer"].count(skill_offer.LINK) == 1


def test_no_offer_when_nothing_was_made_or_the_reply_waits():
    out = rt._reply([{"agent": None, "answer": "Hi.", "notes": []}])
    assert rt._with_skill_offer(out, []) == out
    held = rt._reply([{"agent": None, "answer": "Shall I?", "notes": [],
                       "pending": {"calls": [{"id": "1"}], "agent_id": "x"}}])
    assert rt._with_skill_offer(held, ["create_workflow"]) == held
    empty = rt._reply([{"agent": None, "answer": "", "notes": []}])
    assert rt._with_skill_offer(empty, ["create_workflow"]) == empty


def test_the_offer_fails_open():
    assert rt._with_skill_offer({"turns": "broken"}, ["create_workflow"]) == \
        {"turns": "broken"}
    assert rt._with_skill_offer(None, ["create_workflow"]) is None
    assert rt._with_skill_offer({"turns": []}, ["create_workflow"]) == {"turns": []}


def _made_a_workflow(monkeypatch):
    async def turns(body, secret):
        skill_offer.note("my-n8n_create_workflow", agent_activity.STEP_OK, OK)
        return rt._reply([{"agent": None, "answer": "Your workflow is live.",
                           "notes": []}])

    monkeypatch.setattr(rt, "_chat_turns", turns)


async def test_the_main_chat_adds_it_after_a_made_workflow(monkeypatch):
    _made_a_workflow(monkeypatch)
    out = await rt._chat_inner(_Body("yes", route_only=True), SECRET)
    assert out["turns"][-1]["answer"].endswith(skill_offer.LINK)
    assert skill_offer.LINK in out["rendered_web"]


async def test_the_panel_gets_no_offer(monkeypatch):
    _made_a_workflow(monkeypatch)
    out = await rt._chat_inner(_Body("yes", route_only=False), SECRET)
    assert skill_offer.LINK not in out["turns"][-1]["answer"]
    assert skill_offer.LINK not in out["rendered_web"]


async def test_one_request_does_not_leak_into_the_next(monkeypatch):
    _made_a_workflow(monkeypatch)
    await rt._chat_inner(_Body("yes"), SECRET)

    async def quiet(body, secret):
        return rt._reply([{"agent": None, "answer": "Hi.", "notes": []}])

    monkeypatch.setattr(rt, "_chat_turns", quiet)
    out = await rt._chat_inner(_Body("hello"), SECRET)
    assert skill_offer.LINK not in out["rendered_web"]


# --- the service owns the link: a copy the model wrote is not a button -----

def test_without_link_removes_a_copy_and_its_blank_lines():
    L = skill_offer.LINK
    assert skill_offer.without_link("Done.\n\n" + L) == "Done."
    assert skill_offer.without_link("Done.\n\n" + L + "\n\nAnything else?") == \
        "Done.\n\nAnything else?"
    assert skill_offer.without_link("Press " + L + " to keep it.") == \
        "Press to keep it."
    assert skill_offer.without_link(L) == ""
    assert skill_offer.without_link("No link here.") == "No link here."
    assert skill_offer.without_link(None) is None


def test_a_copied_link_with_nothing_made_is_removed():
    L = skill_offer.LINK
    out = rt._reply([{"agent": None, "answer": "Sure.\n\n" + L, "notes": []}])
    got = rt._with_skill_offer(out, [])
    assert got["turns"][-1]["answer"] == "Sure."
    assert L not in got["rendered"] and L not in got["rendered_web"]


def test_a_copied_link_with_something_made_ends_with_one_link():
    L = skill_offer.LINK
    out = rt._reply([{"agent": None, "answer": L + "\n\nMade it.\n\n" + L,
                      "notes": []}])
    got = rt._with_skill_offer(out, ["create_workflow"])
    answer = got["turns"][-1]["answer"]
    assert answer.count(L) == 1 and answer.endswith(L)
    assert got["rendered_web"].count(L) == 1


def test_a_held_reply_loses_a_copied_link():
    L = skill_offer.LINK
    out = rt._reply([{"agent": None, "answer": "Shall I?\n\n" + L, "notes": [],
                      "pending": {"calls": [{"id": "1"}], "agent_id": "x"}}])
    got = rt._with_skill_offer(out, ["create_workflow"])
    assert L not in got["turns"][-1]["answer"]
    assert L not in got["rendered_web"]


def test_a_copy_in_an_earlier_turn_is_removed_too():
    L = skill_offer.LINK
    out = rt._reply([{"agent": {"id": "a1", "name": "Ada"}, "answer": "Hi " + L,
                      "notes": []},
                     {"agent": None, "answer": "Made it.", "notes": []}])
    got = rt._with_skill_offer(out, ["create_workflow"])
    assert L not in got["turns"][0]["answer"]
    assert got["rendered"].count(L) == 1


async def test_the_main_chat_drops_a_link_the_model_copied(monkeypatch):
    async def copied(body, secret):
        return rt._reply([{"agent": None, "notes": [],
                           "answer": "Hello again.\n\n" + skill_offer.LINK}])

    monkeypatch.setattr(rt, "_chat_turns", copied)
    out = await rt._chat_inner(_Body("hi"), SECRET)
    assert skill_offer.LINK not in out["rendered_web"]


# --- the click reaches the skills tool (final review, Important 1) ---------

import pathlib  # noqa: E402
import re  # noqa: E402

import agent_graph  # noqa: E402
import main_assistant  # noqa: E402

UI_JS = pathlib.Path(__file__).resolve().parents[2] / "gdrive" / "integrations-ui.js"


def test_the_button_sends_exactly_the_message_the_service_knows():
    """The page's text and skill_offer.ASK are one sentence in two
    languages; if they drift the click stops reaching the skills tool."""
    src = UI_JS.read_text(encoding="utf-8")
    m = re.search(r"'save-skill':\s*\{\s*label:\s*'([^']*)',\s*text:\s*'([^']*)'\s*\}",
                  src)
    assert m, "AIUI_SAY_TEXTS['save-skill'] is not {label, text} on its own"
    assert m.group(1) == "Save as your skill"
    assert m.group(2) == skill_offer.ASK


def test_the_ask_is_recognised_only_word_for_word():
    assert skill_offer.is_ask(skill_offer.ASK)
    assert skill_offer.is_ask("  " + skill_offer.ASK + "\n")
    assert not skill_offer.is_ask("Write a skill")
    assert not skill_offer.is_ask(skill_offer.ASK + " Also email Bob.")
    assert not skill_offer.is_ask(None)
    assert not skill_offer.is_ask(["not", "text"])


def _ask_chat(monkeypatch, jev_picks=(), pin=()):
    """_route_chat on Auto with the real _tool_pick and _assistant_reply,
    Jev picking `jev_picks` (or failing, when it is None), and the chat's
    tools pin holding `pin`. Records what the assistant was given."""
    seen = {"turn": [], "pins": []}

    async def pick_tools(email, text, tools, context=""):
        if jev_picks is None:
            raise RuntimeError("Jev is down")
        return list(jev_picks)

    async def turn_for(email, agent, messages, names=(), roster=(), graph="",
                       now=None, tool_ids=None):
        seen["turn"].append(list(tool_ids or []))
        return {"agent": agent, "answer": "Here is the draft.", "notes": []}

    async def write_pin(key, tools):
        seen["pins"].append(list(tools))

    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_jev_release", AsyncMock(return_value=False))
    monkeypatch.setattr(rt, "_agents_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_triage_pick", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda _a: True)
    monkeypatch.setattr(rt.agent_jev, "pick_tools", pick_tools)
    monkeypatch.setattr(rt, "_every_tool_for",
                        AsyncMock(return_value=["skills", "my-n8n", "automations"]))
    monkeypatch.setattr(rt, "_read_tools_pin", AsyncMock(return_value=list(pin)))
    monkeypatch.setattr(rt, "_write_tools_pin", write_pin)
    monkeypatch.setattr(agent_graph, "graph_block", AsyncMock(return_value=""))
    monkeypatch.setattr(rt, "_skill_connect_needs", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_turn_for", turn_for)
    return seen


def _ask_body():
    body = _Body(skill_offer.ASK)
    body.messages = [
        {"role": "user", "content": "make me an n8n workflow for new leads"},
        {"role": "assistant", "content": "Your workflow is live.\n\n" + skill_offer.LINK},
        {"role": "user", "content": skill_offer.ASK}]
    return body


@pytest.mark.parametrize("jev_picks", [(), None], ids=["picks-nothing", "down"])
async def test_the_click_runs_the_assistant_with_the_skills_tool(monkeypatch, jev_picks):
    seen = _ask_chat(monkeypatch, jev_picks=jev_picks)
    out = await rt._route_chat(_ask_body(), SECRET)
    assert seen["turn"] == [["skills"]], "the assistant did not run with skills"
    assert out["turns"][-1]["answer"] == "Here is the draft."
    # Kept for "yes, save it", which is the turn that calls save_skill.
    assert seen["pins"] and "skills" in seen["pins"][-1]


async def test_the_click_keeps_the_tools_the_chat_was_using(monkeypatch):
    """The pin from making the workflow is what tells the draft what was
    made; skills goes on top of it, not instead of it."""
    seen = _ask_chat(monkeypatch, jev_picks=(), pin=["my-n8n"])
    await rt._route_chat(_ask_body(), SECRET)
    assert seen["turn"] == [["my-n8n", "skills"]]


async def test_skills_is_not_added_twice(monkeypatch):
    seen = _ask_chat(monkeypatch, jev_picks=("skills",))
    await rt._route_chat(_ask_body(), SECRET)
    assert seen["turn"] == [["skills"]]


async def test_an_ordinary_question_still_goes_to_the_free_model(monkeypatch):
    seen = _ask_chat(monkeypatch, jev_picks=())
    out = await rt._route_chat(_Body("what is the capital of France"), SECRET)
    assert seen["turn"] == []
    assert out["turns"] == []


async def test_the_click_does_not_wake_a_switched_off_assistant(monkeypatch):
    seen = _ask_chat(monkeypatch, jev_picks=())
    monkeypatch.setattr(rt, "_assistant_on", lambda: False)
    await rt._route_chat(_ask_body(), SECRET)
    assert seen["turn"] == []


# --- a yes that resumes a held create (final review, Minor 5) --------------

async def test_a_yes_that_makes_the_workflow_gets_the_offer(monkeypatch):
    """The real _chat_turns path: the held create_workflow is resumed by a
    bare yes, the call runs during the resume, and the link goes under it."""
    held = {"user_email": "owner@example.com",
            "agent_id": main_assistant.ASSISTANT_ID,
            "conversation": [{"role": "user", "content": "make the workflow"}],
            "calls": [{"id": "c1", "function": {"name": "call_tool"}}]}
    resumed = {}

    async def resume_turn(user_email, agent_id, conversation, calls, approved):
        resumed["approved"] = approved
        skill_offer.note("my-n8n_create_workflow", agent_activity.STEP_OK, OK)
        return {"answer": "Your workflow is live.", "notes": []}

    monkeypatch.setattr(rt, "_read_pending", AsyncMock(return_value=held))
    monkeypatch.setattr(rt, "_clear_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_resume_turn", resume_turn)
    out = await rt._chat_inner(_Body("yes"), SECRET)
    assert resumed == {"approved": True}
    assert out["turns"][-1]["answer"] == "Your workflow is live.\n\n" + skill_offer.LINK
    assert out["turns"][-1]["agent"] is None
    assert skill_offer.LINK in out["rendered_web"]


async def test_the_click_is_not_handed_to_an_agent_jev_picks(monkeypatch):
    """With AGENTS_ANSWER_UNNAMED on, Jev may hand an unnamed message to an
    agent; the button's message is the assistant's, which has skills."""
    seen = _ask_chat(monkeypatch, jev_picks=())
    monkeypatch.setattr(rt, "_agents_may_take_unnamed", lambda: True)
    jev = AsyncMock(return_value={"id": "agent-vera", "name": "Vera"})
    monkeypatch.setattr(rt, "_jev_decision", jev)
    await rt._route_chat(_ask_body(), SECRET)
    assert jev.await_count == 0
    assert seen["turn"] == [["skills"]]
