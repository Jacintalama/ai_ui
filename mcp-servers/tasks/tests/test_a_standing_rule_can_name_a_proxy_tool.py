"""A standing rule can name the tool it means.

Measured on production 2026-11-09: 46 approvals have been asked, 37 of
them approved, and ZERO standing rules have ever been written. This is
why.

Every one of the proxy's roughly 200 tools reaches the tool loop as
`call_tool`, with the real name inside the arguments, and
`rule_decision` fnmatches the outer name. So of the two rules a person
might write:

    tool = "my-clickup_create_task"   never fires, for anything
    tool = "call_tool"                fires for ALL ~200 proxy tools

the specific one silently does nothing, and the only one that works
allows or denies web search, Trello, GitHub, n8n and deleting a ClickUp
space together. There is no way to say "always allow this one thing",
which is the entire purpose of a standing rule and the reason Ralph has
been answering the same question 37 times.

`is_write_call` has read the inner name since PR #147 and the failure
sentences since PR #155. This is the last place that did not.

Both names match, not just the inner one. A rule written `call_tool` is
a blanket today, and somebody who wrote `call_tool` + deny meant to stop
proxy writes; silently narrowing that to nothing would be a safety
regression in the one direction that matters. Deny still wins over allow.
"""
import agent_approvals as ap

CREATE = "my-clickup_create_task"


def _wrapped(tool_name, args=None):
    """The arguments as the tool loop has them for a proxy call: the real
    name and the real arguments nested inside."""
    return {"tool_name": tool_name, "arguments": args or {}}


def test_a_rule_can_name_the_proxy_tool_it_means():
    rules = [{"tool": CREATE, "decision": "allow", "label": "my clickup"}]
    got = ap.rule_decision(rules, "call_tool", _wrapped(CREATE))
    assert got is not None, "a rule naming the tool never fired"
    assert got["label"] == "my clickup"


def test_a_pattern_can_cover_one_service():
    rules = [{"tool": "my-clickup_*", "decision": "allow", "label": "clickup"}]
    got = ap.rule_decision(rules, "call_tool", _wrapped(CREATE))
    assert got is not None and got["label"] == "clickup"


def test_a_rule_for_another_service_does_not_fire():
    rules = [{"tool": "my-trello_*", "decision": "allow"}]
    assert ap.rule_decision(rules, "call_tool", _wrapped(CREATE)) is None


def test_a_deny_for_one_tool_beats_an_allow_for_the_service():
    """The shape that makes a rule worth writing at all: everything in
    ClickUp except the one thing I never want done."""
    rules = [{"tool": "my-clickup_*", "decision": "allow"},
             {"tool": "my-clickup_delete_space", "decision": "deny",
              "label": "never delete a space"}]
    got = ap.rule_decision(rules, "call_tool",
                           _wrapped("my-clickup_delete_space"))
    assert got["decision"] == "deny"
    assert got["label"] == "never delete a space"
    allowed = ap.rule_decision(rules, "call_tool", _wrapped(CREATE))
    assert allowed["decision"] == "allow"


def test_a_rule_naming_the_runner_still_covers_every_proxy_tool():
    """Unchanged on purpose. Somebody who wrote this meant everything
    behind the runner, and a deny written that way must keep denying."""
    rules = [{"tool": "call_tool", "decision": "deny", "label": "no apps"}]
    for tool in (CREATE, "my-trello_create_card", "web-search_web_search"):
        got = ap.rule_decision(rules, "call_tool", _wrapped(tool))
        assert got is not None and got["decision"] == "deny", tool


def test_an_ordinary_tool_is_matched_as_before():
    rules = [{"tool": "send_*", "decision": "allow", "label": "mail"}]
    assert ap.rule_decision(rules, "send_email", {"to": "a@b.c"})["label"] == "mail"
    assert ap.rule_decision(rules, "delete_file", {}) is None


def test_argument_text_still_narrows_a_proxy_rule():
    """when_contains reads the arguments, and for a proxy call the real
    arguments are nested. A rule that only allows writes to one list has
    to keep working."""
    rules = [{"tool": CREATE, "decision": "allow",
              "when_contains": "901234", "label": "that list"}]
    got = ap.rule_decision(rules, "call_tool",
                           _wrapped(CREATE, {"list_id": "901234",
                                             "name": "x"}))
    assert got is not None and got["label"] == "that list"
    other = ap.rule_decision(rules, "call_tool",
                             _wrapped(CREATE, {"list_id": "555",
                                               "name": "x"}))
    assert other is None


def test_a_malformed_proxy_call_matches_nothing_new():
    rules = [{"tool": CREATE, "decision": "allow"}]
    for args in ({}, None, "not a dict", {"tool_name": 7},
                 {"tool_name": ""}, {"tool_name": "call_tool"}):
        assert ap.rule_decision(rules, "call_tool", args) is None, args


def test_the_form_says_a_service_pattern_is_allowed():
    """The capability is worth nothing if nobody knows the shape. The
    example sentence offered only native names, so "my-clickup_*" was
    unguessable."""
    said = ap.rule_problem("", "allow")
    assert "Name the tool" in said, said
    assert "my-" in said, said


def test_the_shape_worth_recommending_works_as_written():
    """Allow a service, deny the destructive part of it. This exact pair
    is what the board card tells Ralph to write, so it is pinned here
    rather than assumed to follow from the single-name case."""
    rules = [{"tool": "my-clickup_*", "decision": "allow", "label": "clickup"},
             {"tool": "my-clickup_delete_*", "decision": "deny",
              "label": "nothing destructive"}]
    for tool in ("my-clickup_delete_space", "my-clickup_delete_list",
                 "my-clickup_delete_task"):
        got = ap.rule_decision(rules, "call_tool", _wrapped(tool))
        assert got["decision"] == "deny", tool
    for tool in (CREATE, "my-clickup_update_task",
                 "my-clickup_create_list"):
        got = ap.rule_decision(rules, "call_tool", _wrapped(tool))
        assert got["decision"] == "allow", tool
