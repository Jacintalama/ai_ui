"""The main chat never says an agent was made when it was not (2026-11-27).

Live: "yes, create Wren" ran create_agent five times, every call a preview,
and the reply said "Wren is created." Nothing was. Same as 2026-10-29
("Crane is now active"). The service knows what create_agent answered, so
it decides, not the model.
"""
import agent_made
import agent_activity

OK = agent_activity.STEP_OK
PREVIEW = ("Here is the agent I would create. Nothing has been made yet.\n\n"
           "Name: Wren\nRole: Morning briefing\n\nInstructions:\nRead my day.\n\n"
           "If that is right, say so and I will create it. Tell me what to "
           "change and I will show you the new version first.\n\n"
           "(confirm code: abc123def456)")
MADE = "Made Wren (Morning briefing), read only. It is in the Agent Office now."


def _run(calls):
    with agent_made.collecting() as seen:
        for tool, status, result in calls:
            agent_made.note(tool, status, result)
        return list(seen)


def test_a_claim_with_only_previews_is_replaced_by_the_preview():
    seen = _run([("create_agent", OK, PREVIEW)] * 3)
    out = agent_made.checked("Wren is created. It reads your calendar.", seen)
    assert out.startswith("Wren is not made yet.")
    assert "Name: Wren" in out and "say so and I will create it" in out
    assert "confirm code" not in out
    assert "Wren is created" not in out


def test_a_real_make_leaves_the_answer_alone():
    seen = _run([("create_agent", OK, PREVIEW), ("create_agent", OK, MADE)])
    answer = "Wren is created. It reads your calendar."
    assert agent_made.checked(answer, seen) == answer


def test_an_honest_preview_answer_is_left_alone():
    seen = _run([("create_agent", OK, PREVIEW)])
    for answer in ("Here is Wren as it would be. Nothing has been made yet.",
                   "Say yes and I will create it.",
                   "Wren is not created yet; say the word.",
                   "Once you say yes, Wren will be made."):
        assert agent_made.checked(answer, seen) == answer, answer


def test_no_create_agent_call_means_nothing_is_checked():
    """Talk about an agent made in an earlier turn is not this turn's claim."""
    answer = "Wren was created yesterday and reads your calendar."
    assert agent_made.checked(answer, _run([])) == answer
    assert agent_made.checked(answer, _run([("list_my_agents", OK, "Wren")])) == answer


def test_the_claims_it_catches():
    seen = _run([("create_agent", OK, PREVIEW)])
    for answer in ("Wren is created.", "Done! Wren has been made.",
                   "I've created Wren for you.", "I created Wren.",
                   "Wren is now created and in the Agent Office.",
                   "I have made Wren."):
        assert agent_made.checked(answer, seen).startswith("Wren is not made yet."), answer


def test_a_namespaced_tool_counts_and_a_failed_call_is_not_a_preview():
    seen = _run([("agent_builder_create_agent", OK, PREVIEW)])
    assert agent_made.checked("Wren is created.", seen).startswith("Wren is not")
    failed = _run([("create_agent", agent_activity.STEP_FAILED, "boom")])
    assert agent_made.checked("Wren is created.", failed) == "Wren is created."


def test_note_outside_collecting_and_bad_input_never_raise():
    agent_made.note("create_agent", OK, PREVIEW)
    agent_made.note(None, None, None)
    assert agent_made.checked(None, ["x"]) is None


def test_the_main_chat_route_shows_the_preview_instead_of_the_claim(monkeypatch):
    import asyncio
    import routes_agent_turn as rt

    class _B:
        route_only = True

    async def turns(body, secret):
        agent_made.note("create_agent", OK, PREVIEW)
        return rt._reply([{"agent": {"id": "io-assistant", "name": "IO"},
                           "answer": "Wren is created. It reads your calendar."}])
    monkeypatch.setattr(rt, "_chat_turns", turns)
    out = asyncio.run(rt._chat_inner(_B(), "s"))
    answer = out["turns"][-1]["answer"]
    assert answer.startswith("Wren is not made yet.")
    assert "Wren is not made yet." in out["rendered"]


def test_the_route_leaves_a_real_make_alone(monkeypatch):
    import asyncio
    import routes_agent_turn as rt

    class _B:
        route_only = True

    async def turns(body, secret):
        agent_made.note("create_agent", OK, MADE)
        return rt._reply([{"agent": {"id": "io-assistant", "name": "IO"},
                           "answer": "Wren is created."}])
    monkeypatch.setattr(rt, "_chat_turns", turns)
    out = asyncio.run(rt._chat_inner(_B(), "s"))
    assert out["turns"][-1]["answer"] == "Wren is created."
