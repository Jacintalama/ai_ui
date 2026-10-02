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
    # Measured on the build host: detect exits 2 when it finds problems.
    assert "Exit code 2" in rules
    assert "COMPLETED" in rules


def test_the_rules_say_why_nobody_can_answer_with_checked_facts():
    # Impeccable's own context output tells the model to treat "you are
    # unattended" in a system prompt as no evidence and to probe once. The
    # rules answer with the two facts that probe would find.
    rules = design_skill.system_prompt(SLUG)
    assert "no structured question tool" in rules
    assert "serve-question` exits 2" in rules


def test_the_rules_keep_the_build_to_one_unattended_pass():
    rules = design_skill.system_prompt(SLUG)
    for step in ("direction round", "comps", "component review",
                 "subagents", "finish reviewer"):
        assert step in rules, step
    assert "apps/crumb-and-co/DESIGN.md" in rules


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
    assert design_skill.disallowed_tools(design, slug) == ()
    assert design_skill.env(design, slug) == {}
    assert design_skill.remote_prefix(design, slug) == ""


def test_a_marked_run_gets_the_rules_and_the_cap():
    args = design_skill.cli_args("impeccable", SLUG)
    assert args == ["--append-system-prompt", design_skill.system_prompt(SLUG),
                    "--max-budget-usd", "1.50"]


def test_a_marked_run_loses_the_question_and_subagent_tools():
    # Task is the subagent tool on the host's 2.1.140, Agent its later name.
    # Checked on the host 2026-10-02: the list is accepted and takes the
    # tools out (25 to 23).
    assert design_skill.disallowed_tools("impeccable", SLUG) == (
        "AskUserQuestion", "Task", "Agent")
    assert design_skill.disallowed_tools(None, SLUG) == ()
    assert design_skill.disallowed_tools("impeccable", None) == ()


def test_build_model_makes_one_flag_from_both_lists(monkeypatch):
    extra = ("AskUserQuestion", "Task", "Agent")
    assert build_model.cli_args(extra) == [
        "--disallowedTools", "AskUserQuestion,Task,Agent"]
    monkeypatch.setenv("APP_BUILD_MODEL", "openai/gpt-5.1-codex")
    args = build_model.cli_args(extra)
    assert args.count("--disallowedTools") == 1
    tools = args[args.index("--disallowedTools") + 1].split(",")
    assert tools == ["EnterPlanMode", "ExitPlanMode", "AskUserQuestion",
                     "EnterWorktree", "Task", "Agent"]


def test_build_model_is_unchanged_without_extra_tools(monkeypatch):
    assert build_model.cli_args() == []
    monkeypatch.setenv("APP_BUILD_MODEL", "openai/gpt-5.1-codex")
    assert build_model.cli_args() == [
        "--model", "openai/gpt-5.1-codex",
        "--disallowedTools", build_model.DISALLOWED_TOOLS]


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
