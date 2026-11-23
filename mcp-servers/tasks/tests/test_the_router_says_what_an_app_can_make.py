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
    "asana": ("task",),
    "clickup": ("task",),
    "github": ("issue", "pull request", "branch"),
    "hubspot": ("contact",),
    "jira": ("issue",),
    "linear": ("issue",),
    "linkedin": ("post",),
    "n8n": ("workflow",),
    "outlook": ("event",),
    "todoist": ("task",),
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


def test_linking_aiui_into_n8n_is_in_the_making_clause():
    """`link_aiui` (#262) saves an AIUI key in the person's n8n so their
    workflows can use the apps connected here. The clause never said so.

    MEASURED on the live router 2026-11-20, server:mcp-proxy against the
    full tool list, cut 0.75, three runs each:

                                                    before        after
      Link AIUI to my n8n                           0.74 0.74     0.91 0.91 0.90
      connect AIUI to my n8n                        0.75 0.72     0.89 0.89 0.90
      set up AIUI in my n8n so my workflows can
        use my Google Drive                         0.54 0.58     0.80 0.79 0.80
      let my n8n workflows use the apps I
        connected here                              0.51 0.54     0.87 0.88 0.88
      put the AIUI credential in my n8n             0.85 0.84     0.92 0.92 0.91

    Before, "Link AIUI to my n8n" tied with the account tool at 0.74, and
    on 2026-11-19 the live chat answered from the account ("Used your
    account") that the bridge "does not exist yet". The account note was
    left alone: adding "not for linking AIUI" to it dropped "is my Trello
    still connected?" from 0.82 to 0.76, too near the cut. Its own nine
    cases (test_the_account_note_is_about_the_account) were unchanged by
    this wording, 3/3 and 0/3 exactly as before."""
    making = _making()
    assert "aiui" in making
    for verb in ("link", "connect", "set up"):
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


# ---------------------------------------------------------------------------
# The same rule, for a tool that has its OWN note rather than the gateway's.
#
# MEASURED on the live router 2026-11-19, three runs each, cut 0.75, probing
# gdrive/gmail/calendar/documents/server:mcp-proxy side by side so the score
# is read off the tool that actually serves Drive:
#
#   find the recruiting spreadsheet in my drive     gdrive 0.97 0.97 0.97  3/3
#   open the Q3 report from my google drive         gdrive 0.97 0.97 0.97  3/3
#   what files are in my google drive?              gdrive 0.97 0.96 0.97  3/3
#   make a folder called Invoices in my drive       gdrive 0.10 0.10 0.10  0/3
#   upload this to my google drive                  gdrive 0.15 0.13 0.14  0/3
#
# FIXING IT TOOK THREE WORDINGS, and the two that failed are the reason
# this test checks listing as well as saving. Bolting ", and saving or
# uploading a new file into it" onto the end of the old sentence lifted
# every write to 3/3 and dropped "what files are in my google drive?" from
# 0.97 to 0.60 and "open the Q3 report" to 0.73, both out of the pick.
# Adding "listing" but shortening the write clause was worse still, 0/3 on
# all three reads. Naming the app first and hanging every verb off it
# carries both: writes 0.94 to 0.96, reads 0.93 to 0.96, nothing dragged in
# ("what is on my calendar tomorrow?" 0.03, a poem 0.02).
#
# Reading is near perfect. Writing scores 0.10, which is not a near miss,
# it is the note being read correctly: "finding or reading files, documents
# and spreadsheets" names no write at all. So the one write Drive really
# has, gdrive_create_file, could not be reached from the main chat, and
# nothing else caught it either: `documents` peaked at 0.70 and the gateway
# at 0.33, so no tool was handed over and the free model answered.
#
# WHAT DRIVE REALLY DOES, read off mcp-servers/gdrive/main.py rather than
# assumed: gdrive_list_files, gdrive_search_files, gdrive_read_file,
# gdrive_get_file_info and gdrive_create_file. That last one takes a name,
# text or base64 content and a mime type. There is no parent folder field
# and no folder endpoint, so Drive can save a file and cannot make a
# folder, cannot move, rename, delete or share one. The note has to say the
# first and must not claim the rest.
# ---------------------------------------------------------------------------

#: The stems a person's own words would use for putting a file into Drive.
DRIVE_SAVE = ("sav", "upload", "put a new file")

#: What no Drive endpoint does. Claiming any of these would send a request
#: to a tool that cannot carry it, which is worse than not being picked.
DRIVE_CANNOT = ("folder", "delete", "rename", "share")


def test_drive_says_it_can_save_a_file():
    """gdrive_create_file exists, so the note has to name it."""
    note = agent_jev.TOOL_NOTES["gdrive"].lower()
    assert any(s in note for s in DRIVE_SAVE), (
        "the gdrive note names no write verb, so 'upload this to my google "
        "drive' scores 0.15 and the tool is never handed over: %r" % note)


def test_drive_does_not_claim_what_it_cannot_do():
    """No folder endpoint exists, so the note must not promise one."""
    note = agent_jev.TOOL_NOTES["gdrive"].lower()
    for word in DRIVE_CANNOT:
        assert word not in note, (
            "the gdrive note claims %r, which no Drive endpoint does" % word)


def test_drive_keeps_the_reading_words_that_already_work():
    """The read phrasings score 0.97. Nothing here may cost that."""
    note = agent_jev.TOOL_NOTES["gdrive"].lower()
    for word in ("find", "list", "read", "file", "spreadsheet",
                 "google drive"):
        assert word in note, "the gdrive note lost %r" % word
