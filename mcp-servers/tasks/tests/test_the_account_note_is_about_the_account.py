# -*- coding: utf-8 -*-
"""The account note has to describe the account, not every app a person owns.

FOUND while hunting for a turn where Jev picks nothing, 2026-11-19: the
`account` tool was being handed over for requests that have nothing to do
with an account. Measured against the full 17-tool list, three runs each,
cut 0.75, it scored 0.91 to 0.93 on Shopify, Todoist, Instagram, YouTube,
n8n and Drive requests and was picked 3/3 on every one of them.

The note read:

    "the person's own account: their apps, connected services, usage and
     settings"

Two faults in one sentence. "their apps" and "connected services" match any
request that names an app the person owns, which is most of them. And
"usage and settings" is a claim no tool backs: account_summary.summarise
returns exactly `connected`, `not_connected` and `agents`, so an assistant
handed this tool for "change my settings" has nothing that changes a
setting. Same defect as the Drive note claiming folders.

MEASURED, three wordings, three runs each, cut 0.75:

                                            now       narrowed
  what apps am I connected to?              3/3 .96   3/3 .88
  is my Trello still connected?             3/3 .93   3/3 .83
  what agents do I have?                    3/3 .85   3/3 .88
  update the price of my Shopify product    3/3 .93   0/3 .14
  add a task in Todoist for Friday          3/3 .92   0/3 .22
  rename my n8n workflow                    3/3 .91   0/3 .07
  make a folder in my google drive          3/3 .93   0/3 .14
  how much have I used this month?          3/3 .91   0/3 .15
  change my settings                        3/3 .89   0/3 .19

  wrong: 8 of 11                            wrong: 0 of 11

The last two are in the drop column deliberately. No tool reports usage and
no tool changes a setting, so being picked for them is a promise the
assistant cannot keep, and a free-model answer that says plainly it was not
done is the better outcome.

These tests assert the wording, not a score, for the same reason as
test_the_router_says_what_an_app_can_make: scores move with the model and
the wording is ours.
"""
import agent_jev
import account_summary


NOTE = agent_jev.TOOL_NOTES["account"]


def test_the_note_says_what_the_summary_actually_returns():
    """connected, not connected and agents: all three, in plain words."""
    note = NOTE.lower()
    assert "connect" in note, note
    assert "not" in note, note
    assert "agent" in note, note


def test_the_note_does_not_promise_usage_or_settings():
    """summarise returns neither, so the tool cannot answer for them."""
    note = NOTE.lower()
    for word in ("usage", "setting", "billing", "plan"):
        assert word not in note, (
            "the account note promises %r, which summarise does not return "
            "and no account tool does" % word)


def test_the_note_rules_out_acting_inside_an_app():
    """The clause that stopped it winning six app requests out of six."""
    note = NOTE.lower()
    assert "not for" in note, (
        "without a clause ruling it out, this note matched any request "
        "naming an app the person owns: %r" % NOTE)
    assert "app" in note


def test_the_note_does_not_claim_the_apps_themselves():
    """"their apps" is what made every app request look like this tool."""
    assert "their apps," not in NOTE.lower(), NOTE


def test_the_summary_really_returns_only_those_three_things():
    """If summarise grows, this test is the reminder to widen the note.

    Asserting the shape rather than the prose, so a real capability change
    fails here instead of silently making the note false.
    """
    import inspect
    src = inspect.getsource(account_summary.summarise)
    assert '"connected"' in src and '"not_connected"' in src
    assert '"agents"' in src
    for claim in ("usage", "billing", "invoice"):
        assert claim not in src.lower(), (
            "summarise now returns %r, so the account note may widen" % claim)
