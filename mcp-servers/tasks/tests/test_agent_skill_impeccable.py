"""The Impeccable design skill, as an agent sees it in the catalogue.

Ticking it on an agent is what turns the real Impeccable skill on in the
builder for that agent's apps (design_skill.py), so it has to be findable by
the words people actually use when they want a better looking site, and it
has to say where it came from: it is condensed from Impeccable, which is
Apache 2.0.
"""
import os

import pytest

import agent_skills

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_FILE = os.path.join(HERE, "..", "agent_skills", "impeccable", "SKILL.md")


def test_it_is_a_valid_skill_that_needs_the_app_tool():
    skill = agent_skills.load_all(refresh=True)["impeccable"]
    assert skill["tools"] == ["code"]
    assert len(skill["body"]) <= agent_skills.MAX_SKILL_CHARS
    assert {"design", "website"} <= set(skill["tags"])


def test_it_never_says_built_before_the_build_says_so():
    # 2026-10-02, the first real run: Dev, with only this skill ticked,
    # answered "Built Crumb and Co landing page." the moment create_app
    # returned, minutes before the build finished.
    body = agent_skills.load_all(refresh=True)["impeccable"]["body"]
    assert "takes a few minutes" in body
    assert "build_status" in body


def test_it_credits_impeccable_and_its_licence():
    text = open(SKILL_FILE, encoding="utf-8").read()
    assert "impeccable.style" in text
    assert "Apache" in text


@pytest.mark.parametrize("ask", [
    "design a website",
    "redesign my landing page",
    "make my site look better",
    "polish the design of my app",
])
def test_a_design_request_finds_it_first(ask):
    agent_skills.load_all(refresh=True)
    assert agent_skills.search(ask, 5)[0]["name"] == "impeccable"
