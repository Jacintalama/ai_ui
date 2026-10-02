"""The design skill an App Builder run is given, and how the run is told.

An agent can have the Impeccable skill ticked on its Edit agent form. That
agent never writes code: create_app and apply_app_change start an App Builder
run, which is Claude Code. So ticking the skill has to reach that run, or it
would only change the words the agent types. This module is the whole of
that reach: who asked (for_agent), and what the run gets (system_prompt,
cli_args, env, remote_prefix).

Impeccable (https://impeccable.style, Apache 2.0) is written for a person at
the keyboard. Its setup interviews the user, and its design step can open a
question page and wait for an answer. A build here is unattended and has 600
seconds, so every run that gets the skill also gets rules that turn those
steps off, and loses the question tool. Checked on the build host on
2026-10-02 with Claude Code 2.1.140: --disallowedTools AskUserQuestion takes
the tool away, and a skill linked into the run's own .claude/skills is loaded
by that run and by no other.

The rules go in as a system prompt rather than into the task prompt, because
the executors cut the task prompt at MAX_PROMPT_CHARS and a fresh-build
prompt is already longer than that.

Everything here fails open. An unknown agent or a database error leaves the
build exactly as it was before this existed. A marked run on a host without
the skill still gets the rules, the cap and the safety flags, and is told to
say the skill is missing and build to the rules that need no skill.

The rules were checked line by line against Impeccable v4.4.0 as installed
and its engine's real output on the build host, and each one answers a way a
marked run was shown to stop, ask, overspend or restyle too much; the tests
in tests/test_design_skill.py name them.
"""
from __future__ import annotations

import json
import logging
import math
import os

from sqlalchemy import text

import agent_skills
from db import session

logger = logging.getLogger(__name__)

IMPECCABLE = "impeccable"

#: Where scripts/install_impeccable.sh puts the skill on the build host.
#: Expanded by the build user's own shell, so it is that user's home.
REMOTE_SKILL_DIR = "$HOME/.impeccable/skills/impeccable"

DEFAULT_MAX_BUDGET_USD = "1.50"

_RULES = """IMPECCABLE DESIGN SKILL, FOR THIS RUN

The person who asked for this work chose the Impeccable design skill. Before \
you write or change any HTML, CSS or interface code, load it with the Skill \
tool, skill "impeccable", args set to the request in one line. Never load it \
with no args: with none the skill shows a menu and stops. These rules are the \
brief, so where the skill and they disagree, they win.

1. Nobody can answer during this run. That is checked, not a default: this \
session has no question tool, and `impeccable serve-question` exits 2 here \
because there is no browser. That exit is the failed probe the skill's \
AUTONOMY_DIRECTIVE_CHECK asks for, so do not probe again, and settle \
WORLD_DISCOVERY_REQUIRED yourself. Infer everything the skill would ask \
(audience, purpose, scope, stack, copy, direction) from the request, and say \
so in one line. Never ask in plain text, never stop to wait, and use \
NEEDS_INPUT only for a missing credential: the end of your turn is the end of \
the run, and a reply without a COMPLETED line is a failed build.
2. If apps/{slug}/PRODUCT.md is missing, write it from the request, marking \
every inferred fact "(inferred)"; if it exists, keep it and change only what \
this request changes. Run the skill's context command with --target \
apps/{slug}. Anything written outside apps/{slug}/ is thrown away when the \
run ends.
3. Build code-led, in one pass. Do not run concept-seed, serve-question, \
build-phase, comp-spec, font-match, generate-image or surface-brief, and do \
not do their rounds by hand. No subagents, and no finish review or documenter \
in any form, including the in-thread versions in reference/degraded/. No dev \
server, browser, live mode or screenshots. When you finish, this platform \
loads the app in a real browser and runs a narrow fix pass on any load error, \
and a change to an app that loaded cleanly before is reverted if it no longer \
loads.
4. Read reference/craft-floor.md before your first UI edit. Record the \
palette, type and spacing in apps/{slug}/DESIGN.md yourself, in a few lines \
and without document.md: create it for a new app, update only what you \
changed for an existing one.
5. The task's own platform rules still hold: its stack, CDN block, file \
layout, content and README rules. Impeccable decides the design inside them.
6. Before you finish, run .claude/skills/impeccable/scripts/impeccable detect \
once: over apps/{slug} for a new app, over only the files you changed for a \
change to an existing one. Exit code 2 means it found problems, not that it \
failed. Fix, in one batch, the findings in code you wrote this run; leave the \
rest, and do not run it again.
7. Changing an app that already exists is a refinement: keep its look, copy \
and behaviour outside what was asked. The task's limits on file reads and \
edits apply to the app's code; loading the skill, the craft floor, \
PRODUCT.md, DESIGN.md and the detect run do not count against them.
8. End your final message with the task's COMPLETED block: a line starting \
`COMPLETED:` with your summary, followed only by what the task's own \
COMPLETED format adds (its Next ideas and commit line). Nothing after it, and \
never a question.

If the impeccable skill is not available, say so in one line and follow \
rules 1, 5, 7 and 8 anyway."""

#: Taken away from a marked run. The question tool because nobody can answer;
#: the subagent tool (Task on the host's 2.1.140, Agent in later releases)
#: because Impeccable's full flow spawns reviewer and documenter agents, each
#: a second bill inside one build. Checked on the host 2026-10-02: the CLI
#: accepts this list and the tool count drops from 25 to 23.
_DISALLOWED = ("AskUserQuestion", "Task", "Agent")


def _on(design, slug) -> bool:
    return design == IMPECCABLE and bool(slug)


def system_prompt(slug: str) -> str:
    """The rules for one marked run. str.replace, not format: the rules are
    prose and a brace in them must not become a template field."""
    return _RULES.replace("{slug}", slug)


def max_budget_usd() -> str:
    """The most one marked run may spend, as Claude Code's --max-budget-usd.

    A cap rather than a hope: Impeccable's own guidance is to go all out, and
    a run that loops on its design checker would otherwise spend until the
    600 second limit. Anything that is not a positive finite number falls
    back to the default rather than to no cap.
    """
    raw = os.environ.get("IMPECCABLE_MAX_BUDGET_USD", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAX_BUDGET_USD
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_MAX_BUDGET_USD
    return raw


def cli_args(design: str | None, slug: str | None) -> list[str]:
    """Extra claude arguments for a marked run, none for any other. The
    tools it loses go through build_model.cli_args instead, so a run has one
    --disallowedTools list whether or not a model override is set."""
    if not _on(design, slug):
        return []
    return ["--append-system-prompt", system_prompt(slug),
            "--max-budget-usd", max_budget_usd()]


def disallowed_tools(design: str | None, slug: str | None) -> tuple[str, ...]:
    """The tools a marked run loses, for build_model.cli_args."""
    return _DISALLOWED if _on(design, slug) else ()


def env(design: str | None, slug: str | None) -> dict[str, str]:
    """Environment for a marked run: Impeccable's question page off. Its
    engine honours this variable and answers "use the structured question
    tool instead", which the run does not have."""
    return {"IMPECCABLE_QUESTION_DISABLED": "1"} if _on(design, slug) else {}


def remote_prefix(design: str | None, slug: str | None) -> str:
    """Shell run on the build host in /agent/work/<slug>, before claude.

    Links the installed skill into this run's own project skills, so only a
    marked run can load it; the folder is deleted when the run ends and is
    never synced back, because only apps/<slug>/ is. `|| true` because the
    remote command runs under set -e, and a host without the skill must
    still build.

    Any other run in an app folder removes the link first. Only a completed
    run deletes /agent/work/<slug>, so a marked run that hit its cap or the
    time limit leaves the link behind, and the next run there, an unmarked
    change from the App Builder page say, would otherwise load the skill with
    none of the rules, the cap or the safety flags.
    """
    if not slug:
        return ""
    if not _on(design, slug):
        return "rm -f .claude/skills/impeccable 2>/dev/null || true; "
    return ('{ mkdir -p .claude/skills && ln -sfn "%s" '
            ".claude/skills/impeccable; } || true; "
            "export IMPECCABLE_QUESTION_DISABLED=1; " % REMOTE_SKILL_DIR)


def skill_from_meta(meta) -> str | None:
    """IMPECCABLE when an agent's meta has it ticked, else None."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return None
    return IMPECCABLE if IMPECCABLE in agent_skills._ids_from(meta) else None


async def for_agent(user_email, agent_id) -> str | None:
    """The design skill for a job this person's agent started, or None.

    Reads the agent row itself rather than taking a flag from the caller:
    the caller is a tool the model drives, and what the model may choose is
    what to build, not how much the build may spend. Scoped to the caller's
    own agent, so one person's id cannot borrow another's settings.
    """
    if not (isinstance(agent_id, str) and agent_id.startswith("agent-")
            and isinstance(user_email, str) and user_email):
        return None
    try:
        async with session() as s:
            row = (await s.execute(text(
                "SELECT m.meta FROM public.model m "
                'JOIN public."user" u ON u.id = m.user_id '
                "WHERE m.id = :agent_id AND lower(u.email) = lower(:email)"),
                {"agent_id": agent_id, "email": user_email})).first()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("design skill lookup for %s failed: %s",
                       agent_id, type(exc).__name__)
        return None
    return skill_from_meta(row[0]) if row else None
