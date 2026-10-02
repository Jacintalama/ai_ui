"""design_skill: which runs get Impeccable, and what such a run is given.

An unmarked run must come out exactly as it did before this module existed,
so every "off" case asserts an empty result rather than merely a missing
flag.
"""
import json
from contextlib import asynccontextmanager

import pytest

import build_model
import design_skill

SLUG = "crumb-and-co"


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("APP_BUILD_MODEL", raising=False)
    monkeypatch.delenv("IMPECCABLE_MAX_BUDGET_USD", raising=False)


# --- the rules the run is given --------------------------------------------

def test_the_rules_name_the_app_folder_and_the_skill():
    rules = design_skill.system_prompt(SLUG)
    assert "apps/crumb-and-co/" in rules
    assert "Skill tool" in rules and "impeccable" in rules


def test_the_rules_turn_off_everything_that_waits_for_a_person():
    rules = design_skill.system_prompt(SLUG)
    assert "NEEDS_INPUT" in rules
    assert "serve-question" in rules
    assert "PRODUCT.md" in rules and "(inferred)" in rules


def test_the_rules_run_the_checker_once_and_keep_the_ending():
    rules = design_skill.system_prompt(SLUG)
    assert "detect apps/crumb-and-co" in rules
    assert "COMPLETED" in rules


# --- the spend cap ---------------------------------------------------------

def test_the_cap_defaults_to_a_dollar_fifty():
    assert design_skill.max_budget_usd() == "1.50"


def test_the_cap_can_be_set(monkeypatch):
    monkeypatch.setenv("IMPECCABLE_MAX_BUDGET_USD", "0.75")
    assert design_skill.max_budget_usd() == "0.75"


@pytest.mark.parametrize("bad", ["", "  ", "lots", "0", "-1", "nan", "inf"])
def test_a_bad_cap_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv("IMPECCABLE_MAX_BUDGET_USD", bad)
    assert design_skill.max_budget_usd() == "1.50"


# --- what reaches the claude command ---------------------------------------

@pytest.mark.parametrize("design,slug", [
    (None, SLUG), ("", SLUG), ("something-else", SLUG), ("impeccable", None),
    ("impeccable", ""),
])
def test_an_unmarked_run_gets_nothing(design, slug):
    assert design_skill.cli_args(design, slug) == []
    assert design_skill.env(design, slug) == {}
    assert design_skill.remote_prefix(design, slug) == ""


def test_a_marked_run_gets_the_rules_the_cap_and_no_question_tool():
    args = design_skill.cli_args("impeccable", SLUG)
    assert args[args.index("--append-system-prompt") + 1] == \
        design_skill.system_prompt(SLUG)
    assert args[args.index("--max-budget-usd") + 1] == "1.50"
    assert args[args.index("--disallowedTools") + 1] == "AskUserQuestion"


def test_with_a_model_override_the_question_tool_is_already_gone(monkeypatch):
    # build_model passes its own --disallowedTools with the override, and a
    # second one is not something the CLI documents merging.
    monkeypatch.setenv("APP_BUILD_MODEL", "openai/gpt-5.1-codex")
    assert "--disallowedTools" not in design_skill.cli_args("impeccable", SLUG)
    assert "AskUserQuestion" in build_model.DISALLOWED_TOOLS.split(",")


def test_a_marked_run_turns_the_question_page_off():
    assert design_skill.env("impeccable", SLUG) == {
        "IMPECCABLE_QUESTION_DISABLED": "1"}


def test_the_remote_prefix_links_the_skill_into_this_run_only():
    prefix = design_skill.remote_prefix("impeccable", SLUG)
    assert 'ln -sfn "$HOME/.impeccable/skills/impeccable" ' \
           ".claude/skills/impeccable" in prefix
    # A missing skill on the host must not fail the build under set -e.
    assert "} || true; " in prefix
    assert "export IMPECCABLE_QUESTION_DISABLED=1; " in prefix
    assert prefix.endswith("; ")


# --- who asked -------------------------------------------------------------

@pytest.mark.parametrize("meta,expected", [
    ({"skillIds": ["inbox-triage", "impeccable"]}, "impeccable"),
    (json.dumps({"skillIds": ["impeccable"]}), "impeccable"),
    ({"skillIds": ["build-an-app"]}, None),
    ({"skillIds": "impeccable"}, None),
    ({}, None),
    (None, None),
    ("not json", None),
])
def test_the_skill_is_read_from_the_agent_meta(meta, expected):
    assert design_skill.skill_from_meta(meta) == expected


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def _fake_session(row=None, error=None, seen=None):
    class _S:
        async def execute(self, statement, params=None):
            if seen is not None:
                seen.append(params)
            if error:
                raise error
            return _Result(row)

    @asynccontextmanager
    async def _session():
        yield _S()

    return _session


async def test_an_agent_with_the_skill_marks_the_job(monkeypatch):
    seen = []
    monkeypatch.setattr(design_skill, "session", _fake_session(
        row=({"skillIds": ["impeccable"]},), seen=seen))
    assert await design_skill.for_agent(
        "a@example.com", "agent-dev-c82b") == "impeccable"
    # The lookup is the caller's own agent, never just any row with that id.
    assert seen == [{"agent_id": "agent-dev-c82b", "email": "a@example.com"}]


async def test_no_row_means_no_mark(monkeypatch):
    monkeypatch.setattr(design_skill, "session", _fake_session(row=None))
    assert await design_skill.for_agent("a@example.com", "agent-x") is None


async def test_a_database_error_leaves_the_build_as_it_was(monkeypatch):
    monkeypatch.setattr(design_skill, "session",
                        _fake_session(error=RuntimeError("db down")))
    assert await design_skill.for_agent("a@example.com", "agent-x") is None


@pytest.mark.parametrize("email,agent_id", [
    ("a@example.com", None), ("a@example.com", ""),
    ("a@example.com", "gpt-4o-mini"), ("a@example.com", 42),
    ("", "agent-dev-c82b"), (None, "agent-dev-c82b"),
])
async def test_anything_but_an_agent_never_touches_the_database(
        monkeypatch, email, agent_id):
    seen = []
    monkeypatch.setattr(design_skill, "session", _fake_session(seen=seen))
    assert await design_skill.for_agent(email, agent_id) is None
    assert seen == []
