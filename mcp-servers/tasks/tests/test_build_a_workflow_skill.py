"""The build-a-workflow skill: an n8n workflow from plain words.

Lukas, standup 2026-11-19: people who never automated anything should get a
workflow by describing a job, without being asked "what's the trigger?".
The body is the whole feature, so what it must tell the model is pinned
here. Design: docs/superpowers/specs/2026-11-23-build-a-workflow-skill-design.md
"""
import agent_skills


def _skill():
    return agent_skills.load_all(refresh=True)["build-a-workflow"]


def test_it_loads_and_fits():
    s = _skill()
    assert 0 < len(s["body"]) <= agent_skills.MAX_SKILL_CHARS
    assert "server:mcp-proxy" in s["tools"]


def test_it_never_asks_for_a_trigger_in_n8n_words():
    body = _skill()["body"]
    assert "Never say trigger" in body
    assert "When should this happen?" in body


def test_it_uses_the_apps_connected_in_aiui():
    body = _skill()["body"]
    assert "link_aiui" in body and "create_workflow" in body


def test_it_says_the_plan_back_and_builds_switched_off():
    body = _skill()["body"]
    assert "only after they say yes" in body
    assert "switched off" in body


def test_an_email_arriving_goes_to_automations_not_n8n():
    body = _skill()["body"]
    assert "when an email arrives" in body.lower()
    assert "Automations" in body


def test_a_plain_timed_job_goes_to_schedules():
    assert "Schedules" in _skill()["body"]


def test_no_n8n_connected_is_said_not_guessed():
    body = _skill()["body"]
    assert "Connections" in body and "not connected" in body


def test_whether_n8n_is_connected_is_the_first_thing_checked():
    """Live 2026-11-23, three runs with no n8n connected: none said so, and
    one promised to build. The check was step 3 and a section at the end."""
    body = _skill()["body"]
    first = body.index("## Steps")
    assert body.index("not connected") < body.index("1. ", first)


def test_the_jargon_list_covers_what_slipped_through_live():
    """The same runs said "(a webhook in n8n)" and "a plain POST"."""
    body = _skill()["body"]
    for word in ("webhook", "endpoint", "POST", "not even in brackets"):
        assert word in body, word


def test_it_lets_them_choose_before_the_n8n_steps():
    """Live 2026-11-24: offered n8n, Zapier and Automations under the
    answer, the skill still opened with "I cannot build this right now"."""
    body = _skill()["body"]
    assert "let them choose first" in body
    assert body.index("let them choose first") < body.index("## Steps")


def test_the_choice_comes_before_saying_n8n_is_not_connected():
    """Review 2026-11-24: "say so in your first sentence" came before the
    choice, so the first sentence could still be "n8n is not connected"."""
    body = _skill()["body"]
    assert body.index("let them choose first") < body.index("first sentence")
