"""A call that does nothing is never put to the person as a question.

2026-11-06. Ralph asked the chat to create a ClickUp space. It answered:

    This will run:
    refresh_cache

    Reply yes to let it, or no to skip.

He said, plainly: "i said if run something like rfresh casche make it
automatic no more in chat or reply".

He is right twice over. `refresh_cache` is housekeeping, not an action on
anything of his. And it does not exist: PROXY_META_ABSENT has recorded
since 2026-09-14 that /meta/refresh_cache, /meta/health_check and
/meta/list_servers each 404. The proxy serves /refresh and /servers.

So he was being asked to authorise a call that could not do anything,
and the refusal only arrived after he answered.

The runner already has this shape for a different case: a name in
METHODS_NO_AGENT_MAY_CALL is run straight through, comes back a refusal,
and is "never shown to the owner as a question". This widens that rule
rather than inventing a second one.
"""
import pytest

import agent_tools as T


# --- the rule -----------------------------------------------------------

def test_the_rule_exists():
    assert hasattr(T, "never_ask_about"), (
        "nothing names the calls that must not become a question")


@pytest.mark.parametrize("name", sorted(T.PROXY_META_ABSENT))
def test_a_call_that_does_not_exist_is_never_asked_about(name):
    assert T.never_ask_about(name) is True


@pytest.mark.parametrize("name", sorted(T.METHODS_NO_AGENT_MAY_CALL))
def test_the_case_this_was_modelled_on_still_holds(name):
    assert T.never_ask_about(name) is True


@pytest.mark.parametrize("name", [
    "call_tool", "create_task", "send_email", "delete_space",
    "my-clickup_create_space",
])
def test_a_real_action_is_still_a_question(name):
    assert T.never_ask_about(name) is False, (
        name + " would now run without being asked about")


def test_an_odd_name_is_not_waved_through():
    for name in ("", None, 123, "  "):
        assert T.never_ask_about(name) is False


# --- it is the rule the runner actually uses ----------------------------

def test_the_runner_asks_the_rule_rather_than_a_list():
    """Two lists checked in two places drift. The runner used to name only
    METHODS_NO_AGENT_MAY_CALL, which is why refresh_cache reached Ralph."""
    import inspect

    import agent_runner

    src = inspect.getsource(agent_runner)
    assert "never_ask_about(" in src, (
        "the runner still decides this for itself")
    # And it actually RESOLVES there. The first version of this fix wrote
    # agent_tools.never_ask_about(...) into a module that imports names
    # from agent_tools and never binds the module itself: a NameError on
    # every tool call, with the source text looking perfectly correct.
    assert hasattr(agent_runner, "never_ask_about"), (
        "the name is in the source but not importable there")
    assert agent_runner.never_ask_about("refresh_cache") is True


def test_refresh_cache_is_the_one_he_saw():
    """Named outright so a future edit to PROXY_META_ABSENT cannot quietly
    put it back in front of him."""
    assert "refresh_cache" in T.PROXY_META_ABSENT
    assert T.never_ask_about("refresh_cache") is True
    assert T.is_write_call("refresh_cache", {}) is True, (
        "if this stops reading as a write the bypass is what keeps it "
        "out of the chat, so the test above is the one that matters")
