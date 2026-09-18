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
    somebody, not for a rule that seems like a good idea.

    Raised from 2100 to 2250 on 2026-09-14 for the long-dash rule, which
    clears that bar: the owner sent a screenshot of his own agents using the
    dash he has a standing rule against. The rule was written twice and cut
    to two lines before this rose, so it is the smallest rise that fits."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert len(said) < 2250, len(said)


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


def test_every_agent_is_told_not_to_use_long_dashes():
    """Ralph's standing rule, and he reported his own agents breaking it with
    a screenshot. Put in the shared identity line rather than in seven briefs,
    so it reaches every agent on every surface, including ones made later.

    The characters are shown literally because "avoid em-dashes" does not
    survive a model that cannot tell which key that is. The words "em-dash"
    and "en-dash" are deliberately NOT in the brief: they were cut to stay
    inside the length budget, and showing the character is what does the work.
    """
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert "\u2014" in said, "the em-dash itself is not shown"
    assert "\u2013" in said, "the en-dash itself is not shown"
    assert "long dashes" in said, "nothing names what they are"


def test_the_brief_does_not_itself_contain_a_stray_long_dash():
    """It would be teaching the format it forbids. The two in the rule are
    deliberate, so count them rather than banning them."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert said.count("\u2014") == 1, "an em-dash outside the rule itself"
    assert said.count("\u2013") == 1, "an en-dash outside the rule itself"


# ---------------------------------------------------------------------------
# Measured 2026-09-14 in the owner's panel, asked to fix the shoe app: Mia
# (Gmail only), Nora (calendar) and Iris (Drive) each offered to bug-hunt it,
# because the brief told every agent it had tools for mail, files, apps,
# connections, schedules and saved notes. Iris also claimed she had added the
# new page, which Ada did: history carries no speaker names.
# ---------------------------------------------------------------------------


def test_a_narrowed_agent_is_told_only_the_tools_it_has():
    from routes_agent_turn import _identity_line
    mia = {"id": "m", "name": "Mia",
           "meta": {"toolIds": ["gmail"], "toolScope": "picked"}}
    said = _identity_line(mia, ["Mia", "Kai"])["content"]
    assert "Your tools reach email, and nothing else" in said, said
    assert "files, apps, connections" not in said
    assert "never offer to do it" in said
    assert "find_skills" not in said, "told to call a tool it does not have"
    assert "tool for remembering" not in said, "told to use memory it lacks"


def test_a_narrowed_agent_names_each_of_its_tools():
    from routes_agent_turn import _identity_line
    nora = {"id": "n", "name": "Nora",
            "meta": {"toolIds": ["calendar", "remember"], "toolScope": "picked"}}
    said = _identity_line(nora, ["Nora"])["content"]
    assert "Your tools reach the calendar and saved notes" in said, said
    assert "tool for remembering" in said, "it does hold memory"


def test_an_unnarrowed_agent_keeps_the_general_lines():
    """Absent scope still means everything, so nothing is taken away from an
    agent that predates narrowing."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert "real account" in said
    assert "find_skills" in said
    assert "tool for remembering" in said


def test_picked_with_nothing_ticked_still_means_everything():
    """The same rule as tools_for_agent: picking nothing is not a request for
    nothing, so the brief must not tell it that it reaches nothing."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada", "meta": {
        "toolIds": [], "toolScope": "picked"}}, ["Ada"])["content"]
    assert "real account" in said
    assert "and nothing else" not in said


def test_an_agent_is_told_what_the_others_are_for():
    """Asked "who handles coding?", Kai said he did, Ada said Kai led it and
    Rex also worked on it, and Rex said he did (Ralph's screenshot,
    2026-09-18). None of them was lying: the brief listed the others by name
    and never said what any of them was for, so each filled the gap from its
    own instructions."""
    from routes_agent_turn import _identity_line
    roster = [
        {"id": "k", "name": "Kai", "meta": {"role": "App reviewer"}},
        {"id": "r", "name": "Rex", "meta": {"role": "Programmer"}},
        {"id": "a", "name": "Ada", "meta": {"role": "Project manager"}},
    ]
    said = _identity_line(roster[0], [a["name"] for a in roster],
                          roster=roster)["content"]
    assert "Rex (programmer)" in said
    assert "Ada (project manager)" in said
    assert "Kai (" not in said, "an agent is not one of its own others"


def test_a_roster_entry_with_no_role_is_still_just_a_name():
    """Most agents predate the role field, and every surface that has only
    names still passes those. A bare name has to read exactly as before."""
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "a", "name": "Ada"}, ["Ada", "Mia"])["content"]
    assert "The other assistants here are Mia." in said


def test_an_agent_is_told_not_to_claim_another_agents_work():
    from routes_agent_turn import _identity_line
    said = _identity_line({"id": "i", "name": "Iris"}, ["Iris", "Ada"])["content"]
    assert "unless you did it in this reply" in said


import pytest as _pytest


@_pytest.mark.parametrize("before, after", [
    ("I'm here \u2014 what do you need?", "I'm here, what do you need?"),
    ("Sep 7\u201311, 2026", "Sep 7-11, 2026"),
    ("2026-09-07 \u2014 2026-09-11", "2026-09-07 to 2026-09-11"),
    ("\u2014 first\n\u2014 second", "- first\n- second"),
    ("Done \u2014\nnext", "Done\nnext"),
    ("a \u2014.", "a."),
    ("no dashes here, a-b stays", "no dashes here, a-b stays"),
    # Code is pasted into files, so it comes back exactly as written.
    ("Put this in:\n```html\n<title>Shoe — Landing</title>\n```\ndone — ok",
     "Put this in:\n```html\n<title>Shoe — Landing</title>\n```\ndone, ok"),
    ("run `echo a—b` — then check", "run `echo a—b`, then check"),
    ("```\nunclosed — block", "```\nunclosed — block"),
])
def test_long_dashes_are_scrubbed_from_what_an_agent_says(before, after):
    import agent_routing
    assert agent_routing.scrub_long_dashes(before) == after


def test_scrubbing_leaves_non_text_alone():
    import agent_routing
    assert agent_routing.scrub_long_dashes(None) is None


async def test_every_turn_is_scrubbed_whatever_the_model_did(monkeypatch):
    """The brief asks. This is what guarantees it, on every surface that goes
    through _turn_for: the panel, the gateway, and the agents page."""
    import routes_agent_turn as rt

    async def fake_run(email, agent_id, history):
        return {"answer": "I'm here \u2014 what do you need?", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    out = await rt._turn_for("me@example.com", {"id": "a", "name": "Ada"},
                             [{"role": "user", "content": "hi"}], ["Ada"])
    assert out["answer"] == "I'm here, what do you need?", out["answer"]
