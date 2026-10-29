"""Creating an agent asks the person once, not twice.

Reported 2026-10-29 with a screenshot. The chat showed the full brief for an
agent called Crane and asked whether to create it. The person said "yes" and
Crane was not created. Instead the turn was held for a SECOND approval, and
the model filled the confusion by proposing a different agent, Rexy.

From the live box, the same minute:

    15:26:23  agent_builder 0.90  chat  completed   the brief
    15:27:16  agent_builder 0.77  chat  WAITING     the "yes", held again

Two approvals were in the way of one decision. `create_agent` does its own,
in two steps, and the generic hold was adding another on top of it.

The preview is the better of the two and the one that was kept: it shows the
instructions the agent will be given, in full and in plain language, where
the generic hold shows raw arguments.
"""
import agent_tools


def test_create_agent_is_not_held_for_a_second_approval():
    """The reported bug. Held as a write, saying yes to the brief opens
    another question instead of creating the agent."""
    assert agent_tools.is_write_call("create_agent", {}) is False


def test_it_is_not_held_with_a_confirm_code_either():
    """The confirmed call is the one that writes, and it writes because the
    person just read the brief and agreed to it. Asking again asks the same
    question twice."""
    assert agent_tools.is_write_call(
        "create_agent", {"name": "Crane", "confirm": "e500e1974ce2"}) is False


def test_it_is_named_as_asking_for_itself_not_as_harmless():
    """The exemption must be deliberate and findable. A tool belongs in that
    set only because it asks first on its own, and if the preview is ever
    removed this is the line that has to be revisited."""
    assert "create_agent" in agent_tools.METHODS_THAT_ASK_FOR_THEMSELVES


# --- nothing else lost its brake ----------------------------------------------

def test_sending_mail_is_still_held():
    assert agent_tools.is_write_call("send_email", {}) is True


def test_making_an_automation_is_still_held():
    assert agent_tools.is_write_call("create_automation", {}) is True


def test_deleting_is_still_held():
    assert agent_tools.is_write_call("delete_automation", {}) is True


def test_reads_are_still_reads():
    assert agent_tools.is_write_call("gmail_list_emails", {}) is False


def test_the_proxy_runner_is_still_judged_by_its_inner_tool():
    """The exemption must not short-circuit call_tool, whose name says
    nothing and whose argument is the whole story."""
    assert agent_tools.is_write_call(
        "call_tool", {"tool_name": "clickup_create_task"}) is True
    assert agent_tools.is_write_call(
        "call_tool", {"tool_name": "web-search_web_search"}) is False
    assert agent_tools.is_write_call("call_tool", {}) is True


def test_only_one_tool_is_exempt():
    """Every entry costs a brake, so the set stays small and deliberate."""
    assert agent_tools.METHODS_THAT_ASK_FOR_THEMSELVES == frozenset({"create_agent"})
