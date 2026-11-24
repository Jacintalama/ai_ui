"""Needed, then pick one.

Standup 2026-11-23, on "I want people to fill the form from my website to be
saved into Airtable automatically": Airtable is required because they named
it, and the part that does it automatically is n8n, Zapier or the platform's
own Automations, their choice. Live 2026-11-24 the same message showed four
identical buttons and "Recommended: Zapier" under an answer that said only
n8n would do. Design: docs/superpowers/specs/2026-11-24-needed-and-pick-one-design.md
"""
import app_triage

MSG = ("I want people to fill the form from my website to be saved into "
       "Airtable automatically")


def _p(picks=(("airtable", .97), ("n8n", .95)), connected=(), tools=(),
       text=MSG):
    return app_triage.plan(list(picks), set(connected), list(tools),
                           text=text)


def test_automations_joins_the_choice_even_if_jev_did_not_pick_it():
    p = _p()
    assert p["choice"] == ["n8n", "zapier", "automations"]
    assert [x["id"] for x in p["platform"]].count("automations") == 1


def test_automations_picked_by_jev_is_not_added_twice():
    p = _p(picks=(("airtable", .97), ("n8n", .95), ("automations", .8)))
    assert p["choice"] == ["n8n", "zapier", "automations"]
    assert [x["id"] for x in p["platform"]].count("automations") == 1


def test_a_connected_n8n_or_zapier_settles_it():
    for have in ({"n8n"}, {"zapier"}):
        p = _p(connected=have)
        assert p["choice"] == [], have
        assert "automations" not in [x["id"] for x in p["platform"]], have


def test_a_timer_job_has_no_choice():
    p = _p(tools=["schedules"], text="every 8am save my email to Airtable")
    assert p["choice"] == []


def test_the_named_app_is_marked_named():
    named = {a["id"]: a["named"] for a in _p()["apps"]}
    assert named["airtable"] is True and named["zapier"] is False


# --- what is written under the answer ----------------------------------------

#: Captured from main (4414b6e96) before this change: with no choice in the
#: plan the output must not move.
BEFORE = ("Here is how.\n\nRecommended: Airtable, so IO can read your bases, "
          "tables and rows, make a new table, add rows and change a row (it "
          "cannot yet make a new base, delete a table or a row, or change a "
          "column's type once it exists, such as turning a text column into a "
          "dropdown).\n[Connect Airtable](#aiui-connect:airtable)")


def _out(answer="Here is how.", **kw):
    return app_triage.with_buttons(answer, _p(**kw))


def _line(out, text):
    return next(l for l in out.splitlines() if text in l)


def test_the_named_app_reads_as_needed_with_its_own_button():
    out = _out()
    assert "#aiui-connect:airtable" in _line(
        out, "You need Airtable, because you asked for it.")
    assert "#aiui-connect:airtable" not in out.rstrip().splitlines()[-1]


def test_the_three_are_one_pick_with_their_own_row():
    lines = _out().rstrip().splitlines()
    assert lines[-2] == ("To do it automatically, pick one: n8n, Zapier or "
                         "Automations.")
    assert lines[-1] == ("[Connect n8n](#aiui-connect:n8n) "
                         "[Connect Zapier](#aiui-connect:zapier) "
                         "[Set up in AI Agents](#aiui-open:ai-agents)")


def test_a_choice_has_no_recommended_zapier_and_no_webhook():
    out = _out()
    assert "Recommended: Zapier" not in out
    assert "webhook" not in out.lower()


def test_an_app_not_named_keeps_the_recommended_line():
    out = _out(text="save every form entry from my site automatically")
    assert "#aiui-connect:airtable" in _line(out, "Recommended: Airtable")


def test_two_named_apps_are_two_needed_lines():
    out = _out(picks=(("airtable", .97), ("gmail", .96), ("n8n", .95)),
               text="save my Gmail attachments into Airtable automatically")
    assert "#aiui-connect:gmail" in _line(out, "You need Gmail")
    assert "#aiui-connect:airtable" in _line(out, "You need Airtable")


def test_a_button_the_answer_already_wrote_is_not_repeated():
    out = _out(answer="Connect it: [Connect n8n](#aiui-connect:n8n)")
    assert out.count("#aiui-connect:n8n") == 1


def test_publish_beside_the_choice_is_not_in_the_pick_row():
    out = _out(picks=(("airtable", .97), ("n8n", .95), ("publish", .8)))
    assert "#aiui-open:app-builder" in out
    assert "#aiui-open:app-builder" not in out.rstrip().splitlines()[-1]


def test_without_a_choice_the_output_is_unchanged():
    p = app_triage.plan([("airtable", .97)], set(), [])
    assert app_triage.with_buttons("Here is how.", p) == BEFORE


# --- what the assistant is told ----------------------------------------------

def _with_skill():
    import agent_skills
    pool = agent_skills.load_all(refresh=True)
    return app_triage.plan([("airtable", .97), ("n8n", .95)], set(), [],
                           text=MSG, skills=[("build-a-workflow", .95)],
                           pool=pool)


def test_the_brief_offers_the_choice_before_the_skill():
    b = app_triage.brief(_with_skill())
    assert "Needed for this: Airtable." in b
    assert "choice of three" in b and "Do not pick one for them" in b
    assert b.index("choice of three") < b.index("Follow the ready-made skill")
    assert "webhook" not in b.split("Follow the ready-made skill")[0].lower()


def test_the_brief_without_a_choice_says_nothing_of_one():
    b = app_triage.brief(app_triage.plan([("airtable", .97)], set(), []))
    assert "choice of three" not in b


def test_no_platform_line_is_left_with_nothing_above_it():
    """Automations moved into the choice line; "Do not write a link to it"
    was left behind with no "it"."""
    b = app_triage.brief(_p())
    assert "Do not write a link to it" not in b
