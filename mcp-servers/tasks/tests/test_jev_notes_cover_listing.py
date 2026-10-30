"""A tool's note has to mention listing, or the router never picks it for
"what have I got".

Measured against the live router on 2026-10-30, not reasoned about. Jev scores
each tool separately against its note in TOOL_NOTES and keeps the ones at or
above 0.75, so the note is the entire basis for the decision. The pattern was
exact:

    automations  "making, listing, pausing or deleting them"   -> picked
    video        "making a video"                              -> 0 of 140

`video` had never been picked once in 140 recorded turns. Not because the
router was broken and not because of a missing grant, but because its note
described making a video and nothing else, so "what videos have I made"
matched nothing. After the note named listing it scored 0.95 three times out
of three. `documents` went the same way, 0.94.

Why this matters more than a missed tool: when nothing clears the cut the
free model answers instead, and it cannot see the person's account. So it
invents an answer about their own videos or documents. That is the same
failure that produced a confident "Crane is now active" for an agent that was
never created.

This test is deliberately about the NOTE, not about a score. Scores move with
the model and would make this flaky; the wording is ours and is the thing that
was wrong.
"""
import re

import agent_jev


#: Tools whose feature can show the person a list of their own things. Each
#: is a question somebody actually asks: "what videos have I made", "list my
#: automations", "what documents do I have".
LISTS_THINGS = ["video", "documents", "schedules", "automations", "skills",
                "agent_builder"]

#: Any of these in a note is enough. A note may say "listing" or "finding" or
#: "what they have"; the point is that retrieval is named at all, not that a
#: particular word is used.
NAMES_RETRIEVAL = ("listing", "list", "finding", "find", "showing",
                   "they have", "recalling", "looking")


def _note(tool_id):
    return " ".join(str(agent_jev.TOOL_NOTES.get(tool_id, "")).split())


def test_every_tool_that_can_list_says_so():
    """The rule the measurement produced. A tool that can show the person
    their own things must say so, or it is unreachable for the commonest
    question anyone asks about it."""
    silent = [t for t in LISTS_THINGS
              if not any(w in _note(t).lower() for w in NAMES_RETRIEVAL)]
    assert silent == [], (
        "these notes describe only making the thing, so the router cannot "
        "pick them for 'what have I got': " + ", ".join(silent))


def test_video_names_more_than_making_one():
    """The one that proved the rule: 0 picks in 140 turns on 'making a
    video'."""
    note = _note("video").lower()
    assert "video" in note
    assert note != "making a video"
    assert any(w in note for w in NAMES_RETRIEVAL)


def test_documents_is_about_documents_here_not_drive():
    """'list my documents' used to reach gdrive, which is a different place.
    Drive is the person's Google Drive; documents are what they uploaded or
    had made here."""
    assert "upload" in _note("documents").lower()


def test_schedules_still_separates_itself_from_the_calendar():
    """`schedule` is a calendar word in ordinary English, and the calendar
    tool wins the ambiguous readings. The note has to say what it is not,
    or 'list my schedules' lands on meetings."""
    note = _note("schedules").lower()
    assert "timer" in note or "cron" in note
    assert "calendar" in note, "the note must name what it is NOT"


def test_every_installed_tool_has_a_note():
    """A tool with no note cannot be picked at all, and nothing else would
    say so: it would simply never appear."""
    missing = [t for t in LISTS_THINGS if not _note(t)]
    assert missing == [], "no note, so never picked: " + ", ".join(missing)


#: Worth knowing and NOT asserted here: rewriting the skills note from 12
#: words to a longer, more self-referential 26 dropped its score from 0.60 to
#: 0.38, measured three times each. But `automations` is 31 words and scores
#: among the best, so length is plainly not the variable and there is no rule
#: here to pin yet. Recorded so the next person does not read "longer is
#: worse" into it.


def test_a_note_never_leaks_a_tool_id_as_jargon():
    """The note is read by a model judging a person's plain sentence. An
    underscore id in the prose is a tell that the note was written for us
    rather than for the question being asked."""
    leaky = [t for t in agent_jev.TOOL_NOTES
             if re.search(r"\b[a-z]+_[a-z]+\b", _note(t))]
    assert leaky == [], "tool ids in the prose: " + ", ".join(leaky)
