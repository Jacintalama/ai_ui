"""The triage recommends the platform's own parts, each with a button
(Lukas, 2026-11-16: "you said automation and it recommended Zapier and n8n.
That's what I would like for the other parts, like the app builder").

Design: docs/plans/2026-11-17-triage-connect-and-continue-design.md.
"""
import re

import agent_jev
import app_triage

PLACES = {"app_builder": "app-builder", "cron_jobs": "cronjobs",
          "ai_agents": "ai-agents", "automations": "ai-agents",
          "video": "video-generation", "channels": "channel"}


def test_each_part_of_the_platform_is_in_the_catalogue():
    for pid, place in PLACES.items():
        feat = app_triage.PLATFORM[pid]
        assert feat.opens == place, pid
        assert feat.button, pid
        assert feat.how and feat.note, pid


def test_every_place_a_button_opens_is_one_the_page_allows():
    assert set(app_triage.OPEN_PLACES) == {
        "app-builder", "cronjobs", "ai-agents", "video-generation", "channel"}
    for feat in app_triage.PLATFORM.values():
        assert feat.opens in app_triage.OPEN_PLACES, feat.id


def test_the_page_allows_the_same_places_and_no_others():
    """integrations-ui.js keeps its own copy; the two must not drift."""
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[2] / "gdrive"
          / "integrations-ui.js").read_text(encoding="utf-8")
    block = js[js.index("var AIUI_OPEN_PLACES"):]
    block = block[:block.index("};")]
    assert set(re.findall(r"'([a-z-]+)':", block)) == set(app_triage.OPEN_PLACES)


def test_the_new_parts_are_asked_about_in_the_same_jev_call():
    ids = app_triage.catalogue_ids()
    _state, questions = agent_jev.apps_request("remind me every Monday at 9")
    assert len(questions) == len(ids)
    for pid in PLACES:
        q = questions["a%d" % ids.index(pid)]["instructions"]
        assert app_triage.PLATFORM[pid].label in q
        assert "the platform's own feature" in q


def test_a_cron_job_answer_gets_an_open_cron_jobs_button():
    p = app_triage.plan([("cron_jobs", 0.9)], set(), ["schedules"])
    out = app_triage.with_buttons("Done, it runs every Monday at 9.", p)
    assert out.rstrip().endswith("[Open Cron Jobs](#aiui-open:cronjobs)")


def test_the_hosting_rule_is_only_said_for_hosting():
    cron = app_triage.brief(app_triage.plan([("cron_jobs", 0.9)], set(), []))
    assert "hosting" not in cron.lower()
    pub = app_triage.brief(app_triage.plan([("publish", 0.9)], set(), []))
    assert "Do not suggest other hosting services or sites." in pub


def test_building_rules_out_other_site_builders():
    b = app_triage.brief(app_triage.plan([("app_builder", 0.9)], set(), []))
    assert app_triage.PLATFORM["app_builder"].rule in b
    assert "site builder" in app_triage.PLATFORM["app_builder"].rule.lower()


def test_two_parts_that_open_the_same_page_make_one_button():
    p = app_triage.plan([("ai_agents", 0.9), ("automations", 0.85)], set(), [])
    out = app_triage.with_buttons("Make an agent, then an automation.", p)
    assert out.count("#aiui-open:ai-agents") == 1


def test_build_and_publish_together_make_one_app_builder_button():
    p = app_triage.plan([("app_builder", 0.9), ("publish", 0.8)], set(), [])
    out = app_triage.with_buttons("Build it, then Publish it.", p)
    assert out.count("#aiui-open:app-builder") == 1


def test_ios_own_automations_sit_beside_n8n_and_zapier():
    """Lukas's own example: automation shows the choice, IO's own included."""
    p = app_triage.plan([("n8n", 0.95), ("automations", 0.8)], set(), [])
    assert [a["id"] for a in p["apps"]] == ["n8n", "zapier"]
    assert [x["id"] for x in p["platform"]] == ["automations"]
    out = app_triage.with_buttons("Here are your options.", p)
    last = out.rstrip().splitlines()[-1]
    for href in ("#aiui-connect:n8n", "#aiui-connect:zapier",
                 "#aiui-open:ai-agents"):
        assert href in last


def test_a_reply_that_opened_a_place_counts_as_offered_for_that_part():
    msgs = [{"role": "user", "content": "remind me every Monday"},
            {"role": "assistant",
             "content": "Done. [Open Cron Jobs](#aiui-open:cronjobs)"},
            {"role": "user", "content": "thanks"}]
    assert "cron_jobs" in app_triage.already_offered(msgs)


def test_how_lines_name_only_real_pages():
    """Each how-line names the page its button opens by its sidebar label,
    read from task-panel.js itself (review 2026-11-17: a copied dict here
    would not notice the sidebar changing)."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "static"
           / "task-panel.js").read_text(encoding="utf-8")
    labels = dict((path, label) for label, path in re.findall(
        r'label: "([^"]+)",.*?urlPath: "/([a-z/-]+)"', src, re.S))
    for pid in PLACES:
        feat = app_triage.PLATFORM[pid]
        assert labels[feat.opens] in feat.how, pid


# --- review 2026-11-17 -------------------------------------------------------------

def _offered_after(reply):
    return app_triage.already_offered([
        {"role": "user", "content": "make me a landing page"},
        {"role": "assistant", "content": reply},
        {"role": "user", "content": "how do I put it online?"}])


def test_building_does_not_count_as_offering_publish():
    got = _offered_after("Building it. [Open App Builder](#aiui-open:app-builder)")
    assert "app_builder" in got
    assert "publish" not in got and "deploy_vercel" not in got


def test_an_automation_does_not_count_as_offering_an_agent():
    got = _offered_after("[Set up in AI Agents](#aiui-open:ai-agents)")
    assert got & {"automations", "ai_agents"} == {"automations"}


def test_the_tool_doing_the_job_keeps_the_button_and_drops_the_how_line():
    p = app_triage.plan([("cron_jobs", 0.9)], set(), ["schedules"])
    out = app_triage.with_buttons("Done, it runs every Monday at 9.", p)
    assert app_triage.PLATFORM["cron_jobs"].how not in out
    assert "[Open Cron Jobs](#aiui-open:cronjobs)" in out
    b = app_triage.brief(p)
    assert "recommend it as the straightforward way" not in b
    assert "You are doing this now" in b


def test_without_the_tool_the_how_line_is_said():
    p = app_triage.plan([("cron_jobs", 0.9)], set(), [])
    out = app_triage.with_buttons("You can do that.", p)
    assert app_triage.PLATFORM["cron_jobs"].how in out


def test_each_part_names_a_tool_the_chat_really_has():
    for feat in app_triage.PLATFORM.values():
        if feat.tool:
            assert feat.tool in agent_jev.TOOL_NOTES, feat.id


def test_a_long_limit_reads_as_a_sentence():
    """Live 2026-11-17: "...such as turning a text column into a dropdown
    yet." The "yet" goes before the limit, so any length of it reads."""
    p = app_triage.plan([("airtable", 0.95)], set(), [])
    out = app_triage.with_buttons("Airtable fits this.", p)
    assert "Airtable cannot yet make a new base" in out
    assert "dropdown yet" not in out
    b = app_triage.brief(p)
    assert "IO cannot yet make a new base" in b
    intro = app_triage.with_buttons("Here is a way.", p)
    assert "(it cannot yet make a new base" in intro


def test_the_platform_is_asked_as_the_part_to_use_or_open():
    """Live 2026-11-17: asked the apps' question, where "a general question"
    is a no, "can I talk to my agents from Telegram?" scored 0.68 and got no
    button. The platform's parts are asked their own question; the apps'
    question, which their 0.90 was measured on, is unchanged."""
    ids = app_triage.catalogue_ids()
    _state, qs = agent_jev.apps_request("can I talk to my agents from Telegram?")
    plat = qs["a%d" % ids.index("channels")]
    assert "the part of the platform to use or open" in plat["instructions"]
    assert "how, where or whether" in plat["criteria"]["true"]
    app = qs["a%d" % ids.index("airtable")]
    assert app["instructions"].startswith("To do what the person wants, would Airtable, an app for ")
    assert "a general question" in app["criteria"]["false"]


def test_a_long_limit_reads_as_a_sentence_for_an_app_they_have_too():
    p = app_triage.plan([("airtable", 0.95)], {"airtable"}, [])
    out = app_triage.with_buttons("Airtable is where your leads go.", p)
    assert "Airtable cannot yet make a new base" in out
    assert "dropdown yet" not in out
