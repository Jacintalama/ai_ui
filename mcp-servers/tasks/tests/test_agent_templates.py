"""The templates every user gets a copy of.

These are checked hard because they go out to every account on the platform
and, once someone owns their copy, editing the template here never reaches
them again.
"""
import re

import pytest

from agent_templates import TEMPLATES

# The page enforces a one word name so the agent can be called by name in a
# sentence. A template that cannot be saved through the form is a bug.
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,23}$")

KNOWN_TOOLS = {
    "server:mcp-proxy", "gmail", "calendar", "gdrive",
    "documents", "excel_creator", "executive_dashboard", "remember",
}


def test_there_are_two_templates():
    assert len(TEMPLATES) == 2


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_the_name_is_one_word_and_mentionable(t):
    assert NAME_RE.match(t["name"]), t["name"]


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_the_instructions_are_real_and_within_the_form_limit(t):
    assert t["instructions"].strip()
    assert len(t["instructions"]) <= 4000


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_every_tool_named_is_one_the_platform_has(t):
    unknown = set(t["tool_ids"]) - KNOWN_TOOLS
    assert not unknown, unknown


def test_the_slugs_are_distinct():
    slugs = [t["slug"] for t in TEMPLATES]
    assert len(set(slugs)) == len(slugs)


def test_no_template_carries_an_access_grant():
    """Nothing seeded may be shared. Each copy belongs to one person."""
    for t in TEMPLATES:
        assert "access_grants" not in t


# The role is what the card shows under the name and what the agent is told it
# does. A new account should start with one rather than a blank line.

ROLE_MAX_CHARS = 32


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_every_template_names_a_role_the_form_would_accept(t):
    assert t["role"].strip(), t["slug"]
    assert len(t["role"]) <= ROLE_MAX_CHARS, t["role"]


def test_the_role_is_carried_into_the_created_agent():
    """It rides in meta beside toolIds. If _body_for dropped it, every seeded
    agent would arrive roleless and only a hand edit would fix it."""
    from routes_agents import _body_for
    body = _body_for(TEMPLATES[0], "agent-ada-0001")
    assert body["meta"]["role"] == TEMPLATES[0]["role"]


async def test_the_templates_endpoint_hands_the_role_to_the_page():
    """The page prefills the form from this response. A role that exists in
    TEMPLATES but never crosses the wire would leave "Use this template"
    producing a roleless agent, which is the one place a role is guaranteed
    to be right."""
    from routes_agents import templates as templates_endpoint
    out = await templates_endpoint()
    by_slug = {t["slug"]: t for t in out["templates"]}
    assert by_slug["ada"]["role"] == "Project manager"
    assert by_slug["mia"]["role"] == "Receptionist"
