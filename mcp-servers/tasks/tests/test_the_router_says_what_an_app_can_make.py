# -*- coding: utf-8 -*-
"""An app named only in the half that says what the gateway can SEE is
unreachable for building anything.

MEASURED on the live router 2026-11-19, three runs each, cut 0.75:

    In n8n, create a workflow called "IO morning ping"...   0.72 0.74 0.71  0/3
    create an n8n workflow that calls an API every morning  0.58 0.63 0.59  0/3
    build me an n8n workflow                                0.68 0.67 0.66  0/3
    add an http request node to my n8n workflow             0.75 0.75 0.74  2/3
    what workflows do I have in n8n?                        0.94 0.94 0.93  3/3
    add a card to my trello board                           0.98 0.98 0.97  3/3

Reading is fine. BUILDING is under the cut on every phrasing, so the tool
is never handed over, the assistant never runs, and the free model answers
with no tools. On 2026-11-18 it answered the first of those messages with
three nodes, a cron expression and an offer to switch the workflow on. None
of it existed. The logs show no create_workflow call for that turn at all.

WHY, and it is not the name. "n8n workflows" is in the note, so
test_connected_apps_are_reachable passes. It is in the sentence listing
what the gateway can see. The sentence saying what can be MADE read "a new
table, board, list, page, record, event or issue", and a workflow is not
one of those, so the write tools shipped in #244 were unreachable from the
main chat the day after they shipped.

MEASURED AGAIN with the clause below, same day, same three runs: 0/3 to 3/3
on all four build phrasings (0.80 to 0.89), the two controls unmoved, and
nothing dragged in that should not be ("write me a poem" 0.03, "every
weekday at 9am email me a quote" still under the cut on the gateway and
still won by `schedules`).

THE RULE THIS LEAVES BEHIND: a thing the platform can make has to be named
in the making clause, not merely somewhere in the note. Same family as
test_connected_apps_are_reachable (the name) and
test_jev_notes_cover_listing (the verb), and this is the third time the
same shape has cost a shipped feature: `video` went 140 turns unpicked,
Trello answered "I don't have any tools available here" about an account
somebody had just connected, and now n8n reported building a workflow it
never built.

These tests assert the WORDING, not a score. Scores move with the model and
would make them flaky; the wording is ours and is the thing that was wrong.
"""
import re

import agent_jev
import mytools

#: A tool name that changes something, by its verb. `writes=True` is set on
#: eight tools out of hundreds, so it cannot be the test's basis.
WRITE_VERB = re.compile(r"^(create|make|new|add|post|send|update|move|"
                        r"delete|archive|activate|deactivate)_")

#: What each app's write tools make, in the words somebody would use for it.
#: Curated, like SPOKEN next door, and for the same reason: ClickUp alone
#: has forty write tools, and a clause naming every noun of theirs would be
#: unreadable and would get picked for anything. One or two words per app is
#: what the clause is for, because a model reads it to answer "is a tool for
#: this needed", not a parser.
#: Sending mail is deliberately NOT here: it is not making a thing, and the
#: note already says "sending mail from it" in its own right, which
#: test_sending_mail_keeps_its_own_verb holds on to.
#:
#: A zap and a branch ARE here, for accuracy rather than repair. I expected
#: both to be in the same hole as a workflow and MEASURED them instead:
#: "start my zapier zap" scored 0.78 and "create a branch in my github
#: repo" 0.96 against the old clause, both picked 3/3. Building a workflow
#: was the only thing actually unreachable.
MAKES = {
    "airtable": ("table", "record"),
    "clickup": ("task",),
    "github": ("issue", "pull request", "branch"),
    "hubspot": ("contact",),
    "jira": ("issue",),
    "linkedin": ("post",),
    "n8n": ("workflow",),
    "outlook": ("event",),
    "trello": ("card",),
    "zapier": ("zap",),
}


def _writers() -> list[str]:
    """Every provider with a tool that changes something."""
    return sorted(pid for pid, tools in mytools.PROVIDER_TOOLS.items()
                  if any(WRITE_VERB.match(t.name) for t in tools))


def _making() -> str:
    return " ".join(str(agent_jev.MAKES_CLAUSE).split()).lower()


def test_building_an_n8n_workflow_is_in_the_making_clause():
    """The measured one. Every other test here generalises it."""
    assert "workflow" in _making()


def test_the_other_things_an_n8n_workflow_tool_does_are_there_too():
    """create is not the whole of it: #244 shipped update, delete, activate
    and deactivate as well.

    This one is a guard, not a repair, and the measurement says so: "switch
    off my n8n workflow" scored 0.92 against the old clause and was picked
    3/3 without any of these words. Building was the broken verb. They are
    named because the next phrasing of them should not have to be lucky.

    Stems rather than whole words on purpose: the question is whether the
    capability is named at all, and asserting "changing" over "change"
    would fail on a rewording that kept every meaning."""
    making = _making()
    for verb in ("chang", "switch", "delet"):
        assert verb in making, verb


def test_sending_mail_keeps_its_own_verb():
    """Sending mail is not making a thing, so it is not in the clause. It
    has to stay in the note, or Outlook's send is unreachable the way
    building a workflow was."""
    note = " ".join(str(agent_jev.TOOL_NOTES["server:mcp-proxy"]).split())
    assert "sending mail" in note.lower()


def test_every_app_with_write_tools_says_what_it_makes():
    assert _writers(), "no provider has write tools; the test is measuring nothing"
    making = _making()
    missing = []
    for pid in _writers():
        for word in MAKES.get(pid, ()):
            if word not in making:
                missing.append("%s: %s" % (pid, word))
    assert missing == [], (
        "these apps can make something the making clause never names, so "
        "the router cannot pick a tool for building it: "
        + ", ".join(missing))


def test_a_new_write_tool_cannot_be_added_without_a_word_for_it():
    """Shipping a write capability and forgetting the clause is the exact
    shape of this bug, so an app the test has never heard of has to fail
    rather than be skipped."""
    unknown = [pid for pid in _writers() if pid not in MAKES]
    assert unknown == [], (
        "no word recorded for: " + ", ".join(unknown) + ". Add it to MAKES "
        "and name what it makes in the router's making clause.")


def test_the_making_clause_is_actually_in_the_note():
    """The clause is a constant so it can be asserted on directly. A
    constant that drifted out of the note would pass every test above and
    change nothing about what the router reads."""
    note = " ".join(str(agent_jev.TOOL_NOTES["server:mcp-proxy"]).split())
    assert " ".join(str(agent_jev.MAKES_CLAUSE).split()) in note


def test_the_clause_does_not_claim_what_no_tool_does():
    """The other direction, and it matters more here than in most places: a
    clause that overclaims gets the tool picked for work it cannot do, and
    the answer is then a different kind of lie. There is no tool that makes
    a repository or a base, and CLAUDE.md says so."""
    making = _making()
    for absent in ("repository", "repo", "base", "space"):
        assert absent not in making, absent
