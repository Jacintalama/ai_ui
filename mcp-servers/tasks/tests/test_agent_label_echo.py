"""An agent must not learn the speaker labels from its own history.

Rendered replies carry "Ada:" and "Mia:" lines so a person can see who spoke.
Fed back as history, those same lines taught the model a format: it began
prefixing its own answers with a name, and then writing whole made up
exchanges between the agents. Seen live 2026-09-04, where Ada's reply to
"hi how it going team" contained a fake reply from Mia.

Two halves. History is cleaned of labels before an agent sees it, and an
answer is stripped of any label lines it opens with, because the renderer
is about to add the real one.
"""
import pytest

import agent_routing as ar

NAMES = ["Ada", "Mia"]


def test_labels_are_removed_from_history_and_words_are_kept():
    rendered = "Ada:\nhello there\n\nMia:\nhi back"
    assert ar.strip_label_lines(rendered, NAMES) == "hello there\n\nhi back"


def test_only_known_agent_names_are_treated_as_labels():
    """A reply genuinely opening with "Note:" on its own line is the
    agent's words, not a speaker label."""
    assert ar.strip_label_lines("Note:\nkeep this", NAMES) == "Note:\nkeep this"
    assert ar.strip_leading_labels("Warning:\nkeep this", NAMES) == "Warning:\nkeep this"


def test_a_name_inside_a_sentence_is_not_a_label():
    text = "Ask Mia: she knows the inbox."
    assert ar.strip_label_lines(text, NAMES) == text


@pytest.mark.parametrize("raw", ["Mia:\nanswer", "MIA:\nanswer", "  Mia :  \nanswer",
                                 "Ada:\nMia:\nanswer", "\n\nAda:\n\nanswer"])
def test_an_answer_that_echoes_a_label_loses_only_the_leading_ones(raw):
    assert ar.strip_leading_labels(raw, NAMES) == "answer"


def test_a_label_in_the_middle_of_an_answer_is_the_agents_own_words():
    """Only the top is stripped. Clean history is what stops the model
    inventing a label mid answer; this function is not meant to hide it."""
    raw = "First part.\n\nMia:\nsecond part"
    assert ar.strip_leading_labels(raw, NAMES) == raw


def test_history_cleaning_touches_assistant_turns_only():
    history = [
        {"role": "user", "content": "Mia:\nthis is what the person typed"},
        {"role": "assistant", "content": "Mia:\nthis is what Mia said"},
        {"role": "user", "content": "thanks"},
    ]
    cleaned = ar.clean_history_for_agent(history, NAMES)
    assert cleaned[0]["content"] == "Mia:\nthis is what the person typed"
    assert cleaned[1]["content"] == "this is what Mia said"
    assert cleaned[2]["content"] == "thanks"
    # The caller's list is never mutated in place.
    assert history[1]["content"].startswith("Mia:")


def test_no_agents_means_nothing_is_stripped():
    assert ar.strip_label_lines("Ada:\nhello", []) == "Ada:\nhello"
    assert ar.strip_leading_labels("Ada:\nhello", []) == "Ada:\nhello"


@pytest.mark.parametrize("bad", [None, 5, [], {}])
def test_nothing_here_ever_raises(bad):
    assert ar.strip_label_lines(bad, NAMES) == ""
    assert ar.strip_leading_labels(bad, NAMES) == ""
    assert ar.clean_history_for_agent(bad, NAMES) == []


# The rendered reply now puts the name in bold on its own line rather than
# "Ada:" in plain text, because Open WebUI shows one tool reply as exactly one
# message and the only thing left to fix was whether that message reads as two
# speakers. Everything above must hold for the new shape too, and for the old
# one, since a live conversation can contain both.

def test_the_rendered_reply_names_each_speaker_in_bold():
    from routes_agent_turn import render_turns
    out = render_turns([
        {"agent": {"id": "a", "name": "Ada"}, "answer": "hello there"},
        {"agent": {"id": "m", "name": "Mia"}, "answer": "hi back"},
    ])
    assert out == "**Ada**\n\nhello there\n\n**Mia**\n\nhi back"
    assert "Ada:" not in out and "Mia:" not in out


def test_a_turn_with_no_agent_is_still_shown_bare():
    from routes_agent_turn import render_turns
    assert render_turns([{"agent": None, "answer": "just me"}]) == "just me"


def test_the_bold_labels_are_removed_from_history_and_words_are_kept():
    rendered = "**Ada**\n\nhello there\n\n**Mia**\n\nhi back"
    assert ar.strip_label_lines(rendered, NAMES) == "hello there\n\nhi back"


def test_history_from_before_the_format_changed_is_still_cleaned():
    """A conversation that started on the old renderer holds old lines above
    new ones. An agent must see neither."""
    mixed = "Ada:\nolder turn\n\n**Mia**\n\nnewer turn"
    assert ar.strip_label_lines(mixed, NAMES) == "older turn\n\nnewer turn"


def test_an_answer_that_opens_with_a_bold_label_loses_it():
    assert ar.strip_leading_labels("**Ada**\n\nmy answer", NAMES) == "my answer"


def test_bold_text_that_is_not_an_agent_name_is_kept():
    """Only known agent names are labels. An agent writing **Note** or
    **Summary** as a heading is writing, not labelling."""
    assert ar.strip_label_lines("**Note**\n\nkeep this", NAMES) == "**Note**\n\nkeep this"
    assert ar.strip_leading_labels("**Summary**\n\nkeep this", NAMES) == "**Summary**\n\nkeep this"


def test_a_bold_name_inside_a_sentence_is_the_agents_own_words():
    kept = "I checked with **Ada** and she agrees"
    assert ar.strip_label_lines(kept, NAMES) == kept


def test_the_rendered_reply_survives_a_round_trip_through_cleaning():
    """The whole point, end to end: what a person reads carries the names,
    and what the next agent reads carries none of them."""
    from routes_agent_turn import render_turns
    rendered = render_turns([
        {"agent": {"id": "a", "name": "Ada"}, "answer": "hello there"},
        {"agent": {"id": "m", "name": "Mia"}, "answer": "hi back"},
    ])
    history = [{"role": "user", "content": "hi team"},
               {"role": "assistant", "content": rendered}]
    cleaned = ar.clean_history_for_agent(history, NAMES)
    assert "Ada" not in cleaned[1]["content"]
    assert "Mia" not in cleaned[1]["content"]
    assert "hello there" in cleaned[1]["content"]
    assert "hi back" in cleaned[1]["content"]


# An agent that does not know its own name is worse than one with no history:
# asked "where is Ada", Ada answered that Ada was somebody else. The labels
# are stripped from what it reads, so the name has to arrive some other way.

def test_an_agent_is_told_its_own_name():
    from routes_agent_turn import _identity_line
    line = _identity_line({"id": "agent-a", "name": "Ada"}, ["Ada", "Mia"])
    assert line["role"] == "system"
    assert "You are Ada" in line["content"]
    assert "Mia" in line["content"], "it should know who else is here"
    assert "Ada, Mia" not in line["content"], "it must not be listed as its own peer"


def test_the_identity_line_forbids_the_two_things_that_went_wrong():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    # Writing another agent's reply is the invented-exchange bug.
    assert "Never answer for them" in said
    # Prefixing its own name is the double-label bug; the renderer adds it.
    assert "Do not put your own name at the start" in said


def test_an_only_agent_is_not_told_about_company_it_does_not_have():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada"])["content"]
    assert "You are Ada" in said
    assert "other assistants" not in said


def test_an_agent_with_no_name_still_gets_a_line():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "agent-x"}, [])["content"]
    assert "agent-x" in said


# The brief also has to make an agent WORK. Asked "who has all my app
# connections" it guessed a number; asked "do you have any work today" it
# offered to help rather than looking. Both were seen live.

def test_the_brief_says_to_use_the_tools_rather_than_describe_them():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert "use a tool and answer from what it returns" in said
    assert "Never state a number or a name you have not looked up" in said
    assert "instead of doing it" in said


def test_the_brief_says_the_others_are_software_not_colleagues():
    """Mia read "hi team what is your task today" as a question about human
    colleagues and suggested asking them."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert "not this person's colleagues" in said
    assert "team or everyone they mean you" in said


def test_the_brief_bans_the_boilerplate_that_was_actually_said():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada"])["content"]
    assert "help with a variety of tasks" in said, "the exact non-answer given"
    assert "Do not close with an offer of further help" in said


def test_the_brief_stays_short_enough_to_send_every_turn():
    """It rides in front of every turn for every agent, so it is paid for on
    every message. A page of rules would cost more than it saves.

    Raised from 1400 to 2100 when the repetition rules went in: an agent
    re-printing a list it had already printed, after being told it was not
    needed, was worth more than the tokens the instruction costs. Raise this
    again only for something that has actually gone wrong in front of
    somebody, not for a rule that seems like a good idea."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert len(said) < 2100, len(said)


def test_the_brief_says_not_to_repeat_itself():
    """Seen live: a whole inbox digest, then "no need to reply on that", then
    "Got it", then the identical digest again on the next question."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada"])["content"]
    assert "Do not say again what you have already said" in said
    assert "that settles it" in said
    assert "Answer the question they actually asked" in said


def test_the_brief_points_at_the_remembering_tool():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada"])["content"]
    assert "tool for remembering" in said


# A role is a job, not a caption. It is typed by the owner on the card, and if
# it only ever reached the card it would be decoration: asked what she does,
# Ada would still answer as a generic assistant. So it arrives in the brief.

def test_an_agent_is_told_its_role():
    from routes_agent_turn import _identity_line
    said = _identity_line(
        {"id": "a", "name": "Ada", "meta": {"role": "Project manager"}},
        ["Ada", "Mia"])["content"]
    assert "You are Ada, this person's project manager." in said


def test_a_role_is_lower_cased_but_an_initialism_is_left_alone():
    """Typed into a form, a role arrives capitalised ("Project manager"), and
    it is interpolated mid sentence where a capital reads as a proper noun.
    Lower-casing the first letter fixes that, but blanket .lower() would turn
    QA lead into qa lead."""
    from routes_agent_turn import _identity_line
    said = _identity_line(
        {"id": "a", "name": "Ada", "meta": {"role": "QA lead"}}, ["Ada"])["content"]
    assert "You are Ada, this person's QA lead." in said


def test_an_agent_with_no_role_keeps_the_line_it_had():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada"])["content"]
    assert "You are Ada, one of this person's own assistants." in said
    assert "this person's ." not in said
    assert "None" not in said


def test_a_junk_role_is_ignored_rather_than_pasted_into_the_brief():
    """meta comes from a database row that a model-facing API writes, so the
    value is not guaranteed to be a short string, or a string at all."""
    from routes_agent_turn import _identity_line
    for junk in (123, [], {"a": 1}, "", "   "):
        said = _identity_line(
            {"id": "a", "name": "Ada", "meta": {"role": junk}}, ["Ada"])["content"]
        assert "You are Ada, one of this person's own assistants." in said


def test_a_long_role_is_cut_rather_than_allowed_to_run_the_brief():
    from routes_agent_turn import _identity_line
    said = _identity_line(
        {"id": "a", "name": "Ada", "meta": {"role": "x" * 500}}, ["Ada"])["content"]
    assert "x" * 200 not in said
