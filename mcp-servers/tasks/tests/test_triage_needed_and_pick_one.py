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
